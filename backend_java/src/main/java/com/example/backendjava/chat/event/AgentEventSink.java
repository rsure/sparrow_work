// 模块说明：Agent 事件出口。AgentRuntime 只负责产生事件，由 ChatService 决定写 SSE 还是落轨迹表。
package com.example.backendjava.chat.event;

// Agent 运行时的执行请求与事件 DTO
import com.example.backendjava.dto.AgentDtos;

/**
 * Agent 事件接收器。
 *
 * <p>这样设计的好处：Agent 运行时不需要知道 HTTP/SSE；测试时可以换成收集到 List 的假实现。</p>
 */
@FunctionalInterface
public interface AgentEventSink {

    /**
     * 接收一个 Agent 事件。
     *
     * @param event 事件类型与负载
     */
    void emit(AgentDtos.AgentEvent event);
}
