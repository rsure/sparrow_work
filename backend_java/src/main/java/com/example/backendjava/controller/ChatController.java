// 模块说明：对话接口。路径与 Python 侧 /api/chat/* 完全一致，便于前端零改动切换后端。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501，而不是让应用启动失败
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：声明 REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /chat
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：PATCH 映射
import org.springframework.web.bind.annotation.PatchMapping;
// Spring Web 注解：DELETE 映射
import org.springframework.web.bind.annotation.DeleteMapping;
// Spring Web 注解：路径变量
import org.springframework.web.bind.annotation.PathVariable;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
// Spring Web 注解：JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// Jakarta 校验注解：触发 DTO 上的约束校验
import jakarta.validation.Valid;
// Spring MVC 的 SSE 发射器：流式接口的返回类型
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// 项目内：Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 对话业务接口：SSE 流式对话、会话历史与中断恢复
import com.example.backendjava.service.ChatService;
// 对话接口的请求/响应 DTO 容器
import com.example.backendjava.dto.ChatDtos;

// 标准库：Map 用于事件协议说明
import java.util.Map;

/**
 * 对话接口。
 *
 * <p><b>为什么返回裸 JSON 而不是 ApiResponse：</b>前端 {@code services/chat.ts} 的
 * {@code chatJson()} 直接读取裸对象（例如 {@code {sessions:[...]}}、{@code {stopped:true}}）。
 * Python 侧的 /chat/* 辅助端点也返回裸 JSON，这里保持兼容，前端不需要改代码。</p>
 *
 * <p>例外：{@code /chat/stream} 与 {@code /chat/resume} 返回 text/event-stream（SSE）。</p>
 */
@RestController
@RequestMapping("/chat")
public class ChatController {

    /** 对话服务；当前工程只提供接口，学习者实现后自动被找到。 */
    private final ObjectProvider<ChatService> chatService;

    /**
     * 构造器注入可选 Service。
     *
     * @param chatService Spring 的按类型查找器
     */
    public ChatController(ObjectProvider<ChatService> chatService) {
        this.chatService = chatService;
    }

    /**
     * 流式对话主入口。
     *
     * @param request 对话请求
     * @return SSE 流
     */
    @PostMapping("/stream")
    public SseEmitter stream(@Valid @RequestBody ChatDtos.ChatRequest request) {
        return ServiceSupport.require(chatService, "对话服务").stream(request.withDefaults());
    }

    /**
     * 用户确认后恢复执行。
     *
     * @param request 恢复请求
     * @return SSE 流
     */
    @PostMapping("/resume")
    public SseEmitter resume(@Valid @RequestBody ChatDtos.ChatResumeRequest request) {
        return ServiceSupport.require(chatService, "对话服务").resume(request.withDefaults());
    }

    /**
     * 终止当前会话正在执行的流。
     *
     * @param request 终止请求
     * @return 终止结果
     */
    @PostMapping("/stop")
    public ChatDtos.ChatStopResult stop(@Valid @RequestBody ChatDtos.ChatStopRequest request) {
        return ServiceSupport.require(chatService, "对话服务").stop(request);
    }

    /**
     * 执行中插话。
     *
     * @param sessionId 会话 id
     * @param request   插话内容
     * @return 受理结果
     */
    @PostMapping("/{sessionId}/steer")
    public ChatDtos.ChatSteerResult steer(
            @PathVariable String sessionId,
            @Valid @RequestBody ChatDtos.ChatSteerRequest request
    ) {
        return ServiceSupport.require(chatService, "对话服务").steer(sessionId, request);
    }

    /**
     * 取消下一个尚未开始的工具。
     *
     * @param sessionId 会话 id
     * @param request   工具名
     * @return 受理结果
     */
    @PostMapping("/{sessionId}/tool-cancel")
    public ChatDtos.ChatToolCancelResult cancelTool(
            @PathVariable String sessionId,
            @RequestBody ChatDtos.ChatToolCancelRequest request
    ) {
        return ServiceSupport.require(chatService, "对话服务")
                .cancelTool(sessionId, request.withDefaults());
    }

