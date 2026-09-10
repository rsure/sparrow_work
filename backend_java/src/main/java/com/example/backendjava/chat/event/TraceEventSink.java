// 模块说明：把事件写进 trace_event 表，供「轨迹」页回放与排查。
//
// 为什么要落库：SSE 事件是「一次性」的，用户关掉页面就没了；
// 出问题时要能回答「这一轮到底调了哪些工具、模型返回了什么」。
package com.example.backendjava.chat.event;

// 标准库：List 收集 token 片段，攒够一批再落库
import java.util.List;
// 标准库：Map 用于把事件 data 序列化成 JSON 字符串
import java.util.Map;
// 标准库：时间格式化
import java.time.Instant;

// Jackson：Map → JSON 字符串
import com.fasterxml.jackson.databind.ObjectMapper;

// 实体与仓库：落库
import com.example.backendjava.entity.TraceEvent;
import com.example.backendjava.repository.TraceEventRepository;
// 已有的事件接口与信封
import com.example.backendjava.dto.AgentDtos;

/**
 * 轨迹出口：把关键事件持久化到 trace_event 表。
 *
 * <p>只记「骨架事件」（tool_start/tool_end/confirm_required/error/done），
 * token 逐条落库会把表撑爆，且没有查询价值，所以显式跳过。</p>
 */
public class TraceEventSink implements AgentEventSink {

    /** 不落库的事件类型。 */
    private static final List<String> SKIPPED = List.of("token", "thinking");

    /** 轨迹仓库。 */
    private final TraceEventRepository repository;

    /**
     * 当前线程正在跑哪一轮。
     *
     * <p>为什么用 ThreadLocal 而不是普通字段：一轮对话一个线程，
     * 而这个是单例 Bean——两个会话同时跑时，普通字段会被后一个覆盖，
     * 结果 A 会话的轨迹被记到 B 会话的轮次下。</p>
     */
    private final ThreadLocal<String> turnId = ThreadLocal.withInitial(() -> "");

    /** 序列化 data 用。 */
    private final ObjectMapper objectMapper;

    /**
     * 构造轨迹出口。
     *
     * @param repository   轨迹仓库
     * @param objectMapper Spring 的 ObjectMapper
     */
    public TraceEventSink(TraceEventRepository repository, ObjectMapper objectMapper) {
        this.repository = repository;
        this.objectMapper = objectMapper;
    }

    /**
     * 设置当前线程的轮次 id，供后续事件共享。
     *
     * @param turnId 轮次 id
     */
    public void setTurnId(String turnId) {
        this.turnId.set(turnId == null ? "" : turnId);
    }

    /**
     * 清掉当前线程的轮次 id。
     *
     * <p>线程池会复用线程，一轮结束时不清，下一轮会继承上一轮的 id。</p>
     */
    public void clearTurnId() {
        this.turnId.remove();
    }

    /**
     * 写一条事件。
     *
     * @param event 事件信封
     */
    @Override
    public void emit(AgentDtos.AgentEvent event) {
        if (SKIPPED.contains(event.type())) {
            return;
        }
        Map<String, Object> data = event.data();
        // 会话 id 从载荷里取（每个载荷都带 session_id；error 事件没有，用空串兜底）
        Object sessionId = data.get("session_id");
        TraceEvent row = new TraceEvent();
        row.setSessionId(sessionId == null ? "" : String.valueOf(sessionId));
        row.setTurnId(turnId.get());
        row.setType(event.type());
        try {
            row.setPayload(objectMapper.writeValueAsString(data));
        } catch (Exception ex) {
            // 序列化失败就存空对象：宁可丢字段，不要让轨迹系统反过来打断对话
            row.setPayload("{}");
        }
        row.setCreatedAt(Instant.now().toString());
        repository.save(row);
    }
}
