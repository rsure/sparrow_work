// 模块说明：事件管道相关的 Bean 装配。
//
// 为什么单独一个配置类：这些类是「基础设施」，不是业务 Service，
// 集中在一处装配，读代码时一眼就能看出「事件从哪来、到哪去」。
package com.example.backendjava.config;

// 标准库：线程池与线程工厂
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
// 标准库：原子计数，给线程起可读名字
import java.util.concurrent.atomic.AtomicInteger;
// 标准库：List 组装出口链
import java.util.List;

// Jackson：轨迹出口要用
import com.fasterxml.jackson.databind.ObjectMapper;

// 本项目：仓库与出口实现
import com.example.backendjava.chat.event.CompositeAgentEventSink;
import com.example.backendjava.chat.event.TraceEventSink;
import com.example.backendjava.repository.TraceEventRepository;

// Spring：配置类与 Bean 声明
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 事件管道装配。
 */
@Configuration
public class AgentEventConfig {

    /**
     * 轨迹出口。
     *
     * @param repository   轨迹仓库
     * @param objectMapper Spring 的 ObjectMapper
     * @return 轨迹出口实例
     */
    @Bean
    public TraceEventSink traceEventSink(TraceEventRepository repository, ObjectMapper objectMapper) {
        return new TraceEventSink(repository, objectMapper);
    }

    /**
     * 对话轮次执行线程池。
     *
     * <p>为什么必须要有：{@code TokenStream.start()} 是阻塞调用，会把 Tomcat 线程占满一整轮；
     * 更关键的是「等用户确认」也会阻塞，绝不能占用 Web 线程。</p>
     *
     * @return 线程池
     */
    @Bean(destroyMethod = "shutdown")
    public ExecutorService chatTurnExecutor() {
        // 每个线程起个可读名字，jstack 时一眼看出是对话线程而不是 Tomcat 线程
        AtomicInteger counter = new AtomicInteger(1);
        ThreadFactory factory = runnable -> {
            Thread thread = new Thread(runnable, "chat-turn-" + counter.getAndIncrement());
            thread.setDaemon(true);
            return thread;
        };
        // 用 cached 池：一轮对话一个线程，等待确认时会长时间占住，固定大小容易饿死
        return Executors.newCachedThreadPool(factory);
    }
    /**
     * 记忆抽取线程池（单线程）。
     *
     * <p>为什么单独开：记忆抽取是一次额外的模型调用，慢且可以失败；
     * 如果和 {@link #chatTurnExecutor()} 混用，会跟下一轮对话抢线程，让用户感觉「发消息没反应」。
     * 单线程足够——抽取本来就该排在对话后面，不急着并行。</p>
     *
     * @return 单线程池；Bean 名 memoryExtractExecutor 供 {@code @Resource} 按名注入
     */
    @Bean(destroyMethod = "shutdown")
    public ExecutorService memoryExtractExecutor() {
        AtomicInteger counter = new AtomicInteger(1);
        ThreadFactory factory = runnable -> {
            Thread thread = new Thread(runnable, "memory-extract-" + counter.getAndIncrement());
            // 守护线程：应用关闭时不阻塞 JVM 退出
            thread.setDaemon(true);
            return thread;
        };
        return Executors.newSingleThreadExecutor(factory);
    }
    /**
     * 全局事件出口链。
     *
     * <p>目前只有轨迹出口；SSE 出口是「每条流一个」，不能做成单例，
     * 因此不在这里注册 —— 它由 ChatSessionBus 在每次开流时单独绑定。</p>
     *
     * @param traceSink 轨迹出口
     * @return 组合出口
     */
    @Bean
    public CompositeAgentEventSink backgroundEventSink(TraceEventSink traceSink) {
        return new CompositeAgentEventSink(List.of(traceSink));
    }
}