    /**
     * 最近会话列表。
     *
     * @param limit    最多返回多少条，默认 20
     * @param query    搜索关键词，可选
     * @param archived 是否查询归档箱，默认 false
     * @return 会话列表
     */
    @GetMapping("/sessions")
    public ChatDtos.ChatSessionList listSessions(
            @RequestParam(defaultValue = "20") int limit,
            // 前端查询参数名是 q（不是 query）；显式写 name 才能正确绑定
            @RequestParam(name = "q", required = false, defaultValue = "") String query,
            @RequestParam(defaultValue = "false") boolean archived
    ) {
        return ServiceSupport.require(chatService, "对话服务").listSessions(limit, query, archived);
    }

    /**
     * 某个会话的历史消息。
     *
     * @param sessionId 会话 id
     * @param limit     最多返回多少条，默认 200
     * @return 历史消息
     */
    @GetMapping("/history/sessions/{sessionId}")
    public ChatDtos.ChatHistory history(
            @PathVariable String sessionId,
            @RequestParam(defaultValue = "200") int limit
    ) {
        return ServiceSupport.require(chatService, "对话服务").history(sessionId, limit);
    }

    /**
     * 修改会话标题/置顶/归档。
     *
     * @param sessionId 会话 id
     * @param patch     要修改的字段
     * @return 落库后的标记
     */
    @PatchMapping("/history/sessions/{sessionId}")
    public ChatDtos.ChatSessionPatchResult patchSession(
            @PathVariable String sessionId,
            @RequestBody ChatDtos.ChatSessionPatch patch
    ) {
        return ServiceSupport.require(chatService, "对话服务").patchSession(sessionId, patch);
    }

    /**
     * 导出会话内容。
     *
     * @param sessionId 会话 id
     * @param format    md 或 json，默认 md
     * @return 导出结果
     */
    @GetMapping("/history/sessions/{sessionId}/export")
    public ChatDtos.ExportedSession export(
            @PathVariable String sessionId,
            @RequestParam(defaultValue = "md") String format
    ) {
        return ServiceSupport.require(chatService, "对话服务").export(sessionId, format);
    }

    /**
     * 会话级 token / 费用汇总。
     *
     * @param sessionId 会话 id
     * @return 用量汇总
     */
    @GetMapping("/history/sessions/{sessionId}/usage")
    public ChatDtos.SessionUsage usage(@PathVariable String sessionId) {
        return ServiceSupport.require(chatService, "对话服务").usage(sessionId);
    }

    /**
     * 永久删除某个会话及其消息。
     *
     * @param sessionId 会话 id
     * @return 删除结果
     */
    @DeleteMapping("/history/sessions/{sessionId}")
    public ChatDtos.DeleteSessionResult deleteHistory(@PathVariable String sessionId) {
        return ServiceSupport.require(chatService, "对话服务").deleteHistory(sessionId);
    }

    /**
     * 查询会话运行时状态。
     *
     * @param sessionId 会话 id
     * @return 运行时状态
     */
    @GetMapping("/sessions/{sessionId}")
    public ChatDtos.SessionInfo sessionInfo(@PathVariable String sessionId) {
        return ServiceSupport.require(chatService, "对话服务").sessionInfo(sessionId);
    }

    /**
     * 清空会话上下文。
     *
     * @param sessionId 会话 id
     * @return 清空结果
     */
    @DeleteMapping("/sessions/{sessionId}")
    public ChatDtos.ClearSessionResult clearSession(@PathVariable String sessionId) {
        return ServiceSupport.require(chatService, "对话服务").clearSession(sessionId);
    }

    /**
     * 按续读标记读取工具完整输出。
     *
     * @param ref 续读标记
     * @return 完整输出
     */
    @GetMapping("/tool-output/{ref}")
    public ChatDtos.ToolOutputPayload toolOutput(@PathVariable String ref) {
        return ServiceSupport.require(chatService, "对话服务").toolOutput(ref);
    }

    /**
     * 返回对话事件协议说明。
     *
     * @return 事件协议字典
     */
    @GetMapping("/events")
    public Map<String, Object> events() {
        return ServiceSupport.require(chatService, "对话服务").events();
    }
}
