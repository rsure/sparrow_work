// 模块说明：LangGraph4j 图运行时的基础 Bean。先把“检查点保存器”装配好，业务图由学习者实现。
package com.example.backendjava.config;

// Spring 配置注解：声明本类是配置类，容器启动时会解析其中的 @Bean 方法
import org.springframework.context.annotation.Configuration;
// Spring Bean 注解：把方法返回值注册到容器，供其它组件注入
import org.springframework.context.annotation.Bean;
// 项目内：工具注册表接口，图节点执行工具时按名字取用
import com.example.backendjava.service.ToolRegistry;
// LangChain4j 消息类型：条件边要判断「最后一条 AI 消息是否带工具调用」（代码当前被注释，保留供恢复时使用）
import dev.langchain4j.data.message.AiMessage;
// LangGraph4j 图编译配置：挂检查点保存器、递归上限与中断点
import org.bsc.langgraph4j.CompileConfig;
// LangGraph4j 编译后的图：可执行、可带 threadId 恢复
import org.bsc.langgraph4j.CompiledGraph;
// LangGraph4j 图结构异常：节点或边定义非法时由 compile() 抛出
import org.bsc.langgraph4j.GraphStateException;
// LangGraph4j 图定义入口：先 addNode/addEdge，再 compile()
import org.bsc.langgraph4j.StateGraph;
// LangGraph4j 检查点接口：compile 时把保存器交给 CompileConfig（实现由 GraphConfig 提供）
import org.bsc.langgraph4j.checkpoint.BaseCheckpointSaver;
// LangGraph4j 状态基类：本图的 State 类型，也是检查点序列化的目标类型
import org.bsc.langgraph4j.state.AgentState;
// 标准库：节点返回「状态增量」时用的 Map（代码当前被注释，保留供恢复时使用）
import java.util.Map;
// 标准库：CompletableFuture，节点函数要求返回异步结果（代码当前被注释，保留供恢复时使用）
import java.util.concurrent.CompletableFuture;


/**
 * LangGraph4j 基础设施配置。
 *
 * <p>检查点保存器是“中断/恢复”的前提：图执行到 interruptBefore 指定节点时，
 * 会把当前状态写入 SQLite；前端确认后，用同一个 threadId 再次调用
 * {@code GraphInput.resume(...)}，图就能从暂停处继续。</p>
 *
 * <p>数据库默认与业务表共用 app.db。SQLiteSaver 会自己创建 checkpoints 相关表，
 * 与业务 schema.sql 中的表互不冲突。</p>
 */
@Configuration
public class AgentGraphConfig {
    /** 图节点名：模型推理。 */
    private static final String NODE_AGENT = "agent";
    /** 图节点名：工具执行。 */
    private static final String NODE_TOOLS = "tools";
    /** 图节点名：需要确认时停在这里。 */
    private static final String NODE_CONFIRM = "confirm";

    /**
     * 编译好的图（当前是占位实现，节点与条件边还没写）。
     *
     * <p>TODO：把下面注释里的 StateGraph 代码补完，然后删掉 {@code return null; }。</p>
     *
     * <p>为什么这里**不**注入 {@code StreamingChatModel}：本项目不是「一个全局模型 Bean」的用法，
     * 模型是每次请求按前端选的模型设置现建的（ChatServiceImpl.java:292 调用
     * {@code llmModelFactoryRouter.createStreamingModel(spec)}，MemoryServiceImpl.java:951 同理）。
     * 如果在这里声明 StreamingChatModel 形参，Spring 启动时会因为容器里没有该类型的 Bean
     * 直接报 {@code No qualifying bean of type 'dev.langchain4j.model.chat.StreamingChatModel'}。
     * 等真正实现图的时候，模型应当作为「每次执行图时传入的参数」处理，而不是在 Bean 装配阶段注入。</p>
     *
     * @param saver        检查点存储（由 GraphConfig 提供的 SQLite 版）
     * @param toolRegistry 工具注册表：节点里按名字取工具执行
     * @return 编译后的图；当前实现固定返回 null（占位，尚无组件依赖它）
     * @throws GraphStateException 图结构非法（重名节点、悬空边等）时抛出
     */
    @Bean
    public CompiledGraph<AgentState> agentGraph(BaseCheckpointSaver saver,
                                                ToolRegistry toolRegistry) throws GraphStateException {
//        StateGraph<AgentState> graph = new StateGraph<>(AgentState::new);
//        graph.addNode(NODE_AGENT, state -> {
//            // 节点里：调模型 → 把 AiMessage 写进 state（messages 通道用追加 reducer）
//            return CompletableFuture.completedFuture(Map.of("messages", List.of(aiMessage)));
//        });
//        graph.addNode(NODE_TOOLS, state -> {
//            // 节点里：执行 state 里最后一个 AiMessage 的 toolExecutionRequests
//            return CompletableFuture.completedFuture(Map.of("messages", results));
//        });
//        graph.addNode(NODE_CONFIRM, state -> CompletableFuture.completedFuture(Map.of()));
//        // 条件边：有工具请求就走 tools，否则结束
//        graph.addConditionalEdges(NODE_AGENT, state -> {
//            AiMessage last = lastAiMessage(state);
//            return last != null && last.hasToolExecutionRequests() ? NODE_TOOLS : "end";
//        }, Map.of(NODE_TOOLS, NODE_TOOLS, "end", "end"));
//
//        graph.addEdge(NODE_TOOLS, NODE_AGENT);
//        graph.addEdge(NODE_CONFIRM, NODE_AGENT);
//
//        return graph.compile(CompileConfig.builder()
//                .checkpointSaver(saver)
//                .recursionLimit(25)
//                // 危险工具执行前停在 confirm，等前端点「同意」
//                .interruptBefore(NODE_CONFIRM)
//                .build());

        return null;
    }
}
