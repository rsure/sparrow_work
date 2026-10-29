// 模块说明：对话域的全部请求/响应 DTO。字段名与 frontend/src/services/chat.ts 严格对齐。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;
// Jakarta 校验注解：非空校验
import jakarta.validation.constraints.NotBlank;
// Jakarta 校验注解：数值范围校验
import jakarta.validation.constraints.Max;
// Jakarta 校验注解：数值范围校验
import jakarta.validation.constraints.Min;
// Jakarta 校验注解：字符串长度校验
import jakarta.validation.constraints.Size;

// 标准库：List 用于消息、工具轨迹、按模型统计
import java.util.List;
// 标准库：Map 用于承载 SSE 事件的任意负载
import java.util.Map;

/**
 * 对话域 DTO 集合。
 *
 * <p>这里刻意使用嵌套 record，而不是为每个小类型单独建文件：
 * 它们只服务于 /api/chat/*，放在一起可以一眼对照前端类型。</p>
 */
public final class ChatDtos {

    /** 工具类禁止实例化。 */
    private ChatDtos() {
    }

    // ======================================================================= //
    // 0. 请求体的默认值
    //
    // 为什么集中写在这里：前端（frontend/src/services/chat.ts）在非 doc 模式下
    // 根本不传 doc_top_k / max_iterations，后端必须有一处「不传时用哪个值」的权威来源。
    // 这两个数字与 Python 侧 backend/app/controllers/chat_controller.py 的
    // ChatRequest 字段默认值逐项对应，改一处必须同步另一处。
    // ======================================================================= //

    /** mode=doc 的检索问答默认取几个片段：前端不传 doc_top_k 时用它兜底（范围 1~20，与 Python 默认 5 一致）。 */
    static final int DEFAULT_DOC_TOP_K = 5;

    /** 单轮递归步数上限的默认值：前端不传 max_iterations 时用它兜底（范围 1~50，与 Python 默认 25 一致）。 */
    static final int DEFAULT_MAX_ITERATIONS = 25;

    // ======================================================================= //
    // 1. 请求体
    // ======================================================================= //

    /**
     * 发起一次对话的请求体，对应 POST /chat/stream。
     *
     * <p><b>为什么 docTopK / maxIterations 是 Integer 而不是 int：</b>
     * 前端只有文档模式才会带上这两个字段，普通对话根本不传。用基本类型 int 时，
     * Jackson 会把「没传」填成 0，而 0 又会被 {@code @Min(1)} 判成越界——
     * 于是请求在校验阶段就被 400 掉，{@link #withDefaults()} 里的默认值永远来不及生效。
     * 换成包装类型 Integer 后，「没传」是 null（{@code @Min/@Max} 对 null 放行），
     * 「传了 0」仍然是 0 并照旧报 400，两种意图终于能区分开。</p>
     *
     * @param message       用户输入文本；不能为空
     * @param sessionId     会话 id；为空时由服务端生成，并随 done 事件返回
     * @param mode          对话模式：agent=工具 Agent；doc=`\doc` 知识库指令
     * @param docTopK       仅 mode=doc 的检索问答生效：返回片段数上限（1~20）；null=没传，取默认 5
     * @param maxIterations LangGraph 递归步数上限（1~50）；null=没传，取默认 25
     * @param debug         是否把 Agent 事件写进服务端日志
     */
    public record ChatRequest(
            // 用户输入文本；首尾空白由服务端 trim 后再判空
            @NotBlank(message = "message 不能为空")
            String message,
            // 会话 id；首轮不传
            @JsonProperty("session_id") String sessionId,
            // 对话模式；缺省 agent
            String mode,
            // 检索片段数；null=前端没传（默认 5），显式越界仍报错
            @JsonProperty("doc_top_k")
            @Min(value = 1, message = "doc_top_k 最小为 1")
            @Max(value = 20, message = "doc_top_k 最大为 20")
            Integer docTopK,
            // 递归步数上限；null=前端没传（默认 25），显式越界仍报错
            @JsonProperty("max_iterations")
            @Min(value = 1, message = "max_iterations 最小为 1")
            @Max(value = 50, message = "max_iterations 最大为 50")
            Integer maxIterations,
            // 调试开关；默认 false
            boolean debug
    ) {

        /**
         * 补齐前端省略字段的默认值。
         *
         * <p>Java record 没有“字段默认值”，Jackson 对缺省字段填 null；
         * 这里统一归一化，避免业务层到处判断。</p>
         *
         * <p>判断条件是 {@code == null} 而不是 {@code <= 0}：显式传 0 已经被
         * {@code @Min(1)} 拦在入口（400，见 docs/adr/0001），不能在这里再悄悄改成默认值。</p>
         *
         * @return 补齐 mode / docTopK / maxIterations 后的新请求对象（三个字段都非 null）
         */
        public ChatRequest withDefaults() {
            // mode 为空时按 agent 处理，与 Python 侧默认值一致
            String safeMode = (mode == null || mode.isBlank()) ? "agent" : mode;
            // docTopK 为 null 说明前端没传；合法范围是 1~20
            int safeDocTopK = docTopK == null ? DEFAULT_DOC_TOP_K : docTopK;
            // maxIterations 为 null 说明前端没传；合法范围是 1~50
            int safeMaxIterations = maxIterations == null ? DEFAULT_MAX_ITERATIONS : maxIterations;
            return new ChatRequest(message, sessionId, safeMode, safeDocTopK, safeMaxIterations, debug);
        }
    }

