// 模块说明：工具执行时的统一关卡（对应 Python policy.py 的 guard / finalize / make_tool）。
//
// 所有工具都通过 AbstractGuardedTool -> ToolRuntime 执行，顺序固定：
//   裁决(decide) -> 预算熔断 -> 人工确认 -> 执行 -> 输出治理 -> 审计。
// DENY 一定先于预算与确认返回，任何权限模式都改不了它。
package com.example.backendjava.tools;

// 标准库：List 接收排队中的用户插话
import java.util.List;
// 标准库：Map 保存审计附加字段
import java.util.Map;
// 标准库：Optional 表达「没有预算/没有超限」
import java.util.Optional;
// 标准库：Supplier 延迟执行工具函数（裁决通过后才真正干活）
import java.util.function.Supplier;
// 第三方（Spring）：按类型延迟获取可选 Bean（允许相关服务尚未实现）
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果（统一 OK/FAIL 前缀）
import com.example.backendjava.dto.ToolResult;
// 项目内：设置注册表——写前校验开关等配置的读取入口
import com.example.backendjava.settings.SettingsRegistry;

/**
 * 工具执行关卡：裁决、预算、确认、输出治理与审计的唯一出口。
 */
@Component
public class ToolRuntime {

    /** 工具策略注册表。 */
    private final ToolPolicyRegistry policyRegistry;

    /** 预算登记表。 */
    private final ToolBudgetRegistry budgetRegistry;

    /** 输出治理。 */
    private final OutputContract outputContract;

    /** 设置注册表。 */
    private final SettingsRegistry settingsRegistry;

    /** 人工确认网关；没有实现 Bean 时使用 fail-closed 的默认实现。 */
    private final ToolApprovalGateway approvalGateway;

    /** 审计出口；没有实现 Bean 时使用空实现。 */
    private final ToolAuditSink auditSink;

    /** 执行中插话来源；没有实现 Bean 时为 null（直接跳过）。 */
    private final ToolSteeringSource steeringSource;

    /**
     * 构造器。
     *
     * @param policyRegistry     策略注册表
     * @param budgetRegistry     预算登记表
     * @param outputContract     输出治理
     * @param settingsRegistry   设置注册表
     * @param gatewayProvider    可选的确认网关
     * @param auditSinkProvider  可选的审计出口
     * @param steeringProvider   可选的插话来源
     */
    public ToolRuntime(ToolPolicyRegistry policyRegistry,
                       ToolBudgetRegistry budgetRegistry,
                       OutputContract outputContract,
                       SettingsRegistry settingsRegistry,
                       ObjectProvider<ToolApprovalGateway> gatewayProvider,
                       ObjectProvider<ToolAuditSink> auditSinkProvider,
                       ObjectProvider<ToolSteeringSource> steeringProvider) {
        this.policyRegistry = policyRegistry;
        this.budgetRegistry = budgetRegistry;
        this.outputContract = outputContract;
        this.settingsRegistry = settingsRegistry;
        // 没有实现类时一律拒绝：宁可让写操作跑不起来，也不要「默认放行、悄悄越权」
        this.approvalGateway = gatewayProvider.getIfAvailable(() -> new ToolApprovalGateway() {
            @Override
            public ApprovalResult confirm(ApprovalRequest request) {
                return ApprovalResult.DENIED;
            }

            @Override
            public ApprovalResult budget(BudgetRequest request) {
                return ApprovalResult.DENIED;
            }
        });
        this.auditSink = auditSinkProvider.getIfAvailable(() -> event -> {
            // 没有审计实现时什么也不做：审计不应成为工具执行的前置条件
        });
        this.steeringSource = steeringProvider.getIfAvailable();
    }

