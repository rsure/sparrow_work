// 模块说明：把 AgentEvent 写成 SSE 帧的那个「水龙头」。
//
// 为什么单独成类：SseEmitter 只能在 Web 线程里安全写，业务代码（工具线程、模型回调线程）
// 不应该知道 SSE 长什么样。这里做一层隔离：业务只管 emit，格式化与线程安全都在这。
// 帧格式必须与 Python 一致：event: xxx\ndata: {...}\n\n（前端 sse() 按这个解析）。
package com.example.backendjava.chat.event;

// 标准库：IOException 来自 send 失败（客户端断开）
import java.io.IOException;

// Spring：MediaType 指定按 JSON 序列化，StringHttpMessageConverter 会把 String 当文本发出去
import org.springframework.http.MediaType;
// Spring：SseEmitter 是服务端 SSE 的出口对象
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

// 已有的事件接口与信封类型
import com.example.backendjava.dto.AgentDtos;

/**
 * SSE 事件出口：一个实例对应「一条 HTTP 流」。
 *
 * <p>线程安全：{@code send} 用对象锁串行化。SseEmitter 内部会做缓冲，
 * 并发写同一个 emitter 可能丢帧或抛 IllegalStateException，加锁最省心。</p>
 */
public class SseAgentEventSink implements AgentEventSink {

    /** 当前流对应的 emitter。 */
    private final SseEmitter emitter;

    /** 串行化 send 的锁；不要用 emitter 自己当锁，避免和 Spring 内部锁交叉。 */
    private final Object lock = new Object();

    /** 是否已关闭（客户端断开或我们主动 complete 之后置 true），关闭后一切事件直接丢弃。 */
    private volatile boolean closed;

    /**
     * 构造出口。
     *
     * @param emitter 本流对应的 SseEmitter
     */
    public SseAgentEventSink(SseEmitter emitter) {
        this.emitter = emitter;
    }

    /**
     * 发送一条事件。
     *
     * @param event 事件信封；type 作为 SSE 的 event 名，data 作为 JSON 负载
     */
    @Override
    public void emit(AgentDtos.AgentEvent event) {
        // 已关闭（客户端走了）就没必要再写，直接丢，避免无谓的异常刷日志
        if (closed) {
            return;
        }
        synchronized (lock) {
            // 双重检查：等锁期间可能已经被别的线程关掉了
            if (closed) {
                return;
            }
            try {
                // 注意：data 传 Map + APPLICATION_JSON，Spring 会用 Jackson 序列化成 JSON 对象。
                // 千万不要「自己序列化成字符串再传 APPLICATION_JSON」，那样会被再包一层引号。
                emitter.send(SseEmitter.event()
                        .name(event.type())
                        .data(event.data(), MediaType.APPLICATION_JSON));
            } catch (IOException | IllegalStateException ex) {
                // 客户端断开或容器已回收：标记关闭，后续静默丢弃（这不是业务错误，不打 ERROR）
                closed = true;
            }
        }
    }

    /**
     * 正常结束这条流（前端会看到流关闭）。
     *
     * <p>幂等：重复调用不会报错。</p>
     */
    public void close() {
        synchronized (lock) {
            if (closed) {
                return;
            }
            closed = true;
            try {
                emitter.complete();
            } catch (RuntimeException ex) {
                // 已经是完成/超时状态：忽略，close 的语义就是「尽量关掉」
            }
        }
    }

    /**
     * 异常结束这条流。
     *
     * @param error 导致流结束的异常
     */
    public void closeWithError(Throwable error) {
        synchronized (lock) {
            if (closed) {
                return;
            }
            closed = true;
            try {
                emitter.completeWithError(error);
            } catch (RuntimeException ex) {
                // 同上：状态已结束就忽略
            }
        }
    }

    /**
     * 查询这条流是否已结束。
     *
     * @return true 表示已关闭
     */
    public boolean isClosed() {
        return closed;
    }
}
