// 模块说明：Agent 运行时接口。实现类负责 LangGraph4j 建图、检查点、工具循环与中断恢复。
package com.example.backendjava.service;

// Agent 运行时的执行请求与事件 DTO
import com.example.backendjava.chat.event.AgentEventSink;
import com.example.backendjava.dto.AgentDtos;

/**
 * Agent 运行时接口。
 *
 * <p>实现建议：</p>
 * <ol>
 *   <li>用 {@code StateGraph<MessagesState<ChatMessage>>}（或 {@code MessagesStateGraph}）建图；</li>
 *   <li>用 {@code CompileConfig.builder().checkpointSaver(saver).interruptBefore("confirm")...} 编译；</li>
 *   <li>用 {@code RunnableConfig.builder().threadId(sessionId).build()} 绑定会话；</li>
 *   <li>用 {@code StreamingChatModel} 把 token 通过 {@link AgentEventSink} 发出去；</li>
 *   <li>暂停后用 {@code GraphInput.resume(...)} 从检查点继续。</li>
 * </ol>
 */
public interface AgentRuntime {

    /**
     * 执行一轮 Agent 对话。
     *
     * @param request 执行请求
     * @param sink    事件接收器
     */
    void run(AgentDtos.AgentTurnRequest request, AgentEventSink sink);

    /**
     * 从暂停点恢复执行。
     *
     * @param request 恢复请求
     * @param sink    事件接收器
     */
    void resume(AgentDtos.AgentResumeRequest request, AgentEventSink sink);

    /**
     * 请求终止某个会话当前正在执行的图。
     *
     * @param sessionId 会话 id
     */
    void cancel(String sessionId);
}
