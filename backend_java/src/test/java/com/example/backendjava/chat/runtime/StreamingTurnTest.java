// 模块说明：StreamingTurn 的单元测试。
//
// 为什么必须单独测这一层：langchain4j 1.22 的 TokenStream.start() 是「发出去就返回」的，
// 回调（partial / complete / error）会在别的线程上晚一点才到。之前 /api/chat/stream 的
// 空答案事故就是「以为 start() 阻塞、返回后立刻收尾关流」造成的。
// 这里用假的 TokenStream 把「start() 立刻返回、回调稍后才来」这个时序固定下来，
// 保证等待逻辑本身的语义不再退化。
// 注意：本文件只测「等待器」，测不到 ChatServiceImpl.runTurn 有没有真的调用 await；
// 那一层靠接口联调（真实 SSE 请求必须收到 token 事件且 answer 非空）来守。
package com.example.backendjava.chat.runtime;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// 断言工具：断言等待耗时、增量文本序列、终态标志
import static org.assertj.core.api.Assertions.assertThat;
// 断言工具：确认中断场景会抛 InterruptedException
import static org.assertj.core.api.Assertions.assertThatThrownBy;
// langchain4j 的回复对象：完成回调的参数
import dev.langchain4j.data.message.AiMessage;
// langchain4j 的聊天响应：完成回调里拿到的最终结果
import dev.langchain4j.model.chat.response.ChatResponse;
// langchain4j 的检索内容类型：假实现要提供 onRetrieved 方法签名
import dev.langchain4j.rag.content.Content;
// langchain4j 的流式对话句柄：被测代码必须能对它挂回调并 start()
import dev.langchain4j.service.TokenStream;
// langchain4j 的工具执行结果类型：假实现要提供 onToolExecuted 方法签名
import dev.langchain4j.service.tool.ToolExecution;
// 时间长度：表达等待超时
import java.time.Duration;
// 回调函数接口：假实现里保存与触发回调
import java.util.function.Consumer;
// 线程安全的列表：收集被转发的增量文本
import java.util.concurrent.CopyOnWriteArrayList;
// 列表接口：声明增量文本、检索内容的容器类型
import java.util.List;
// 原子整数：统计完成回调被触发了几次
import java.util.concurrent.atomic.AtomicInteger;
// 原子引用：保存回调里捕获到的失败原因
import java.util.concurrent.atomic.AtomicReference;

/**
 * 验证 {@link StreamingTurn} 的核心约定：start() 返回不等于本轮结束，必须等到终态回调。
 */
class StreamingTurnTest {

