// 模块说明：Agent 运行时与上层 ChatService 之间的内部 DTO（不直接暴露给前端）。
package com.example.backendjava.dto;

// 标准库：Map 用于事件负载
import java.util.Map;

/**
 * Agent 域内部 DTO。
 */
public final class AgentDtos {

    /** 工具类禁止实例化。 */
    private AgentDtos() {
    }

    /**
     * 一次 Agent 执行请求。
     *
     * @param sessionId     会话 id，同时作为 LangGraph4j 的 threadId
     * @param message       用户输入
     * @param mode          agent / doc
     * @param maxIterations 图递归步数上限
     * @param debug         是否输出调试事件
     */
    public record AgentTurnRequest(
            // 会话 id
            String sessionId,
            // 用户输入
            String message,
            // 模式
            String mode,
            // 递归步数上限
            int maxIterations,
            // 调试开关
            boolean debug
    ) {
    }

    /**
     * 恢复被中断的 Agent 执行。
     *
     * @param sessionId     会话 id
     * @param interruptId   中断 id
     * @param approved      是否同意
     * @param remember      是否记住授权
     * @param maxIterations 递归步数上限
     */
    public record AgentResumeRequest(
            // 会话 id
            String sessionId,
            // 中断 id
            String interruptId,
            // 是否同意
            boolean approved,
            // 是否记住授权
            boolean remember,
            // 递归步数上限
            int maxIterations
    ) {
    }

    /**
     * Agent 产生的一个事件。
     *
     * @param type 事件名：thinking / token / tool_start / tool_end / confirm_required / done / error / stopped
     * @param data 事件负载
     */
    public record AgentEvent(
            // 事件名
            String type,
            // 事件负载
            Map<String, Object> data
    ) {
    }
}
