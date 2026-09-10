// 模块说明：人工确认网关（对应 Python tool_utils.py 的 ask_user / ask_user_decide / ask_budget）。
//
// Python 用 LangGraph 的 interrupt() 暂停整张图；Java 侧把它抽象成接口：
// 工具层只负责提出「需要确认」，具体是弹 SSE、写检查点还是直接放行，由 Agent 运行时实现。
// 没有实现 Bean 时，ToolRuntime 采用「fail-closed」策略：一律拒绝，绝不默认放行。
package com.example.backendjava.tools;

// 标准库：Map 用于展示给确认弹窗的关键参数
import java.util.Map;

/**
 * 工具确认网关。
 *
 * <p>实现类通常由 Agent 运行时提供：把请求转成 SSE 事件并等待前端回复，
 * 对应 Python 的 interrupt() / resume 链路。</p>
 */
public interface ToolApprovalGateway {

    /**
     * 请求用户确认一次有风险的操作。
     *
     * @param request 确认请求
     * @return 用户决定；不能用 null 表示同意
     */
    ApprovalResult confirm(ApprovalRequest request);

    /**
     * 预算超限时询问「继续 / 停止」。
     *
     * @param request 预算请求
     * @return 用户决定；approved=true 表示继续，false 表示停止本轮
     */
    ApprovalResult budget(BudgetRequest request);

    /**
     * 一次人工确认请求。
     *
     * @param tool          触发确认的工具名
     * @param title         弹窗标题
     * @param message       弹窗正文（影响范围说明）
     * @param args          展示给用户的关键参数（长文本应先截断）
     * @param allowRemember 是否提供「记住本工作区授权」勾选
     */
    record ApprovalRequest(
            // 工具名
            String tool,
            // 弹窗标题
            String title,
            // 弹窗正文
            String message,
            // 关键参数
            Map<String, Object> args,
            // 是否允许记住本工作区
            boolean allowRemember
    ) {
    }

    /**
     * 用户对一次确认请求的决定。
     *
     * @param approved 是否同意
     * @param remember 是否记住本工作区授权（仅在 allowRemember=true 时可能为 true）
     */
    record ApprovalResult(
            // 是否同意
            boolean approved,
            // 是否记住授权
            boolean remember
    ) {

        /** 拒绝且不记住的固定结果。 */
        public static final ApprovalResult DENIED = new ApprovalResult(false, false);

        /**
         * 构造「同意」结果。
         *
         * @param remember 是否记住
         * @return 同意结果
         */
        public static ApprovalResult approved(boolean remember) {
            return new ApprovalResult(true, remember);
        }
    }

    /**
     * 一次预算超限询问。
     *
     * @param tool      被拦截的工具名
     * @param dimension 超限维度：tokens / cost / duration
     * @param current   当前累计值（单位随维度）
     * @param limit     阈值（单位随维度）
     */
    record BudgetRequest(
            // 工具名
            String tool,
            // 超限维度
            String dimension,
            // 当前值
            double current,
            // 阈值
            double limit
    ) {
    }
}