    /**
     * 模型异步返回时：start() 立刻返回，await 必须一直等到完成回调才放行。
     *
     * <p>这是事故的回归用例——如果 await 在 start() 返回时就返回，awaitMillis 会远小于 100ms。</p>
     *
     * @throws Exception 等待被中断时抛出
     */
    @Test
    void awaitWaitsForCompletionCallback() throws Exception {
        // 假的流：start() 什么都不做（模拟 1.22 的真实行为），回调由测试线程稍后手动触发
        FakeTokenStream stream = new FakeTokenStream();
        // 收集被转发的增量文本，用来确认 partial 回调没有被吞掉
        List<String> partials = new CopyOnWriteArrayList<>();
        // 记录完成回调次数
        AtomicInteger completed = new AtomicInteger();

        // 挂回调并 start()：这一步应当立刻返回，不阻塞
        StreamingTurn turn = StreamingTurn.start(stream,
                partials::add,
                response -> completed.incrementAndGet(),
                error -> {
                });

        // 另一个线程模拟模型：100ms 后先吐两个增量，再给完成回调
        Thread model = new Thread(() -> {
            try {
                Thread.sleep(100L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            stream.emitPartial("你");
            stream.emitPartial("好");
            stream.emitComplete();
        });
        model.start();

        // 等：上限给 5 秒，真实耗时应当在 100ms 量级
        long before = System.nanoTime();
        boolean finished = turn.await(Duration.ofSeconds(5));
        long waitedMs = (System.nanoTime() - before) / 1_000_000L;
        model.join();

        assertThat(finished).as("回调到齐后应当返回 true").isTrue();
        assertThat(waitedMs).as("必须真的等到回调，而不是 start() 一返回就走").isGreaterThanOrEqualTo(90L);
        assertThat(partials).as("增量文本要原样转发").containsExactly("你", "好");
        assertThat(completed).as("完成回调只触发一次").hasValue(1);
    }

    /**
     * 模型报错时：await 也要放行（否则会一直等到超时），并把异常转交给调用方。
     *
     * @throws Exception 等待被中断时抛出
     */
    @Test
    void errorCallbackReleasesAndRecordsError() throws Exception {
        FakeTokenStream stream = new FakeTokenStream();
        // 模型返回的失败原因
        IllegalStateException boom = new IllegalStateException("401 Unauthorized");
        // 记录是否把错误原样转发给调用方
        AtomicReference<Throwable> forwarded = new AtomicReference<>();

        StreamingTurn turn = StreamingTurn.start(stream, text -> {
        }, response -> {
        }, forwarded::set);

        Thread model = new Thread(() -> {
            try {
                Thread.sleep(50L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            stream.emitError(boom);
        });
        model.start();

        assertThat(turn.await(Duration.ofSeconds(5))).as("错误也是终态，应当放行").isTrue();
        model.join();
        assertThat(forwarded.get()).as("错误要转交给调用方自己的 onError").isSameAs(boom);
    }

    /**
     * 模型一直不回：await 到点返回 false，不能永久卡住执行线程。
     */
    @Test
    void awaitReturnsFalseOnTimeout() throws Exception {
        FakeTokenStream stream = new FakeTokenStream();
        StreamingTurn turn = StreamingTurn.start(stream, text -> {
        }, response -> {
        }, error -> {
        });

        long before = System.nanoTime();
        boolean finished = turn.await(Duration.ofMillis(80));
        long waitedMs = (System.nanoTime() - before) / 1_000_000L;

        assertThat(finished).as("没有任何终态回调时应当超时").isFalse();
        assertThat(waitedMs).as("应当等满超时时长").isGreaterThanOrEqualTo(70L);
    }

    /**
     * 同步模型（回调在 start() 里就到达）：信号不能丢，await 必须立刻返回 true。
     *
     * @throws Exception 等待被中断时抛出
     */
    @Test
    void completionBeforeAwaitIsNotLost() throws Exception {
        FakeTokenStream stream = new FakeTokenStream();
        // 模拟「同步返回」的实现：start() 里就把完成回调打出来
        stream.completeDuringStart = true;

        StreamingTurn turn = StreamingTurn.start(stream, text -> {
        }, response -> {
        }, error -> {
        });

        assertThat(turn.await(Duration.ofSeconds(1))).as("先到的完成信号不能丢").isTrue();
    }

    /**
     * 调用方的完成回调自己抛异常：仍然要放行，不能让执行线程卡到超时。
     *
     * @throws Exception 等待被中断时抛出
     */
    @Test
    void completionHandlerFailureStillReleases() throws Exception {
        FakeTokenStream stream = new FakeTokenStream();
        stream.completeDuringStart = true;

        StreamingTurn turn = StreamingTurn.start(stream, text -> {
        }, response -> {
            // 例如 recordUsage 里解析用量时炸了，这里模拟这种「收尾代码出错」
            throw new IllegalStateException("recordUsage failed");
        }, error -> {
        });

        assertThat(turn.await(Duration.ofSeconds(1))).as("回调抛异常也要放行").isTrue();
    }

    /**
     * 执行线程被中断（例如应用正在关闭）：await 抛 InterruptedException，把决定权交回调用方。
     */
    @Test
    void awaitPropagatesInterrupt() {
        FakeTokenStream stream = new FakeTokenStream();
        StreamingTurn turn = StreamingTurn.start(stream, text -> {
        }, response -> {
        }, error -> {
        });

        // 在测试线程里先给自己打中断标记，再进入等待：await 应当立刻抛出
        Thread.currentThread().interrupt();
        try {
            assertThatThrownBy(() -> turn.await(Duration.ofSeconds(5)))
                    .as("中断要原样抛出，由调用方决定怎么收尾")
                    .isInstanceOf(InterruptedException.class);
        } finally {
            // 清掉中断标记，避免影响同一个测试线程里的后续用例
            Thread.interrupted();
        }
    }

    /**
     * 假的 TokenStream：只记录回调，不主动触发，由测试精确控制时序。
     *
     * <p>start() 故意什么都不做——这正是 langchain4j 1.22 的实测行为（发出去就返回）。</p>
     */
    private static final class FakeTokenStream implements TokenStream {

        // 增量文本回调
        private Consumer<String> onPartialResponse;
        // 完成回调
        private Consumer<ChatResponse> onCompleteResponse;
        // 错误回调
        private Consumer<Throwable> onError;
        // 是否在 start() 里立刻打出完成回调（模拟同步实现）
        private boolean completeDuringStart;

        /**
         * 记录增量回调。
         *
         * @param handler 调用方传入的回调
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream onPartialResponse(Consumer<String> handler) {
            this.onPartialResponse = handler;
            return this;
        }

        /**
         * 检索回调：本用例不涉及 RAG，忽略即可。
         *
         * @param handler 调用方传入的回调
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream onRetrieved(Consumer<List<Content>> handler) {
            return this;
        }

        /**
         * 工具执行回调：本用例不涉及工具，忽略即可。
         *
         * @param handler 调用方传入的回调
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream onToolExecuted(Consumer<ToolExecution> handler) {
            return this;
        }

        /**
         * 记录完成回调。
         *
         * @param handler 调用方传入的回调
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream onCompleteResponse(Consumer<ChatResponse> handler) {
            this.onCompleteResponse = handler;
            return this;
        }

        /**
         * 记录错误回调。
         *
         * @param handler 调用方传入的回调
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream onError(Consumer<Throwable> handler) {
            this.onError = handler;
            return this;
        }

        /**
         * 错误忽略开关：本用例不涉及，原样返回。
         *
         * @return 自身，便于链式调用
         */
        @Override
        public TokenStream ignoreErrors() {
            return this;
        }

        /**
         * 启动：故意不阻塞、不触发任何回调，只在需要时同步给出完成回调。
         */
        @Override
        public void start() {
            if (completeDuringStart && onCompleteResponse != null) {
                onCompleteResponse.accept(emptyResponse());
            }
        }

        /**
         * 手动触发一次增量文本回调。
         *
         * @param text 增量文本
         */
        void emitPartial(String text) {
            onPartialResponse.accept(text);
        }

        /**
         * 手动触发一次完成回调。
         */
        void emitComplete() {
            onCompleteResponse.accept(emptyResponse());
        }

        /**
         * 手动触发一次错误回调。
         *
         * @param error 失败原因
         */
        void emitError(Throwable error) {
            onError.accept(error);
        }

        /**
         * 造一个最小可用的响应对象：测试不关心内容，只关心「终态到了」。
         *
         * @return 只带一句占位文本的响应
         */
        private static ChatResponse emptyResponse() {
            return ChatResponse.builder().aiMessage(AiMessage.from("ok")).build();
        }
    }
}
