// 模块说明：把「异步流式对话」包成「可以等它真的结束」的同步句柄。
//
// 背景（踩过的坑）：langchain4j 1.22 的 TokenStream.start() 只是把请求发出去，
// 增量文本 / 完成 / 失败这些回调会在别的线程上晚一点才到（实测：start() 474ms 返回，
// 第一个 token 在 1.7s 后才到）。如果调用方以为 start() 会阻塞到整轮结束，
// 就会在答案还是空串的时候就落库、发 done、关掉 SSE 流，
// 于是前端看到 answer=""，而模型随后真正吐出的内容全被丢弃。
//
// 这个类只做一件事：挂好回调 → start() → 提供 await(超时)。
// 真正的业务回调（攒答案、发事件、记用量）仍然由调用方传入，本类不掺和。
package com.example.backendjava.chat.runtime;

// langchain4j 的最终响应：完成回调的参数，调用方用它记用量
import dev.langchain4j.model.chat.response.ChatResponse;
// langchain4j 的流式对话句柄：本类负责给它挂回调并 start()
import dev.langchain4j.service.TokenStream;
// 日志门面：回调里抛出的异常要记下来，但不能让它把等待卡死
import org.slf4j.Logger;
// 日志门面工厂：拿到本类的 logger
import org.slf4j.LoggerFactory;
// 时间长度：表达「最多等多久」
import java.time.Duration;
// 参数校验：回调与超时不允许为 null
import java.util.Objects;
// 倒计数闩锁：本轮终态（完成或失败）到达时放行等待线程
import java.util.concurrent.CountDownLatch;
// 时间单位：配合 CountDownLatch.await 使用
import java.util.concurrent.TimeUnit;
// 回调函数接口：调用方把「攒答案 / 发事件」传进来
import java.util.function.Consumer;

/**
 * 一轮流式对话的可等待句柄。
 *
 * <p>用法：</p>
 * <pre>{@code
 * StreamingTurn turn = StreamingTurn.start(assistant.chat(message),
 *         partial -> { ... },        // 每段增量文本
 *         response -> { ... },       // 整轮成功完成
 *         error -> { ... });         // 失败
 * if (!turn.await(Duration.ofSeconds(280))) {
 *     // 超时：模型迟迟不结束
 * }
 * }</pre>
 *
 * <p>约定：{@link #await(Duration)} 返回 true 表示「已经收到终态回调」（成功或失败都算，
 * 具体原因由调用方在传入的 {@code onCompleteResponse} / {@code onError} 里自行处理）；
 * 返回 false 表示超时，即这一轮迟迟没有结果。</p>
 */
public final class StreamingTurn {

    /** 本类日志：只用来记录回调里抛出的异常，正常路径不打日志。 */
    private static final Logger log = LoggerFactory.getLogger(StreamingTurn.class);

    /** 终态闩锁：初值 1，完成或失败回调里各减 1，减到 0 时放行 await。 */
    private final CountDownLatch finished = new CountDownLatch(1);

    /** 私有构造：只允许通过 {@link #start} 创建，保证「挂回调 + 启动」一步完成。 */
    private StreamingTurn() {
    }

    /**
     * 挂好回调、启动这一轮，并返回可等待的句柄。
     *
     * <p>注意：本方法返回时模型通常还没开始回包，必须再调用 {@link #await(Duration)}。</p>
     *
     * @param stream             已由 AiServices 创建好、尚未启动的流
     * @param onPartialResponse  增量文本回调（攒答案、推事件）
     * @param onCompleteResponse 整轮成功回调（记用量、收尾）
     * @param onError            失败回调（发 error 事件）
     * @return 可等待本轮结束的句柄
     */
    public static StreamingTurn start(TokenStream stream,
                                      Consumer<String> onPartialResponse,
                                      Consumer<ChatResponse> onCompleteResponse,
                                      Consumer<Throwable> onError) {
        Objects.requireNonNull(stream, "stream");
        Objects.requireNonNull(onPartialResponse, "onPartialResponse");
        Objects.requireNonNull(onCompleteResponse, "onCompleteResponse");
        Objects.requireNonNull(onError, "onError");

        StreamingTurn turn = new StreamingTurn();
        // 1) 先挂回调再启动：1.22 里 token 可能来得很快，启动后再挂就漏了
        stream.onPartialResponse(onPartialResponse)
                // 2) 完成：必须先执行调用方的收尾（记用量），再放行等待；收尾抛异常也要放行
                .onCompleteResponse(response -> turn.completeQuietly(onCompleteResponse, response))
                // 3) 失败：同样要先转交错误再放行
                .onError(cause -> turn.failQuietly(onError, cause))
                // 4) start() 只是发请求，不阻塞——这正是本类存在的原因
                .start();
        return turn;
    }

    /**
     * 等本轮到达终态（成功完成或失败）。
     *
     * @param timeout 最长等待时长；到点还没终态就返回 false
     * @return true 表示已收到终态回调（成败看 {@link #error()}），false 表示超时
     * @throws InterruptedException 等待线程被中断时抛出（例如应用正在关闭），
     *                              由调用方决定怎么收尾；抛出时中断标记已被清除
     */
    public boolean await(Duration timeout) throws InterruptedException {
        Objects.requireNonNull(timeout, "timeout");
        // 负数或 0 按「立刻检查一次」处理，避免把负数传给 CountDownLatch
        long millis = Math.max(0L, timeout.toMillis());
        return finished.await(millis, TimeUnit.MILLISECONDS);
    }

    /**
     * 执行调用方的完成回调并放行等待。
     *
     * <p>为什么把异常吞掉：这里运行在模型的回调线程上，收尾代码（比如解析用量）出错
     * 不该让执行线程一直等到超时；记日志后照常放行，让用户先看到已经产出的答案。</p>
     *
     * @param handler  调用方的完成回调
     * @param response 模型的最终响应
     */
    private void completeQuietly(Consumer<ChatResponse> handler, ChatResponse response) {
        releaseAfter("完成", () -> handler.accept(response));
    }

    /**
     * 记录失败原因、执行调用方的错误回调并放行等待。
     *
     * @param handler 调用方的错误回调
     * @param cause   模型或传输层的失败原因
     */
    private void failQuietly(Consumer<Throwable> handler, Throwable cause) {
        releaseAfter("错误", () -> handler.accept(cause));
    }

    /**
     * 执行调用方回调并放行等待，回调抛异常时只记日志、不向上抛。
     *
     * <p>抽出来的原因：完成与失败两条路径的「执行回调 → 记日志 → 放行」完全同形，
     * 只是回调参数不同；写两遍容易出现「一边忘了 countDown 就永久卡住」的漏改。</p>
     *
     * @param stage  阶段名（完成 / 错误），只用于日志文案
     * @param action 调用方的回调动作
     */
    private void releaseAfter(String stage, Runnable action) {
        try {
            action.run();
        } catch (RuntimeException ex) {
            log.warn("流式对话{}回调抛出异常，已忽略并放行等待", stage, ex);
        } finally {
            // 无论回调成功还是抛异常都要放行，否则执行线程会一直等到超时
            finished.countDown();
        }
    }
}
