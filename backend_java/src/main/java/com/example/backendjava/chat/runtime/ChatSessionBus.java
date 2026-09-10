// 模块说明：会话级事件总线 —— 「一次对话」和「一条 HTTP 流」之间的可换绑插座。
//
// 为什么必须有它：前端契约要求 confirm_required 之后当前 SSE 流立刻结束，
// 用户点完同意再用 /chat/resume 打开一条「新流」继续看后续输出（见 frontend/src/stores/chat.ts:1133-1164）。
// 也就是说：执行线程（跑模型、跑工具的那个）不能和某一条具体的 SseEmitter 绑死。
// 本类用 sessionId → Turn 的映射，让执行线程只管「往总线写」，总线决定「现在写给谁」。
//
// 代价（写在这里免得上线踩）：
//   1) 一个待确认的轮次会占住一个线程（阻塞在 future.get 上）；
//   2) 进程重启后待确认的轮次会丢（没有落盘，Python 用 LangGraph checkpoint 解决，见第 7 章）。
package com.example.backendjava.chat.runtime;

// 标准库：并发容器与原子类型
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
// 标准库：UUID 生成中断 id
import java.util.UUID;

// 已有的事件信封、工厂与 SSE 出口
import com.example.backendjava.chat.event.ChatEvents;
import com.example.backendjava.chat.event.CompositeAgentEventSink;
import com.example.backendjava.chat.event.SseAgentEventSink;
import com.example.backendjava.dto.AgentDtos;
// 确认结果类型：直接复用工具层的 record，避免两套
import com.example.backendjava.tools.ToolApprovalGateway.ApprovalRequest;
import com.example.backendjava.tools.ToolApprovalGateway.ApprovalResult;
// 预算请求类型
import com.example.backendjava.tools.ToolApprovalGateway.BudgetRequest;

// 日志门面：后台出口失败时记一笔，不影响主流程
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// Spring：单例
import org.springframework.stereotype.Component;

/**
 * 会话级事件总线。
 *
 * <p>三个职责：</p>
 * <ol>
 *   <li>记住每个会话「当前该往哪条 SSE 流写」；</li>
 *   <li>在需要确认时把流摘下来（detach）并挂起一个 Future；</li>
 *   <li>在 /chat/resume 时换上新流并兑现 Future，让挂起的工具线程继续跑。</li>
 * </ol>
 */
@Component
public class ChatSessionBus {

    /** 等待用户点确认的最长时间；超时按「拒绝」处理，避免线程永远挂着。 */
    private static final long ASK_TIMEOUT_MINUTES = 10;

    /** 日志：后台出口失败、换流失败等非致命问题记这里。 */
    private static final Logger log = LoggerFactory.getLogger(ChatSessionBus.class);

    /** 会话 id → 本轮运行状态。 */
    private final Map<String, Turn> turns = new ConcurrentHashMap<>();

    /** 会话 id → 本轮记事本；与 turns 同生命周期。 */
    private final Map<String, TurnRecorder> recorders = new ConcurrentHashMap<>();

    /** 事件工厂：总线自己也发事件（confirm_required / budget_exceeded）。 */
    private final ChatEvents events;

    /** 与流无关的出口链（落库/审计/日志）；见 3.9.3 里那个 backgroundEventSink Bean。 */
    private final CompositeAgentEventSink background;

    /**
     * 构造总线。
     *
     * <p>参数类型写具体的 CompositeAgentEventSink 而不是 AgentEventSink：
     * 因为容器里还有一个 TraceEventSink 也是 AgentEventSink，写接口会报「找到两个 Bean」。</p>
     *
     * @param events     事件工厂
     * @param background 与流无关的出口链（落库等），不能为 null
     */
    public ChatSessionBus(ChatEvents events, CompositeAgentEventSink background) {
        this.events = events;
        this.background = background;
    }

    /**
     * 一轮对话的运行时状态。
     *
     * <p>用普通内部类而不是 record：字段需要就地修改（换 sink、改停止标记）。</p>
     */
    public static final class Turn {

        /** 会话 id。 */
        private final String sessionId;

        /** 当前绑定的 SSE 出口；为 null 表示「现在没有流在看」，事件直接丢弃。 */
        private volatile SseAgentEventSink sink;

        /** 是否已请求停止（前端点了「停止」）。 */
        private volatile boolean stopRequested;

        /** 当前唯一一个待确认的询问；没有则为 null。 */
        private volatile PendingAsk pending;

        /** 本次询问的中断 id，与 confirm_required 事件里的 interrupt_id 一致。 */
        private volatile String interruptId;

