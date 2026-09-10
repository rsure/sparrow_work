// 模块说明：一次待执行的具体操作（对应 Python policy.py 的 Action）。
package com.example.backendjava.tools;

// 标准库：List 保存需要校验的路径
import java.util.List;
// 标准库：Map 保存展示给确认弹窗的关键参数
import java.util.Map;
// 标准库：Path 表示待校验路径
import java.nio.file.Path;

/**
 * 一次待执行的具体操作（由工具在产生副作用之前构造）。
 *
 * <p>工具只负责把参数翻译成这个对象，不再自己判断「该不该问、该不该拒」——
 * 那些判断统一交给 {@link ToolPolicyRegistry#decide(String, ToolAction, SessionContext)}。</p>
 *
 * @param tool    工具名
 * @param kind    操作类型
 * @param target  本次操作的目标（人类可读描述，如文件路径或命令字符串）
 * @param paths   需要校验的路径列表（工具自己从参数里挑出来）
 * @param preview 展示给确认弹窗的关键参数（值应已截断）
 * @param detail  附加说明：写进裁决原因的「这次到底要做什么」
 */
public record ToolAction(
        // 工具名
        String tool,
        // 操作类型
        ToolKind kind,
        // 操作目标
        String target,
        // 待校验路径
        List<Path> paths,
        // 确认弹窗参数
        Map<String, Object> preview,
        // 附加说明
        String detail
) {
}
