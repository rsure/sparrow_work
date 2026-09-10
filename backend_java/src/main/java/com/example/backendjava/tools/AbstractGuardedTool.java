// 模块说明：工具基类。把「构造操作 -> 统一裁决 -> 执行 -> 输出治理」的骨架固定下来。
//
// 子类只需要做两件事：
//   1. buildAction：把 Map 入参翻译成 ToolAction（只做只读解析与校验，不要产生副作用）；
//   2. run：真正干活（此时已经过 DENY / 预算 / 用户确认三道关卡）。
package com.example.backendjava.tools;

// 标准库：Map 工具入参
import java.util.Map;
// 项目内：工具安全策略枚举（对接 AgentTool 接口）
import com.example.backendjava.common.ToolPolicy;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：Agent 工具接口
import com.example.backendjava.service.AgentTool;

/**
 * 带统一安全关卡的 Agent 工具基类。
 */
public abstract class AbstractGuardedTool implements AgentTool {

    /** 执行关卡：所有工具共用同一套裁决/预算/确认/治理逻辑。 */
    private final ToolRuntime runtime;

    /**
     * 构造器。
     *
     * @param runtime 执行关卡
     */
    protected AbstractGuardedTool(ToolRuntime runtime) {
        this.runtime = runtime;
    }

    /**
     * 返回执行关卡，供子类读取写前校验开关等配置。
     *
     * @return 工具执行关卡
     */
    protected ToolRuntime runtime() {
        return runtime;
    }

    /**
     * 把工具入参翻译成一次待裁决的操作。
     *
     * <p>本方法必须保持只读：它可以抛异常（参数不合法），但绝不能已经产生副作用。</p>
     *
     * @param arguments 工具入参
     * @return 待裁决操作
     */
    protected abstract ToolAction buildAction(Map<String, Object> arguments);

    /**
     * 真正执行工具。
     *
     * <p>调用本方法时，策略裁决、预算检查与用户确认都已经通过。</p>
     *
     * @param arguments 工具入参
     * @param action    已裁决的操作
     * @return 工具结果
     */
    protected abstract ToolResult run(Map<String, Object> arguments, ToolAction action);

    /**
     * 执行工具：先构造操作，再交给 ToolRuntime 完成裁决与收尾。
     *
     * @param arguments 工具入参
     * @return 工具结果
     */
    @Override
    public final ToolResult execute(Map<String, Object> arguments) {
        final ToolAction action;
        try {
            action = buildAction(arguments == null ? Map.of() : arguments);
        } catch (RuntimeException e) {
            // 参数级失败：不进入执行关卡，直接给模型可读的提示
            return ToolResult.fail(name() + " 参数不合法: " + e.getMessage());
        }
        return runtime.execute(name(), action, () -> run(arguments == null ? Map.of() : arguments, action));
    }

    /**
     * 从策略注册表推导对外的工具策略枚举。
     *
     * @return 只读 / 写盘 / 执行 / 联网
     */
    @Override
    public ToolPolicy policy() {
        ToolKind kind = runtime.policyRegistry().find(name())
                .map(ToolPolicySpec::kind)
                .orElse(ToolKind.READ);
        return switch (kind) {
            case READ -> ToolPolicy.READ_ONLY;
            case WRITE -> ToolPolicy.WRITE;
            case EXEC -> ToolPolicy.EXECUTE;
            // MCP 与联网一样属于「外部能力」，统一按联网策略展示
            case NET, MCP -> ToolPolicy.NETWORK;
        };
    }
}
