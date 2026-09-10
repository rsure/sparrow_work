// 模块说明：事件工厂。把「强类型载荷」翻译成「AgentEvent 信封」，业务代码不再手写 Map。
//
// 为什么需要它：AgentEvent 的 data 是 Map<String,Object>，
// 如果每个调用点都手写 Map.of(...)，字段名拼错没有任何编译期保护。
// 这里用 ObjectMapper.convertValue 一次转换，@JsonProperty 会生效，整个项目只在这一处碰 Map。
package com.example.backendjava.chat.event;

// Jackson：把 record 转成 Map，转换时会遵循 @JsonProperty 的 snake_case 约定
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

// 标准库：List / Map 用于组装载荷
import java.util.List;
import java.util.Map;

// 已有的事件信封与载荷类型
import com.example.backendjava.dto.AgentDtos;
import com.example.backendjava.dto.ChatDtos.ToolCallTrace;
import com.example.backendjava.chat.event.ChatEventPayloads.BudgetExceeded;
import com.example.backendjava.chat.event.ChatEventPayloads.ConfirmRequired;
import com.example.backendjava.chat.event.ChatEventPayloads.Done;
import com.example.backendjava.chat.event.ChatEventPayloads.Error;
import com.example.backendjava.chat.event.ChatEventPayloads.SteerInjected;
import com.example.backendjava.chat.event.ChatEventPayloads.Stopped;
import com.example.backendjava.chat.event.ChatEventPayloads.Thinking;
import com.example.backendjava.chat.event.ChatEventPayloads.Token;
import com.example.backendjava.chat.event.ChatEventPayloads.ToolEnd;
import com.example.backendjava.chat.event.ChatEventPayloads.ToolStart;

// Spring：注册成单例，把 ObjectMapper 注入进来
import org.springframework.stereotype.Component;

/**
 * 事件工厂：所有 SSE 事件都从这里造。
 *
 * <p>业务代码只写 {@code events.token("你好")}，不直接接触 Map 与 JSON。</p>
 */
@Component
public class ChatEvents {

    /** record → Map 的目标类型；字段值保持 Object，null 会保留。 */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    /** Spring 提供的 ObjectMapper，负责遵守 @JsonProperty 约定。 */
    private final ObjectMapper objectMapper;

    /**
     * 构造工厂。
     *
     * @param objectMapper Spring 容器里的 ObjectMapper
     */
    public ChatEvents(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * 造 thinking 事件。
     *
     * @param sessionId  会话 id
     * @param stage      阶段标识
     * @param delayMs    已耗时（毫秒）
     * @param historyLen 历史条数
     * @param text       提示文案
     * @return 事件信封
     */
    public AgentDtos.AgentEvent thinking(String sessionId, String stage, long delayMs, int historyLen, String text) {
        return wrap(ChatEventType.THINKING,
                new Thinking(stage, delayMs / 1000.0, sessionId, historyLen, text));
    }

    /**
     * 造 token 事件。
     *
     * @param text 增量文本
     * @return 事件信封
     */
    public AgentDtos.AgentEvent token(String text) {
        return wrap(ChatEventType.TOKEN, new Token(text));
    }

    /**
     * 造 tool_start 事件。
     *
     * @param name  工具名
     * @param input 工具入参
     * @return 事件信封
     */
    public AgentDtos.AgentEvent toolStart(String name, Map<String, Object> input) {
        return wrap(ChatEventType.TOOL_START, new ToolStart(name, input));
    }

    /**
     * 造 tool_end 事件。
     *
     * @param name            工具名
     * @param output          展示用输出
     * @param totalChars      原始字符数
     * @param truncated       是否截断
     * @param continuationRef 续读标记
     * @return 事件信封
     */
    public AgentDtos.AgentEvent toolEnd(String name, String output, long totalChars,
                                        boolean truncated, String continuationRef) {
        return wrap(ChatEventType.TOOL_END,
                new ToolEnd(name, output, totalChars, truncated, continuationRef));
    }

    /**
     * 造 confirm_required 事件。
     *
     * @param sessionId   会话 id
     * @param interruptId 中断 id
     * @param tool        工具名
     * @param title       弹窗标题
     * @param message     弹窗正文
     * @param args        工具入参
     * @param canRemember 是否允许记住
     * @return 事件信封
     */
    public AgentDtos.AgentEvent confirmRequired(String sessionId, String interruptId, String tool,
                                                String title, String message,
                                                Map<String, Object> args, boolean canRemember) {
        return wrap(ChatEventType.CONFIRM_REQUIRED,
                new ConfirmRequired(sessionId, interruptId, tool, title, message, args, canRemember));
    }

    /**
     * 造 stopped 事件。
     *
     * @param sessionId 会话 id
     * @param answer    已产出的文本
     * @param reason    停止原因
     * @return 事件信封
     */
    public AgentDtos.AgentEvent stopped(String sessionId, String answer, String reason) {
        return wrap(ChatEventType.STOPPED, new Stopped(sessionId, answer, reason));
    }

    /**
     * 造 done 事件。
     *
     * @param sessionId  会话 id
     * @param answer     完整答案
     * @param elapsedMs  耗时（毫秒）
     * @param toolCalls  工具轨迹
     * @param historyLen 历史条数
     * @param files      涉及文件
     * @param usage      用量
     * @param steerCount 插话条数
     * @param model      模型名
     * @return 事件信封
     */
    public AgentDtos.AgentEvent done(String sessionId, String answer, long elapsedMs,
                                     List<ToolCallTrace> toolCalls, int historyLen,
                                     List<String> files, Map<String, Object> usage,
                                     int steerCount, String model) {
        return wrap(ChatEventType.DONE, new Done(sessionId, answer, elapsedMs / 1000.0,
                toolCalls, historyLen, files, usage, steerCount, model));
    }

    /**
     * 造 error 事件。
     *
     * @param message 用户可读信息
     * @param detail  调试细节，可为 null
     * @return 事件信封
     */
    public AgentDtos.AgentEvent error(String message, String detail) {
        return wrap(ChatEventType.ERROR, new Error(message, detail));
    }

    /**
     * 造 steer_injected 事件。
     *
     * @param sessionId 会话 id
     * @param steerId   插话 id
     * @return 事件信封
     */
    public AgentDtos.AgentEvent steerInjected(String sessionId, String steerId) {
        return wrap(ChatEventType.STEER_INJECTED, new SteerInjected(sessionId, steerId));
    }

    /**
     * 造 budget_exceeded 事件。
     *
     * @param sessionId   会话 id
     * @param interruptId 中断 id
     * @param dimension   超限维度
     * @param current     当前值
     * @param limit       上限
     * @param message     提示文案
     * @return 事件信封
     */
    public AgentDtos.AgentEvent budgetExceeded(String sessionId, String interruptId, String dimension,
                                               double current, double limit, String message) {
        return wrap(ChatEventType.BUDGET_EXCEEDED,
                new BudgetExceeded(sessionId, interruptId, dimension, current, limit, message));
    }

    /**
     * 把「事件类型 + 载荷」装进统一信封。
     *
     * @param type    事件类型
     * @param payload 强类型载荷
     * @return 事件信封；data 已经是 snake_case 的 Map
     */
    private AgentDtos.AgentEvent wrap(ChatEventType type, Object payload) {
        // ObjectMapper 在这里把 record 转 Map：@JsonProperty 生效，null 字段保留
        Map<String, Object> data = objectMapper.convertValue(payload, MAP_TYPE);
        return new AgentDtos.AgentEvent(type.wireName(), data);
    }
}