    /**
     * 用户对 confirm_required 的决定，对应 POST /chat/resume。
     *
     * @param sessionId     会话 id
     * @param interruptId   中断 id，用来确认恢复的是哪一处
     * @param approved      true=同意执行；false=拒绝
     * @param remember      是否记住本工作区授权
     * @param maxIterations 恢复执行的递归步数上限；null=没传，取默认 25
     * @see ChatRequest#withDefaults() 为什么这里的步数上限也要用包装类型 Integer
     */
    public record ChatResumeRequest(
            // 会话 id；取自 confirm_required 事件
            @NotBlank(message = "session_id 不能为空")
            @JsonProperty("session_id") String sessionId,
            // 中断 id；必须与暂停时的一致
            @NotBlank(message = "interrupt_id 不能为空")
            @JsonProperty("interrupt_id") String interruptId,
            // 是否同意
            boolean approved,
            // 是否记住授权
            boolean remember,
            // 恢复执行的步数上限；null=前端没传（默认 25），显式越界仍报错
            @JsonProperty("max_iterations")
            @Min(value = 1, message = "max_iterations 最小为 1")
            @Max(value = 50, message = "max_iterations 最大为 50")
            Integer maxIterations
    ) {
        /**
         * 补齐 maxIterations 的默认值。
         *
         * @return 归一化后的新请求对象（maxIterations 非 null）
         */
        public ChatResumeRequest withDefaults() {
            return new ChatResumeRequest(
                    sessionId,
                    interruptId,
                    approved,
                    remember,
                    maxIterations == null ? DEFAULT_MAX_ITERATIONS : maxIterations
            );
        }
    }

    /**
     * 终止对话请求体，对应 POST /chat/stop。
     *
     * @param sessionId 要终止的会话 id
     */
    public record ChatStopRequest(
            // 会话 id
            @NotBlank(message = "session_id 不能为空")
            @JsonProperty("session_id") String sessionId
    ) {
    }

    /**
     * 执行中插话请求体，对应 POST /chat/{sessionId}/steer。
     *
     * @param content 要补进当前这一轮的话
     */
    public record ChatSteerRequest(
            // 插话内容；上限 2000 字，更长的内容应当等本轮结束后再发
            @NotBlank(message = "content 不能为空")
            @Size(max = 2000, message = "content 最多 2000 字")
            String content
    ) {
    }

    /**
     * 取消当前工具的请求体，对应 POST /chat/{sessionId}/tool-cancel。
     *
     * @param tool 要取消的工具名；空串表示“下一个开始的工具，不管是什么”
     */
    public record ChatToolCancelRequest(
            // 工具名；可空
            String tool
    ) {
        /**
         * 归一化空值，避免业务层出现 null 判断。
         *
         * @return tool 为空串的新请求对象
         */
        public ChatToolCancelRequest withDefaults() {
            return new ChatToolCancelRequest(tool == null ? "" : tool);
        }
    }

    /**
     * 修改会话标题/置顶/归档的请求体，对应 PATCH /chat/history/sessions/{id}。
     *
     * <p>字段用包装类型 Boolean/Integer，才能区分“没传”和“传了 false”。</p>
     *
     * @param title    新标题；null 表示不改
     * @param pinned   是否置顶；null 表示不改
     * @param archived 是否归档；null 表示不改
     */
    public record ChatSessionPatch(
            // 新标题；null=不改，空串=不改（与前端约定一致）
            String title,
            // 置顶标记；null=不改
            Boolean pinned,
            // 归档标记；null=不改
            Boolean archived
    ) {
    }

    // ======================================================================= //
    // 2. 响应体
    // ======================================================================= //