    /**
     * 执行一次经过裁决的工具调用。
     *
     * @param tool 工具名
     * @param action 工具声明的本次操作
     * @param body 真正的工具函数（裁决通过后才会调用）
     * @return 治理后的工具结果
     */
    public ToolResult execute(String tool, ToolAction action, Supplier<ToolResult> body) {
        SessionContext context = ToolSession.currentContext();
        ToolDecision decision = policyRegistry.decide(tool, action, context);

        // 1) DENY：硬拦截，不弹窗、不进入预算
        if (decision.level() == ToolLevel.DENY) {
            audit(context, tool, action, decision.level().value(),
                    decision.reason(), "none", "skipped", decision.reason());
            return ToolResult.fail(decision.reason());
        }

        // 2) 预算熔断：先于确认弹窗，避免「先弹同意、再弹预算」两次打扰
        Optional<String> budgetBlock = checkBudget(tool, action, context);
        if (budgetBlock.isPresent()) {
            audit(context, tool, action, decision.level().value(),
                    "预算超限，用户选择停止", "none", "skipped", budgetBlock.get());
            return ToolResult.fail(budgetBlock.get());
        }

        // 3) ASK：按权限模式决定是否真的弹窗
        String decisionWord = "none";
        if (decision.level() == ToolLevel.ASK) {
            boolean approved = resolveAsk(tool, action, decision, context);
            decisionWord = approved ? "approved" : "rejected";
            if (!approved) {
                String reason = "用户拒绝了 " + tool + " 操作，未做任何改动";
                audit(context, tool, action, decision.level().value(),
                        decision.reason(), decisionWord, "skipped", reason);
                return ToolResult.fail(reason);
            }
        }

        // 4) 真正执行工具
        ToolResult raw;
        try {
            raw = body.get();
        } catch (RuntimeException e) {
            // 工具内部未捕获的异常：转成 FAIL，避免把 Agent 整轮打断
            raw = ToolResult.fail(tool + " 执行失败: " + e.getMessage());
        }

        // 5) 输出治理 + 审计：先治理后审计，保证模型看到与审计记录的是同一份文本
        OutputContract.TruncateResult governed = outputContract.apply(
                raw.content(), tool, context.sessionId());
        audit(context, tool, action, decision.level().value(), decision.reason(), decisionWord,
                raw.ok() ? "ok" : "fail", governed.output());
        // 6) 插话注入：放在治理与审计之后——插话是用户原话，不该被截断，也不该记成工具输出
        return new ToolResult(raw.ok(), appendSteering(governed.output(), context.sessionId()));
    }

    /**
     * 把排队中的用户插话追加到工具结果末尾（ARCH-6 的注入点）。
     *
     * @param result    已经过治理的工具结果
     * @param sessionId 会话 id
     * @return 可能被追加了插话块的文本
     */
    private String appendSteering(String result, String sessionId) {
        if (steeringSource == null || sessionId == null || sessionId.isEmpty()) {
            return result;
        }
        List<String> items;
        try {
            items = steeringSource.drain(sessionId);
        } catch (RuntimeException e) {
            // 插话队列读失败不能改变工具结果
            return result;
        }
        if (items == null || items.isEmpty()) {
            return result;
        }
        String block = items.stream()
                .map(item -> ToolSteeringSource.INJECT_PREFIX + " " + item)
                .reduce((left, right) -> left + "\n" + right)
                .orElse("");
        return result + "\n\n" + block + "\n" + ToolSteeringSource.INJECT_HINT;
    }

    /**
     * 写前校验（task.write_stale_guard）是否开启；读不到按开启处理。
     *
     * @return true 表示开启
     */
    public boolean writeStaleGuardEnabled() {
        try {
            Object value = settingsRegistry.getSetting("task.write_stale_guard");
            return value == null || Boolean.TRUE.equals(value);
        } catch (RuntimeException e) {
            // 读不到配置时选择「保护开启」：多拦一次比静默覆盖安全
            return true;
        }
    }

    /**
     * 返回策略注册表（工具基类据此推导 AgentTool.policy()）。
     *
     * @return 策略注册表
     */
    public ToolPolicyRegistry policyRegistry() {
        return policyRegistry;
    }