        /**
         * 构造一轮状态。
         *
         * @param sessionId 会话 id
         */
        Turn(String sessionId) {
            this.sessionId = sessionId;
        }

        /**
         * 读取会话 id。
         *
         * @return 会话 id
         */
        public String sessionId() {
            return sessionId;
        }

        /**
         * 查询是否已被请求停止。
         *
         * @return true 表示前端点了停止
         */
        public boolean stopRequested() {
            return stopRequested;
        }
    }

    /**
     * 一个待确认的询问。
     *
     * @param interruptId 中断 id
     * @param future      等待用户决定的结果
     * @param event       当时发出的 confirm_required 事件；换流后要补发，否则新流看不到弹窗
     */
    private record PendingAsk(String interruptId,
                              java.util.concurrent.CompletableFuture<ApprovalResult> future,
                              AgentDtos.AgentEvent event) {
    }

    /**
     * 开启（或复用）一轮对话。
     *
     * @param sessionId 会话 id
     * @return 本轮状态
     */
    public Turn open(String sessionId) {
        return turns.computeIfAbsent(sessionId, Turn::new);
    }

    /**
     * 取（或创建）本轮的记事本。
     *
     * @param sessionId 会话 id
     * @return 本轮记录器
     */
    public TurnRecorder recorderOf(String sessionId) {
        open(sessionId);
        return recorders.computeIfAbsent(sessionId, key -> new TurnRecorder());
    }

    /**
     * 静默摘流：用于 emitter 的 onCompletion / onTimeout / onError 回调。
     *
     * <p>与 {@link #detach(String)} 的区别：这里不调用 emitter.complete()
     * （因为是容器/前端先关的，再 complete 一次会抛异常），只把绑定清掉。</p>
     *
     * @param sessionId 会话 id
     */
    public void detachQuietly(String sessionId) {
        Turn turn = turns.get(sessionId);
        if (turn != null) {
            turn.sink = null;
        }
    }

    /**
     * 把一条新的 SSE 流插到会话上。
     *
     * @param sessionId 会话 id
     * @param sink      新流的出口
     */
    public void bind(String sessionId, SseAgentEventSink sink) {
        open(sessionId).sink = sink;
    }

    /**
     * 把当前 SSE 流摘下来并关闭（不结束执行线程）。
     *
     * @param sessionId 会话 id
     */
    public void detach(String sessionId) {
        Turn turn = turns.get(sessionId);
        if (turn == null) {
            return;
        }
        SseAgentEventSink current = turn.sink;
        turn.sink = null;
        if (current != null) {
            // 关闭后前端那次 await 才会返回，弹窗才出得来
            current.close();
        }
    }

    /**
     * 往会话当前绑定的流写一条事件，同时扇出给与流无关的出口链。
     *
     * <p>没有流在听时 SSE 这一路静默丢弃——这是「用户关掉页面」的正常情况，不是错误。
     * 但落库那一路照样要写，否则轨迹页会缺记录。</p>
     *
     * @param sessionId 会话 id
     * @param event     事件
     */
    public void emit(String sessionId, AgentDtos.AgentEvent event) {
        // 1) 先扇出给后台出口（落库/审计）：它们的异常绝不能影响 SSE
        try {
            background.emit(event);
        } catch (RuntimeException ex) {
            // 轨迹写库失败只是少一条记录，不该让整轮对话挂掉
            log.warn("后台事件出口失败 type={}", event.type(), ex);
        }

        // 2) 再写当前绑定的 SSE 流（没有就丢弃）
        Turn turn = turns.get(sessionId);
        if (turn == null) {
            return;
        }
        SseAgentEventSink current = turn.sink;
        if (current != null) {
            current.emit(event);
        }
    }

    /**
     * 发起一次「需要用户确认」的等待。
     *
     * <p>流程：发 confirm_required → 关流（detach）→ 阻塞等 future。
     * 注意本方法会阻塞调用线程（也就是工具线程），这是有意为之。</p>
     *
     * @param sessionId 会话 id
     * @param request   确认请求（来自 ToolRuntime 的 ApprovalRequest）
     * @return 用户决定；超时或异常返回「拒绝」
     */
    public ApprovalResult askAndWait(String sessionId, ApprovalRequest request) {
        Turn turn = open(sessionId);
        String interruptId = UUID.randomUUID().toString();
        AgentDtos.AgentEvent event = events.confirmRequired(
                sessionId,
                interruptId,
                request.tool(),
                request.title(),
                request.message(),
                request.args(),
                request.allowRemember());

        CompletableFuture<ApprovalResult> future = new CompletableFuture<>();
        turn.interruptId = interruptId;
        turn.pending = new PendingAsk(interruptId, future, event);

        // 1) 先发事件：前端据此弹窗
        emit(sessionId, event);
        // 2) 立刻关流：前端 await 才会返回，弹窗才不会被「挂住」
        detach(sessionId);

        try {
            // 3) 挂起等用户点：超时按拒绝处理，绝不会永久占线程
            return future.get(ASK_TIMEOUT_MINUTES, TimeUnit.MINUTES);
        } catch (Exception ex) {
            return ApprovalResult.DENIED;
        } finally {
            turn.pending = null;
            turn.interruptId = null;
        }
    }

