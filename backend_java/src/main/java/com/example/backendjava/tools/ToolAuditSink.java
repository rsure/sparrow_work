// 模块说明：工具调用审计出口（对应 Python policy.py / guard / finalize 里对 audit_service.record 的调用）。
package com.example.backendjava.tools;

// 标准库：Map 保存动态审计字段
import java.util.Map;

/**
 * 工具调用审计出口。
 *
 * <p>Java 侧现有的 AuditService 只有查询方法，因此这里定义一个最小写入接口；
 * 实现类（可选 Bean）可以把它落到 audit_log 表。没有实现时 ToolRuntime 不会审计，
 * 但不会影响工具本身的执行。</p>
 */
public interface ToolAuditSink {

    /**
     * 记录一次工具调用事件。
     *
     * @param event 审计事件
     */
    void record(ToolAuditEvent event);

    /**
     * 一条工具审计事件。
     *
     * @param sessionId 会话 id
     * @param tool      工具名
     * @param kind      操作类型（read/write/exec/net/mcp/unknown）
     * @param target    操作目标
     * @param detail    说明（裁决原因、用户选择等）
     * @param level     裁决等级 allow/ask/deny
     * @param decision  用户选择 none/approved/rejected
     * @param outcome   结果 ok/fail/skipped
     * @param output    输出摘要（可截断）
     * @param extra     其它需要留痕的动态字段
     */
    record ToolAuditEvent(
            // 会话 id
            String sessionId,
            // 工具名
            String tool,
            // 操作类型
            String kind,
            // 操作目标
            String target,
            // 说明
            String detail,
            // 裁决等级
            String level,
            // 用户选择
            String decision,
            // 结果
            String outcome,
            // 输出摘要
            String output,
            // 其它字段
            Map<String, Object> extra
    ) {

        /**
         * 构造一条最简审计事件（extra 为空）。
         *
         * @param sessionId 会话 id
         * @param tool      工具名
         * @param kind      操作类型
         * @param target    操作目标
         * @param outcome   结果
         * @param output    输出摘要
         * @return 审计事件
         */
        public static ToolAuditEvent simple(String sessionId, String tool, String kind,
                                            String target, String outcome, String output) {
            return new ToolAuditEvent(sessionId, tool, kind, target, "",
                    "none", "none", outcome, output, Map.of());
        }
    }
}
