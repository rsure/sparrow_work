// 模块说明：对话域业务接口。Controller 只做协议适配，具体实现由学习者补上。
package com.example.backendjava.service;

// Spring MVC 的 SSE 发射器：实现类用它逐帧推送事件
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

// 标准库：Map 用于事件协议说明
import java.util.Map;

// 对话接口的请求/响应 DTO 容器
import com.example.backendjava.dto.ChatDtos;

/**
 * 对话服务接口。
 *
 * <p>实现建议：</p>
 * <ol>
 *   <li>用 LangChain4j 的 StreamingChatModel 负责模型调用与工具循环；</li>
 *   <li>用 LangGraph4j 的 StateGraph + SQLiteSaver 负责状态、检查点与人工确认中断；</li>
 *   <li>把每个事件转成 SSE 帧：event=事件名，data=JSON 负载；</li>
 *   <li>会话级并发控制放在实现类里（同一 sessionId 同时只允许一条流）。</li>
 * </ol>
 */
public interface ChatService {

    /**
     * 发起一次流式对话。
     *
     * @param request 已补齐默认值的对话请求
     * @return SSE 发射器；调用方负责把它返回给 Spring MVC
     */
    SseEmitter stream(ChatDtos.ChatRequest request);

    /**
     * 用户确认后恢复被中断的图。
     *
     * @param request 已补齐默认值的恢复请求
     * @return SSE 发射器
     */
    SseEmitter resume(ChatDtos.ChatResumeRequest request);

    /**
     * 终止某个会话正在执行的流。
     *
     * @param request 终止请求
     * @return 是否确实叫停了一条流
     */
    ChatDtos.ChatStopResult stop(ChatDtos.ChatStopRequest request);

    /**
     * 执行期间追加一句指令，不打断已经生成的内容。
     *
     * @param sessionId 会话 id
     * @param request   插话内容
     * @return 受理结果
     */
    ChatDtos.ChatSteerResult steer(String sessionId, ChatDtos.ChatSteerRequest request);

    /**
     * 取消下一个尚未开始的工具。
     *
     * @param sessionId 会话 id
     * @param request   要取消的工具名；空串表示下一个工具
     * @return 受理结果
     */
    ChatDtos.ChatToolCancelResult cancelTool(String sessionId, ChatDtos.ChatToolCancelRequest request);

    /**
     * 列出最近会话。
     *
     * @param limit    最多返回多少条
     * @param query    搜索关键词；空串表示不过滤
     * @param archived 是否查询归档箱
     * @return 会话列表
     */
    ChatDtos.ChatSessionList listSessions(int limit, String query, boolean archived);

    /**
     * 读取某个会话的历史消息。
     *
     * @param sessionId 会话 id
     * @param limit     最多返回多少条
     * @return 历史消息
     */
    ChatDtos.ChatHistory history(String sessionId, int limit);

    /**
     * 修改会话标题/置顶/归档。
     *
     * @param sessionId 会话 id
     * @param patch     要修改的字段
     * @return 落库后的标记
     */
    ChatDtos.ChatSessionPatchResult patchSession(String sessionId, ChatDtos.ChatSessionPatch patch);

    /**
     * 导出会话内容。
     *
     * @param sessionId 会话 id
     * @param format    md 或 json
     * @return 导出结果
     */
    ChatDtos.ExportedSession export(String sessionId, String format);

    /**
     * 读取会话级 token / 费用汇总。
     *
     * @param sessionId 会话 id
     * @return 用量汇总
     */
    ChatDtos.SessionUsage usage(String sessionId);

    /**
     * 永久删除某个会话及其消息。
     *
     * @param sessionId 会话 id
     * @return 删除结果
     */
    ChatDtos.DeleteSessionResult deleteHistory(String sessionId);

    /**
     * 查询会话运行时状态。
     *
     * @param sessionId 会话 id
     * @return 运行时状态
     */
    ChatDtos.SessionInfo sessionInfo(String sessionId);

    /**
     * 清空会话上下文（保留落库历史，仅丢弃运行时状态与检查点）。
     *
     * @param sessionId 会话 id
     * @return 清空结果
     */
    ChatDtos.ClearSessionResult clearSession(String sessionId);

    /**
     * 按续读标记读取工具的完整输出。
     *
     * @param ref 续读标记
     * @return 完整输出
     */
    ChatDtos.ToolOutputPayload toolOutput(String ref);

    /**
     * 返回对话事件协议说明，对应 GET /chat/events。
     *
     * @return 事件协议字典
     */
    Map<String, Object> events();
}
