// 模块说明：一个工具的静态安全策略（对应 Python policy.py 的 Policy）。
package com.example.backendjava.tools;

// 标准库：Set 保存「哪些参数是路径」
import java.util.Set;

/**
 * 一个工具的静态安全策略（注册时声明，运行期不变）。
 *
 * @param tool          工具名，必须与 AgentTool.name() 完全一致
 * @param kind          操作类型，决定默认裁决等级
 * @param pathArgs      参数中属于「路径」的键名；这些参数的值会被解析成绝对路径并逐个校验
 * @param pathOp        路径按哪种操作校验（默认与 kind 一致；只读源路径可单独指定）
 * @param requireConfirm 强制要求用户确认（覆盖 kind 的默认等级）
 * @param defaultLevel  显式指定裁决等级（优先级最高）；null 表示不指定
 * @param confirmNote   免确认/需确认条件说明（给读代码的人看）
 * @param offByDefault  是否默认关闭（联网工具），开启需要用户显式打开
 */
public record ToolPolicySpec(
        // 工具名
        String tool,
        // 操作类型
        ToolKind kind,
        // 路径参数名
        Set<String> pathArgs,
        // 路径校验使用的操作类型
        String pathOp,
        // 是否强制确认
        boolean requireConfirm,
        // 显式裁决等级
        ToolLevel defaultLevel,
        // 确认说明
        String confirmNote,
        // 是否默认关闭
        boolean offByDefault
) {

    /**
     * 构造一条只读工具策略的便捷方法。
     *
     * @param tool 工具名
     * @return 只读策略（默认 ALLOW）
     */
    public static ToolPolicySpec readOnly(String tool) {
        return new ToolPolicySpec(tool, ToolKind.READ, Set.of(), PathPolicy.OP_READ,
                false, null, "", false);
    }
}
