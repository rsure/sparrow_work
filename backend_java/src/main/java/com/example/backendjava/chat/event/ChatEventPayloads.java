// 模块说明：所有 SSE 事件的载荷定义（强类型）。
//
// 为什么集中在一个文件：这些 record 每个只有几行，拆成十几个文件反而难找；
// 集中之后，这个文件本身就是一份「前后端事件协议清单」。
// 为什么用 record 而不是 Map：字段名编译期可查，@JsonProperty 保证 snake_case，
// 且 null 会正常序列化（Map.of 不允许 null，"没有截断"这种情况会很别扭）。
package com.example.backendjava.chat.event;

// 标准库：List 承载工具调用轨迹、文件清单与子任务
import java.util.List;
// 标准库：Map 承载用量等结构不固定的附加信息
import java.util.Map;

// Jackson 注解：把 Java 驼峰字段名映射成前端要的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;

// 工具调用轨迹：done 事件与历史消息共用同一个类型，避免两套结构
import com.example.backendjava.dto.ChatDtos.ToolCallTrace;

/**
 * 事件载荷集合。
 *
 * <p>每个嵌套 record 对应 {@link ChatEventType} 里的一个事件；
 * 字段名（JSON）必须与 frontend/src/services/chat.ts 中的同名 interface 对齐。</p>
 */
public final class ChatEventPayloads {

    /** 工具类禁止实例化。 */
    private ChatEventPayloads() {
    }

    /**
     * thinking 事件载荷。
     *
     * @param stage      阶段标识：start / history / model / tool，前端可用于去重
     * @param delay      本阶段已耗时（秒），前端做「已等待 3 秒」这类提示
     * @param sessionId  会话 id
     * @param historyLen 已加载的历史消息条数
     * @param text       给用户看的一句话
     */
    public record Thinking(
            // 阶段标识
            String stage,
            // 已耗时（秒）
            double delay,
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 历史消息条数
            @JsonProperty("history_len") int historyLen,
            // 提示文案
            String text
    ) {
    }

    /**
     * token 事件载荷。
     *
     * @param text 本次增量文本（可能只有一个字）
     */
    public record Token(
            // 增量文本
            String text
    ) {
    }

    /**
     * tool_start 事件载荷。
     *
     * @param name  工具名
     * @param input 工具入参（原样透传，前端折叠展示）
     */
    public record ToolStart(
            // 工具名
            String name,
            // 工具入参
            Map<String, Object> input
    ) {
    }

    /**
     * tool_end 事件载荷。
     *
     * <p>total_chars / truncated / continuation_ref 三个字段来自
     * {@code OutputContract.takeLastTruncation(sessionId, toolName)}，前端靠它们显示「展开全文」。</p>
     *
     * @param name            工具名
     * @param output          展示用输出（可能已截断）
     * @param totalChars      截断前的原始字符数
     * @param truncated       是否发生了截断
     * @param continuationRef 续读标记；未截断时为 null，前端据此决定是否显示链接
     */
    public record ToolEnd(
            // 工具名
            String name,
            // 展示用输出
            String output,
            // 原始字符数
            @JsonProperty("total_chars") long totalChars,
            // 是否截断
            boolean truncated,
            // 续读标记；未截断时为 null
            @JsonProperty("continuation_ref") String continuationRef
    ) {
    }

    /**
     * confirm_required 事件载荷。
     *
     * <p><b>发送本事件后必须立刻关闭当前 SSE 流</b>，前端会弹窗并在用户点选后
     * 用 interrupt_id 调 POST /chat/resume 打开一条新流。</p>
     *
     * @param sessionId   会话 id
     * @param interruptId 中断 id，恢复时原样带回
     * @param tool        要执行的工具名
     * @param title       弹窗标题
     * @param message     弹窗正文
     * @param args        工具入参，弹窗里可折叠展示
     * @param canRemember 是否允许「本工作区以后都同意」
     */
    public record ConfirmRequired(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 中断 id
            @JsonProperty("interrupt_id") String interruptId,
            // 工具名
            String tool,
            // 弹窗标题
            String title,
            // 弹窗正文
            String message,
            // 工具入参
            Map<String, Object> args,
            // 是否允许记住
            @JsonProperty("can_remember") boolean canRemember
    ) {
    }

    /**
     * stopped 事件载荷。
     *
     * @param sessionId 会话 id
     * @param answer    停止前已经吐出的文本
     * @param reason    停止原因：user_stop / timeout
     */
    public record Stopped(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 已产出的文本
            String answer,
            // 停止原因
            String reason
    ) {
    }

    /**
     * done 事件载荷。
     *
     * <p>字段对齐前端 DoneEvent：answer/elapsed/tool_calls/history_len/files/usage/steer_count/model。
     * subtasks 只在计划模式下出现，本轮先不发。</p>
     *
     * @param sessionId  会话 id
     * @param answer     完整答案文本
     * @param elapsed    本轮耗时（秒）
     * @param toolCalls  本轮工具调用轨迹
     * @param historyLen 本轮结束后的历史消息条数
     * @param files      本轮涉及的文件路径
     * @param usage      用量：input_tokens / output_tokens / total_tokens / cost
     * @param steerCount 本轮注入的插话条数
     * @param model      实际使用的模型名
     */
    public record Done(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 完整答案
            String answer,
            // 耗时（秒）
            double elapsed,
            // 工具轨迹
            @JsonProperty("tool_calls") List<ToolCallTrace> toolCalls,
            // 历史条数
            @JsonProperty("history_len") int historyLen,
            // 涉及文件
            List<String> files,
            // 用量
            Map<String, Object> usage,
            // 插话条数
            @JsonProperty("steer_count") int steerCount,
            // 模型名
            String model
    ) {
    }

    /**
     * error 事件载荷。
     *
     * @param message 面向用户的错误说明（不要放堆栈）
     * @param detail  排查细节；仅 debug 模式带，否则为 null
     */
    public record Error(
            // 用户可读信息
            String message,
            // 调试细节
            String detail
    ) {
    }

    /**
     * steer_injected 事件载荷。
     *
     * @param sessionId 会话 id
     * @param steerId   插话 id，与 POST /chat/{id}/steer 返回的一致
     */
    public record SteerInjected(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 插话 id
            @JsonProperty("steer_id") String steerId
    ) {
    }

    /**
     * budget_exceeded 事件载荷。
     *
     * @param sessionId   会话 id
     * @param interruptId 中断 id（前端同样走确认弹窗，这个值必须带）
     * @param dimension   维度：tokens / cost / duration
     * @param current     当前值
     * @param limit       上限
     * @param message     给用户看的一句话
     */
    public record BudgetExceeded(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 中断 id
            @JsonProperty("interrupt_id") String interruptId,
            // 超限维度
            String dimension,
            // 当前值
            double current,
            // 上限
            double limit,
            // 提示文案
            String message
    ) {
    }
}
