// 模块说明：LangGraph4j 图运行时的基础 Bean。先把“检查点保存器”装配好，业务图由学习者实现。
package com.example.backendjava.config;

// Spring 配置注解：声明本类提供 Bean
import com.example.backendjava.service.ToolRegistry;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.model.chat.StreamingChatModel;
import org.bsc.langgraph4j.CompileConfig;
import org.bsc.langgraph4j.CompiledGraph;
import org.bsc.langgraph4j.GraphStateException;
import org.bsc.langgraph4j.StateGraph;
import org.springframework.context.annotation.Configuration;
// Spring Bean 注解：把方法返回值注册到容器
import org.springframework.context.annotation.Bean;
// LangGraph4j 检查点接口：CompiledGraph 编译时接收它的实现
import org.bsc.langgraph4j.checkpoint.BaseCheckpointSaver;
// LangGraph4j 官方 SQLite 保存器：按 threadId 把图状态落盘，对应 Python 的 AsyncSqliteSaver
import org.bsc.langgraph4j.checkpoint.SQLiteSaver;
// LangGraph4j 的状态基类：检查点序列化需要一个 AgentState 工厂
import org.bsc.langgraph4j.state.AgentState;
// LangGraph4j 与 LangChain4j 的桥接序列化器：能正确序列化 ChatMessage / ToolExecutionRequest
import org.bsc.langgraph4j.langchain4j.serializer.jackson.LC4jJacksonStateSerializer;

import java.util.Map;
import java.util.concurrent.CompletableFuture;
// 项目内配置：读取检查点数据库路径


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
     * 编译好的图。
     * TODO
     * @param saver       检查点存储（GraphConfig 已经提供 SQLite 版）
     * @param model       流式模型
     * @param toolExecutor 工具执行（第 3 章的 ChatToolExecutor 可以直接用）
     * @return 编译后的图
     */
    @Bean
    public CompiledGraph<AgentState> agentGraph(BaseCheckpointSaver saver,
                                                StreamingChatModel model,
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
