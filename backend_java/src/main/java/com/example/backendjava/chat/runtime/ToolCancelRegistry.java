// 模块说明：会话级「取消工具」登记处 —— /chat/{id}/tool-cancel 写，工具执行器读。
//
// 为什么不用「删掉工具」来实现取消：工具表是一轮开始时一次性装好的，
// AiServices 跑起来之后改不了；改成「执行前查一下有没有被取消」最省事。
package com.example.backendjava.chat.runtime;

// 标准库：并发容器（多个会话同时跑，必须线程安全）
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

// Spring：单例，两个地方（Controller 层与工具执行器）共用
import org.springframework.stereotype.Component;

/**
 * 取消登记处：每个会话一组「被取消的工具名」，空串表示「下一个工具」。
 */
@Component
public class ToolCancelRegistry {

    /** 会话 id → 被取消的工具名集合；空串代表任意下一个工具。 */
    private final Map<String, Set<String>> cancelled = new ConcurrentHashMap<>();

    /**
     * 登记一次取消。
     *
     * @param sessionId 会话 id
     * @param tool      工具名；空串表示「下一个工具」
     */
    public void register(String sessionId, String tool) {
        String key = (tool == null || tool.isBlank()) ? "" : tool;
        cancelled.computeIfAbsent(sessionId, id -> ConcurrentHashMap.newKeySet()).add(key);
    }

    /**
     * 试探并消费一次取消（消费掉就没了，避免误伤后面的工具）。
     *
     * @param sessionId 会话 id
     * @param toolName  即将执行的工具名
     * @return true 表示这次调用应该被跳过
     */
    public boolean consume(String sessionId, String toolName) {
        Set<String> set = cancelled.get(sessionId);
        if (set == null) {
            return false;
        }
        // 命中：精确点名，或登记了「下一个」
        boolean hit = set.remove(toolName) || set.remove("");
        if (set.isEmpty()) {
            cancelled.remove(sessionId);
        }
        return hit;
    }

    /**
     * 一轮结束时清空，避免下次同会话误命中。
     *
     * @param sessionId 会话 id
     */
    public void clear(String sessionId) {
        cancelled.remove(sessionId);
    }
}