    /**
     * 检查本轮预算；超限时询问用户「继续 / 停止」。
     *
     * @param tool    工具名
     * @param action  本次操作
     * @param context 会话上下文
     * @return 非空表示必须拒绝，内容为给模型的说明
     */
    private Optional<String> checkBudget(String tool, ToolAction action, SessionContext context) {
        Optional<ToolBudgetRegistry.TurnBudget> maybeBudget =
                budgetRegistry.getBudget(context.sessionId());
        if (maybeBudget.isEmpty()) {
            return Optional.empty();
        }
        ToolBudgetRegistry.TurnBudget budget = maybeBudget.get();
        if (budget.isBlocked()) {
            // 用户已经在本轮里选过「停止」：不再弹窗，直接拒绝，让模型去总结
            return Optional.of("用户已经选择停止本轮，工具 " + tool + " 未执行。"
                    + "请总结已完成的部分，并说明还差什么。");
        }
        Optional<ToolBudgetRegistry.BudgetHit> hit = budget.exceeded();
        if (hit.isEmpty()) {
            return Optional.empty();
        }
        ToolBudgetRegistry.BudgetHit value = hit.get();
        ToolApprovalGateway.ApprovalResult result = approvalGateway.budget(
                new ToolApprovalGateway.BudgetRequest(
                        tool, value.dimension(), value.current(), value.limit()));
        if (result.approved()) {
            // 用户选「继续」：本轮不再就这个维度提醒（防骚扰）
            budget.release(value.dimension());
            return Optional.empty();
        }
        // 用户选「停止」：标记整轮阻塞，后续工具调用不再询问也不再执行
        budget.block();
        return Optional.of("用户因为预算超出（" + value.dimension() + ": " + value.current()
                + " > " + value.limit() + "）选择停止本轮，工具 " + tool + " 未执行。"
                + "请总结已经完成的部分，并说明还差什么。");
    }

    /**
     * 按权限模式决定「原本要 ASK 的操作」是否放行。
     *
     * <p>安全不变量：本方法只在 decide() 已给出 ASK 时调用。DENY 在更上游返回，
     * 任何模式都不可能把 DENY 变成放行。</p>
     *
     * @param tool     工具名
     * @param action   本次操作
     * @param decision 裁决结果（标题与正文用于弹窗）
     * @param context  会话上下文
     * @return true 表示允许执行
     */
    private boolean resolveAsk(String tool, ToolAction action, ToolDecision decision,
                               SessionContext context) {
        String mode = context.permissionMode() == null
                ? "ask"
                : context.permissionMode().strip().toLowerCase(java.util.Locale.ROOT);

        // 子 agent 红线：写盘/执行操作无论什么模式都必须逐次确认。
        // 这一段必须放在 allow 绕过之前，否则 allow 模式会把它们整体跳过。
        boolean forcedBySubAgent = ToolSession.SCOPE_SUB.equals(context.scope())
                && (action.kind() == ToolKind.WRITE || action.kind() == ToolKind.EXEC);

        // 完全授权：跳过弹窗（DENY 已在更上游被拦下）
        if (!forcedBySubAgent && "allow".equals(mode)) {
            return true;
        }

        boolean allowRemember = "workspace".equals(mode)
                && context.workspaceId() != null && !context.workspaceId().isBlank();
        String message = forcedBySubAgent
                ? "（子 agent 操作，需逐次确认）" + decision.reason()
                : decision.reason();
        ToolApprovalGateway.ApprovalResult result = approvalGateway.confirm(
                new ToolApprovalGateway.ApprovalRequest(
                        tool, decision.title(), message, action.preview(), allowRemember));
        // 说明：Java 侧暂时没有 approval 表的写入服务；remember 目前只回给审计，
        // 等 workspace 授权服务落地后再在这里落库（对应 Python 的 approval_service.upsert）。
        return result.approved();
    }

    /**
     * 写一条审计事件；审计实现本身抛异常时只记录日志，不影响工具结果。
     *
     * @param context  会话上下文
     * @param tool     工具名
     * @param action   本次操作
     * @param level    裁决等级
     * @param detail   说明
     * @param decision 用户选择
     * @param outcome  结果
     * @param output   输出摘要
     */
    private void audit(SessionContext context, String tool, ToolAction action, String level,
                       String detail, String decision, String outcome, String output) {
        try {
            auditSink.record(new ToolAuditSink.ToolAuditEvent(
                    context.sessionId(),
                    tool,
                    action == null || action.kind() == null ? "unknown" : action.kind().value(),
                    action == null ? "" : action.target(),
                    detail == null ? "" : detail,
                    level == null ? "none" : level,
                    decision,
                    outcome,
                    output == null ? "" : output,
                    Map.of()
            ));
        } catch (RuntimeException e) {
            // 审计写失败不能反过来改变工具结果
            org.slf4j.LoggerFactory.getLogger(ToolRuntime.class)
                    .warn("写工具审计失败：{}", e.getMessage());
        }
    }
}