    /**
     * 发起一次「预算超限」的等待（前端同样走确认弹窗，只是事件名不同）。
     *
     * @param sessionId 会话 id
     * @param request   预算请求
     * @return 用户决定；超时或异常返回「拒绝」
     */
    public ApprovalResult askBudgetAndWait(String sessionId, BudgetRequest request) {
        Turn turn = open(sessionId);
        String interruptId = UUID.randomUUID().toString();
        AgentDtos.AgentEvent event = events.budgetExceeded(
                sessionId,
                interruptId,
                request.dimension(),
                request.current(),
                request.limit(),
                "本轮" + request.dimension() + "已超限，是否继续？");

        CompletableFuture<ApprovalResult> future =  new CompletableFuture<>();
        turn.interruptId = interruptId;
        turn.pending = new PendingAsk(interruptId, future, event);

        emit(sessionId, event);
        detach(sessionId);
        try {
            return future.get(ASK_TIMEOUT_MINUTES, TimeUnit.MINUTES);
        } catch (Exception ex) {
            return ApprovalResult.DENIED;
        } finally {
            turn.pending = null;
            turn.interruptId = null;
        }
    }

    /**
     * 兑现一次等待（由 /chat/resume 调用）。
     *
     * @param sessionId   会话 id
     * @param interruptId 前端带回来的中断 id
     * @param result      用户决定
     * @return true 表示确实兑现了一个等待；false 表示没有匹配的等待（可能已超时）
     */
    public boolean answer(String sessionId, String interruptId, ApprovalResult result) {
        Turn turn = turns.get(sessionId);
        if (turn == null) {
            return false;
        }
        PendingAsk pending = turn.pending;
        // interrupt_id 必须匹配：防止用户点的是上一次已经超时的弹窗
        if (pending == null || !pending.interruptId().equals(interruptId)) {
            return false;
        }
        return pending.future().complete(result);
    }

    /**
     * 查询当前是否有待确认的询问。
     *
     * @param sessionId 会话 id
     * @return true 表示正在等用户点
     */
    public boolean hasPending(String sessionId) {
        Turn turn = turns.get(sessionId);
        return turn != null && turn.pending != null;
    }

    /**
     * 这个会话当前有没有一轮在跑（侧边栏「正在回答」的小圆点靠它）。
     *
     * @param sessionId 会话 id
     * @return true 表示总线上有这个会话的状态
     */
    public boolean isRunning(String sessionId) {
        return turns.containsKey(sessionId);
    }

    /**
     * 请求停止本轮（由 /chat/stop 调用）。
     *
     * <p>若正卡在确认上，直接按拒绝兑现，避免线程等到超时。</p>
     *
     * @param sessionId 会话 id
     * @return true 表示确实叫停了一个在跑的轮次
     */
    public boolean requestStop(String sessionId) {
        Turn turn = turns.get(sessionId);
        if (turn == null) {
            return false;
        }
        turn.stopRequested = true;
        PendingAsk pending = turn.pending;
        if (pending != null) {
            pending.future().complete(ApprovalResult.DENIED);
        }
        return true;
    }

    /**
     * 一轮彻底结束：清掉状态（不影响已经关掉的流）。
     *
     * @param sessionId 会话 id
     */
    public void finish(String sessionId) {
        Turn turn = turns.remove(sessionId);
        recorders.remove(sessionId);
        if (turn != null) {
            SseAgentEventSink current = turn.sink;
            turn.sink = null;
            if (current != null) {
                current.close();
            }
        }
    }

    /**
     * 读取会话的中断 id（调试用）。
     *
     * @param sessionId 会话 id
     * @return 当前中断 id；没有则为 null
     */
    public String interruptId(String sessionId) {
        Turn turn = turns.get(sessionId);
        return turn == null ? null : turn.interruptId;
    }
}