    /**
     * 终止对话的返回体。
     *
     * @param stopped   是否确实叫停了一条流；false 表示当前没有在跑的流
     * @param sessionId 会话 id
     */
    public record ChatStopResult(
            // 是否叫停成功
            boolean stopped,
            // 会话 id
            @JsonProperty("session_id") String sessionId
    ) {
    }

    /**
     * 插话的返回体。
     *
     * @param sessionId 会话 id
     * @param steerId   本次插话的 id
     * @param content   插话内容
     * @param queued    是否已入队（true 表示等下一个工具边界注入）
     * @param pending   当前队列里还有多少条待注入
     */
    public record ChatSteerResult(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 插话 id
            @JsonProperty("steer_id") String steerId,
            // 插话内容
            String content,
            // 是否已入队
            boolean queued,
            // 待注入条数
            int pending
    ) {
    }

    /**
     * 取消工具的返回体。
     *
     * @param sessionId 会话 id
     * @param cancelled 是否已登记取消
     * @param tool      被取消的工具名；空串时前端显示“下一个工具”
     */
    public record ChatToolCancelResult(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 是否登记成功
            boolean cancelled,
            // 工具名
            String tool
    ) {
    }

    /**
     * 会话运行时状态，对应 GET /chat/sessions/{id}。
     *
     * @param exists     会话是否还在后端内存里
     * @param sessionId  会话 id
     * @param messages   历史消息条数；exists=false 时为 null
     * @param createdAt  创建时间（Unix 秒）；exists=false 时为 null
     * @param lastActive 最近活跃时间（Unix 秒）；exists=false 时为 null
     * @param running    当前是否有正在执行的流
     */
    public record SessionInfo(
            // 是否还存在
            boolean exists,
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 消息条数
            Integer messages,
            // 创建时间（Unix 秒）
            @JsonProperty("created_at") Double createdAt,
            // 最近活跃时间（Unix 秒）
            @JsonProperty("last_active") Double lastActive,
            // 是否正在执行
            boolean running
    ) {
    }

    /**
     * 最近会话列表的一行，对应 GET /chat/sessions 的 sessions 元素。
     *
     * @param sessionId   会话 id
     * @param title       会话标题
     * @param mode        最近一次使用的模式
     * @param messageCount 已落库消息条数
     * @param createdAt   创建时间（ISO-8601）
     * @param updatedAt   最近更新时间（ISO-8601）
     * @param preview     最后一条消息的一行预览
     * @param pinned      是否置顶
     * @param archived    是否归档
     */
    public record ChatSessionInfo(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 标题
            String title,
            // 最近一次模式
            String mode,
            // 消息条数
            @JsonProperty("message_count") long messageCount,
            // 创建时间
            @JsonProperty("created_at") String createdAt,
            // 最近更新时间
            @JsonProperty("updated_at") String updatedAt,
            // 最后一条消息预览
            String preview,
            // 是否置顶
            boolean pinned,
            // 是否归档
            boolean archived
    ) {
    }

    /**
     * 会话列表返回体，对应 GET /chat/sessions。
     *
     * @param sessions 会话数组
     */
    public record ChatSessionList(
            // 会话数组
            List<ChatSessionInfo> sessions
    ) {
    }

    /**
     * 工具轨迹里的一条记录。
     *
     * @param name    工具名
     * @param input   工具入参；结构由具体工具决定
     * @param output  工具输出摘要
     * @param confirm 用户确认结果；没有确认环节时为 null
     */
    public record ToolCallTrace(
            // 工具名
            String name,
            // 工具入参
            Object input,
            // 工具输出
            String output,
            // 确认结果
            String confirm
    ) {
    }

    /**
     * 落库的一条历史消息。
     *
     * @param id           消息主键；同一会话内越大越新
     * @param role         说话人：user / assistant
     * @param content      消息正文
     * @param mode         该消息所属的对话模式
     * @param toolCalls    助手调用过的工具轨迹；用户消息为 null
     * @param finishReason 本轮结束原因：done / stopped / error / pending_confirm
     * @param elapsed      本轮耗时（秒）；用户消息为 null
     * @param createdAt    入库时间（ISO-8601）
     */
    public record StoredChatMessage(
            // 消息主键
            long id,
            // 角色
            String role,
            // 正文
            String content,
            // 模式
            String mode,
            // 工具轨迹
            @JsonProperty("tool_calls") List<ToolCallTrace> toolCalls,
            // 结束原因
            @JsonProperty("finish_reason") String finishReason,
            // 耗时秒数
            Double elapsed,
            // 入库时间
            @JsonProperty("created_at") String createdAt
    ) {
    }

