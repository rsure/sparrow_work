// 模块说明：会话上下文传递（对应 Python app/tools/session.py）。
//
// Python 用 ContextVar 把 session_id / scope 隐式传给工具；Java 侧工具运行在同步线程里，
// 用 ThreadLocal 实现同样的效果：调用方在进入工具循环前 set，工具内部 get。
// 注意：线程池复用时必须清理，否则上一个会话的值会串到下一个请求（见 clear()）。
package com.example.backendjava.tools;

/**
 * 工具层会话上下文。
 */
public final class ToolSession {

    /** 主对话 Agent 的作用域：全量工具、走完整权限模式。 */
    public static final String SCOPE_MAIN = "main";

    /** 子 Agent 的作用域：只读工具集，写盘/执行强制逐次询问。 */
    public static final String SCOPE_SUB = "sub";

    /** 当前线程绑定的会话 id；未设置时为空串（表示不在某次对话里）。 */
    private static final ThreadLocal<String> CURRENT_SESSION_ID = ThreadLocal.withInitial(() -> "");

    /** 当前线程绑定的 Agent 作用域；默认主对话。 */
    private static final ThreadLocal<String> CURRENT_SCOPE = ThreadLocal.withInitial(() -> SCOPE_MAIN);

    /** 当前线程绑定的完整权限上下文；未设置时返回默认上下文。 */
    private static final ThreadLocal<SessionContext> CURRENT_CONTEXT = new ThreadLocal<>();

    /** 工具类禁止实例化。 */
    private ToolSession() {
    }

    /**
     * 设置当前线程的会话 id。
     *
     * @param sessionId 会话 id
     */
    public static void setSessionId(String sessionId) {
        CURRENT_SESSION_ID.set(sessionId == null ? "" : sessionId);
    }

    /**
     * 读取当前线程的会话 id。
     *
     * @return 会话 id；未设置时为空串
     */
    public static String currentSessionId() {
        return CURRENT_SESSION_ID.get();
    }

    /**
     * 设置当前线程的 Agent 作用域。
     *
     * @param scope main 或 sub
     */
    public static void setAgentScope(String scope) {
        CURRENT_SCOPE.set(SCOPE_SUB.equals(scope) ? SCOPE_SUB : SCOPE_MAIN);
    }

    /**
     * 读取当前线程的 Agent 作用域。
     *
     * @return main 或 sub
     */
    public static String currentScope() {
        return CURRENT_SCOPE.get();
    }

    /**
     * 设置当前线程的完整权限上下文（由 Agent 运行时在每轮开始时装配）。
     *
     * @param context 会话上下文
     */
    public static void setContext(SessionContext context) {
        CURRENT_CONTEXT.set(context);
    }

    /**
     * 读取当前线程的权限上下文；没有显式设置时按线程本地的 session/scope 组装一个默认值。
     *
     * <p>默认值的 permissionMode 固定为 ask（最严）：读不到配置绝不能变成「默认放行」。</p>
     *
     * @return 会话上下文；不会为 null
     */
    public static SessionContext currentContext() {
        SessionContext context = CURRENT_CONTEXT.get();
        if (context != null) {
            return context;
        }
        return new SessionContext(
                currentSessionId(),
                PathPolicy.workspaceRoots(),
                java.util.Set.of(),
                java.util.Set.of(),
                "",
                "ask",
                currentScope()
        );
    }

    /**
     * 清空当前线程的全部上下文（线程池归还线程前必须调用，避免串会话）。
     */
    public static void clear() {
        CURRENT_SESSION_ID.remove();
        CURRENT_SCOPE.remove();
        CURRENT_CONTEXT.remove();
    }
}
