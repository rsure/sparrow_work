// 模块说明：把「工具要确认」翻译成「前端弹窗」的那座桥。
//
// 时序：用户提问 → 模型要求调工具 → ToolRuntime 判定 ASK → 调到这里
//      → 发 confirm_required → 关流 → 线程挂起 → 用户点同意 → /chat/resume
//      → 兑现 Future → 线程醒来继续执行工具。
package com.example.backendjava.chat.runtime;

// 已有：会话上下文（从中取 sessionId）与确认接口
import com.example.backendjava.tools.SessionContext;
import com.example.backendjava.tools.ToolApprovalGateway;
import com.example.backendjava.tools.ToolSession;

// Spring：注册成 Bean，ToolRuntime 会通过 ObjectProvider 取到它
import org.springframework.stereotype.Component;

/**
 * 基于 SSE 的确认网关：需要用户确认时，向前端发事件并挂起等待。
 *
 * <p>注意：工具线程是同步线程，{@link ToolSession} 是 ThreadLocal，
 * 所以这里能安全地取到当前会话 id（Agent 运行时在进入工具前 setContext）。</p>
 */
@Component
public class ChatApprovalGateway implements ToolApprovalGateway {

    /** 会话总线：负责发事件与挂起/唤醒。 */
    private final ChatSessionBus bus;

    /**
     * 构造网关。
     *
     * @param bus 会话总线
     */
    public ChatApprovalGateway(ChatSessionBus bus) {
        this.bus = bus;
    }

    /**
     * 请求用户确认一次工具调用。
     *
     * @param request 确认请求（工具名、说明、入参、是否可记住）
     * @return 用户决定；超时为拒绝
     */
    @Override
    public ApprovalResult confirm(ApprovalRequest request) {
        SessionContext context = ToolSession.currentContext();
        String sessionId = context.sessionId();
        // 没有会话 id 说明是启动自检之类的调用，不能弹窗，直接拒绝（最安全的默认值）
        if (sessionId == null || sessionId.isBlank()) {
            return ApprovalResult.DENIED;
        }
        return bus.askAndWait(sessionId, request);
    }

    /**
     * 请求用户批准超预算继续。
     *
     * @param request 预算请求（维度、当前值、上限）
     * @return 用户决定；超时为拒绝
     */
    @Override
    public ApprovalResult budget(BudgetRequest request) {
        SessionContext context = ToolSession.currentContext();
        String sessionId = context.sessionId();
        if (sessionId == null || sessionId.isBlank()) {
            return ApprovalResult.DENIED;
        }
        return bus.askBudgetAndWait(sessionId, request);
    }
}