    /**
     * 历史消息返回体，对应 GET /chat/history/sessions/{id}。
     *
     * @param sessionId 会话 id
     * @param messages  按时间升序的消息列表
     * @param hasMore   是否还有更早的消息没返回（true 时前端可以显示「加载更早」）
     */
    public record ChatHistory(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 消息列表
            List<StoredChatMessage> messages,
            // 更早的消息还有没有：由后端多取一条判断，不需要额外 COUNT
            @JsonProperty("has_more") boolean hasMore
    ) {
    }

    /**
     * 修改会话标记后的返回体。
     *
     * @param renamed   标题是否真的被改了
     * @param sessionId 会话 id
     * @param title     落库后的标题
     * @param pinned    落库后的置顶状态
     * @param archived  落库后的归档状态
     */
    public record ChatSessionPatchResult(
            // 是否改名
            boolean renamed,
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 标题
            String title,
            // 置顶
            boolean pinned,
            // 归档
            boolean archived
    ) {
    }

    /**
     * 删除会话的返回体。
     *
     * @param deleted   是否确实删掉了一个会话
     * @param sessionId 会话 id
     */
    public record DeleteSessionResult(
            // 是否删除
            boolean deleted,
            // 会话 id
            @JsonProperty("session_id") String sessionId
    ) {
    }

    /**
     * 清空会话上下文的返回体，对应 DELETE /chat/sessions/{id}。
     *
     * @param cleared   是否确实清掉了一个会话
     * @param sessionId 会话 id
     */
    public record ClearSessionResult(
            // 是否清空
            boolean cleared,
            // 会话 id
            @JsonProperty("session_id") String sessionId
    ) {
    }

    /**
     * 按模型拆分的用量。
     *
     * @param model  模型名
     * @param turns  轮次
     * @param tokens 累计 token
     * @param cost   折算费用（元）
     */
    public record ModelUsage(
            // 模型名
            String model,
            // 轮次
            long turns,
            // token 数
            long tokens,
            // 费用（元）
            double cost
    ) {
    }

    /**
     * 会话级用量汇总，对应 GET /chat/history/sessions/{id}/usage。
     *
     * @param sessionId   会话 id
     * @param turns       有用量记录的轮次数
     * @param inputTokens 累计输入 token
     * @param outputTokens 累计输出 token
     * @param totalTokens 累计总 token
     * @param cost        折算费用（元）
     * @param currency    币种；当前恒为 CNY
     * @param byModel     按模型拆分
     */
    public record SessionUsage(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 轮次
            long turns,
            // 输入 token
            @JsonProperty("input_tokens") long inputTokens,
            // 输出 token
            @JsonProperty("output_tokens") long outputTokens,
            // 总 token
            @JsonProperty("total_tokens") long totalTokens,
            // 费用
            double cost,
            // 币种
            String currency,
            // 按模型拆分
            @JsonProperty("by_model") List<ModelUsage> byModel
    ) {
    }

    /**
     * 会话导出结果，对应 GET /chat/history/sessions/{id}/export。
     *
     * @param sessionId    会话 id
     * @param format       实际格式：md / json
     * @param filename     后端建议的文件名
     * @param content      文件全文
     * @param messageCount 导出时的消息条数
     */
    public record ExportedSession(
            // 会话 id
            @JsonProperty("session_id") String sessionId,
            // 格式
            String format,
            // 文件名
            String filename,
            // 文件全文
            String content,
            // 消息条数
            @JsonProperty("message_count") long messageCount
    ) {
    }

    /**
     * 工具完整输出，对应 GET /chat/tool-output/{ref}。
     *
     * @param ref     续读标记
     * @param found   完整内容是否还在
     * @param content 完整文本；found=false 时为空串
     * @param chars   字符数
     */
    public record ToolOutputPayload(
            // 续读标记
            String ref,
            // 是否找到
            boolean found,
            // 完整文本
            String content,
            // 字符数
            long chars
    ) {
    }

    /**
     * SSE 事件统一结构。
     *
     * <p>真正的线上格式由 ChatService 实现决定：事件名放 SSE 的 event 字段，
     * 本对象的 data 放 JSON 负载。这里定义结构是为了让服务层与测试有共同类型。</p>
     *
     * @param type 事件名：thinking / token / tool_start / tool_end / confirm_required / done / error / stopped 等
     * @param data 事件负载
     */
    public record ChatEvent(
            // 事件名
            String type,
            // 事件负载
            Map<String, Object> data
    ) {
    }
}
