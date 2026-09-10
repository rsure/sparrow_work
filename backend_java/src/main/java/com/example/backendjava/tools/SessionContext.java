// 模块说明：会话级权限上下文（对应 Python policy.py 的 SessionContext）。
package com.example.backendjava.tools;

// 标准库：List 保存工作区根目录
import java.util.List;
// 标准库：Path 表示工作区根目录
import java.nio.file.Path;
// 标准库：Set 保存禁用工具与会话级命令白名单
import java.util.Set;

/**
 * 会话级上下文：把「这次是谁、在什么范围内操作」传给裁决逻辑。
 *
 * @param sessionId       会话 id，用于审计、预算与「记住本次选择」
 * @param workspaceRoots  本会话允许写入/执行的目录白名单；空列表表示用全局白名单
 * @param denyTools       本会话显式禁用的工具名（用户在界面上关掉的能力）
 * @param allowedCommands 本会话显式允许的执行命令前缀（如 "git status"）
 * @param workspaceId     当前工作区 id；空串表示还没有工作区
 * @param permissionMode  权限模式：ask=每次询问 / workspace=本工作区批准后免询问 / allow=完全授权
 * @param scope           Agent 作用域：main=主对话 / sub=子 agent
 */
public record SessionContext(
        // 会话 id
        String sessionId,
        // 工作区根目录白名单
        List<Path> workspaceRoots,
        // 本会话禁用的工具名
        Set<String> denyTools,
        // 会话级命令白名单
        Set<String> allowedCommands,
        // 当前工作区 id
        String workspaceId,
        // 权限模式
        String permissionMode,
        // Agent 作用域
        String scope
) {

    /**
     * 构造一个「什么都没配置」的默认上下文：最严格，所有有副作用的操作都会询问。
     *
     * @return 默认上下文
     */
    public static SessionContext empty() {
        return new SessionContext("", List.of(), Set.of(), Set.of(), "", "ask", ToolSession.SCOPE_MAIN);
    }
}
