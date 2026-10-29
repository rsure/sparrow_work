// 模块说明：对话服务的 Java 实现。当前阶段完成流式对话入口的基础装配：
// （1）会话 id 初始化；（2）按设置补全模型装配参数 LlmModelSpec；
// （3）从 classpath 读取系统提示词；（4）把注册表里的 AgentTool 交给 LangChain4j 的工具循环。
// SSE 逐帧推送、检查点与其余会话管理接口留待后续里程碑补齐。
package com.example.backendjava.service.impl;

// 唯一 id 工具：首轮请求未带 session_id 时生成一个 32 位十六进制会话 id
import cn.hutool.core.util.IdUtil;
import cn.hutool.core.util.StrUtil;
import com.example.backendjava.chat.event.ChatEvents;
import com.example.backendjava.chat.event.SseAgentEventSink;
import com.example.backendjava.chat.event.TraceEventSink;
import com.example.backendjava.chat.runtime.*;
import com.example.backendjava.common.ApiException;
// 项目内：limit 的默认值与上限契约表（与 Python 侧 app/core/limits.py 一一对应）
import com.example.backendjava.common.PageLimits;
import com.example.backendjava.dto.ChatDtos;
import com.example.backendjava.dto.LlmDtos;
import com.example.backendjava.dto.LlmModelSpec;
import com.example.backendjava.dto.ToolResult;
import com.example.backendjava.entity.ChatMessage;
import com.example.backendjava.entity.ChatSession;
import com.example.backendjava.llm.LlmModelFactoryRouter;
import com.example.backendjava.llm.LlmProviderRegistry;
import com.example.backendjava.repository.ChatMessageRepository;
import com.example.backendjava.repository.ChatSessionRepository;
import com.example.backendjava.service.AgentTool;
import com.example.backendjava.service.Assistant;
import com.example.backendjava.service.ChatService;
import com.example.backendjava.service.ToolRegistry;
import com.example.backendjava.settings.SecretStore;
import com.example.backendjava.settings.SettingsRegistry;
import com.example.backendjava.tools.*;
import com.example.backendjava.util.JsonUtils;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.model.chat.StreamingChatModel;
import dev.langchain4j.model.chat.request.json.JsonObjectSchema;
import dev.langchain4j.model.output.TokenUsage;
import dev.langchain4j.service.AiServices;
import dev.langchain4j.service.tool.ToolExecutor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ResourceLoader;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;

// 字符串工具：判断前端传来的 session_id / 工具参数 JSON 是否为空白
// Jackson 泛型类型引用：把工具参数的 JSON 文本解析成 Map<String, Object>
// 项目内业务异常：供应商未知、模型清单为空、缺少密钥时给出可读提示
// 对话接口的请求/响应 DTO 容器：本类用到 ChatRequest 及其余接口返回类型
// 模型供应商/模型/探测的 DTO 容器：装配参数时需要 ProviderInfo 的默认地址与密钥名
// 装配一个模型实例所需的参数（供应商、模型、密钥、地址、温度、输出上限）
// 工具执行结果：工具抛异常时用它拼出带 FAIL: 前缀的文本回给模型
// 模型工厂路由器：按供应商 id 选择具体工厂并创建流式模型
// 内置供应商清单：提供默认 baseUrl、密钥名与「是否需要密钥」判断
// 单项工具能力接口：工具表里每个元素都是一个 AgentTool
// LangChain4j 流式助手接口：AiServices 按它生成代理，承载一次流式对话
// 对话业务接口：本类实现它
// 工具注册表：主 Agent 从这里取全部已登记工具
// 密钥仓库：从加密存储里取出当前供应商的 API Key
// 设置注册表：模型供应商/模型名/接口地址/温度/输出上限/权限模式的唯一读取入口
// 路径策略：取全局工作区白名单，构造工具会话上下文
// 工具会话上下文：把会话 id、权限模式传给裁决/预算/审计逻辑
// 工具层 ThreadLocal 上下文：在真正执行工具的线程上设置与清理
// JSON 工具：工具参数 JSON 统一走全局 ObjectMapper，失败时抛可读异常
// LangChain4j 工具调用请求：模型决定调用某个工具时给出的名字与 JSON 参数
// LangChain4j 工具规格：告诉模型「有哪些工具、各自做什么、参数长什么样」
// LangChain4j 流式模型接口：本类持有并交给 AiServices 发起流式请求
// LangChain4j 工具参数的 JSON Schema：描述工具入参的结构
// LangChain4j 助手工厂：把系统提示词、工具与流式模型组装成可调用的代理
// LangChain4j 流式令牌：注册 token/完成/错误回调，调用 start() 后开始生成
// LangChain4j 工具执行器：框架回调它，本项目再转交给 AgentTool.execute
// Jakarta 生命周期注解：应用启动完成后加载系统提示词（缺失即启动失败）
// Jakarta 依赖注入注解（Spring 直接支持）：按类型注入字段，与项目现有写法保持一致
// Spring 资源加载器：按 classpath: 前缀定位提示词文件
// （注意：Spring 的 Resource 接口与上面的 jakarta.annotation.Resource 同名，
//   所以本文件不 import 它，用到时写全限定名，避免 single-type-import 冲突）
// Spring 服务注解：把本类注册成 ChatService 的实现
// Spring MVC 的 SSE 发射器：流式接口的返回类型
// 标准库：IOException 读取提示词文件失败时向上抛启动异常
// 标准库：StandardCharsets 显式用 UTF-8 读取提示词，避免平台默认编码读坏中文
// 标准库：LinkedHashMap 保持工具注入顺序，便于诊断与日志对照
// 标准库：Map 保存「工具规格 -> 执行器」的映射
// 标准库：Set 构造「本会话没有额外禁用/放行」的空集合

/**
 * 对话服务实现。
 *
 * <p>当前只实现「一次流式对话」的入口装配，重点是把「会话是谁」与「用哪个模型」
 * 这两件事从设置里解析出来，避免业务代码里散落硬编码的模型名和密钥。</p>
 */
@Slf4j
@Service
public class ChatServiceImpl implements ChatService {

    /** 模型工厂路由器：按供应商 id 创建流式模型，业务层不感知具体实现类。 */
    @Resource
    private LlmModelFactoryRouter llmModelFactoryRouter;

    /** 设置注册表：模型装配参数（供应商/模型名/地址/温度/上限）的唯一来源。 */
    @Resource
    private SettingsRegistry settingsRegistry;

    /** 密钥仓库：按供应商声明的密钥名取出加密保存的 API Key。 */
    @Resource
    private SecretStore secretStore;

    /** 内置供应商清单：校验供应商是否存在，并提供默认地址与密钥名。 */
    @Resource
    private LlmProviderRegistry llmProviderRegistry;

    /** 工具注册表：主 Agent 从这里取出全部已登记工具。 */
    @Resource
    private ToolRegistry toolRegistry;

    /** Spring 资源加载器：启动时按 classpath: 前缀读取系统提示词模板。 */
    @Resource
    private ResourceLoader resourceLoader;


    // 会话总线：管「事件往哪条流写」与「确认挂起/唤醒」
    @Resource
    private ChatSessionBus sessionBus;

    // 事件工厂：所有事件都从它造
    @Resource
    private ChatEvents chatEvents;

    // 轮次线程池：把阻塞的模型调用挪出 Tomcat 线程
    @Resource
    private ExecutorService chatTurnExecutor;

    // 轨迹出口：给它设置轮次 id
    @Resource
    private TraceEventSink traceEventSink;

    // 输出治理：给工具执行器传
    @Resource
    private OutputContract outputContract;

    // 会话仓库：落库
    @Resource
    private ChatSessionRepository chatSessionRepository;

    // 消息仓库：落库
    @Resource
    private ChatMessageRepository chatMessageRepository;
    // 消息仓库：落库
    @Resource
    private SessionSteeringQueue steeringQueue;
    // 消息仓库：落库
    @Resource
    private ToolCancelRegistry toolCancelRegistry;
    // 消息仓库：落库 会话与消息的读写都走它
    @Resource
    private ChatPersistence chatPersistence;

    // 对象映射：JSON 序列化（审计、用量等）
    @Resource
    private ObjectMapper objectMapper;

    /** 系统提示词：启动时一次性读入，之后每轮对话复用；修改模板后需重启服务才会生效。 系统提示词不应该暴露给用户随意修改*/
    private String systemPrompt;


    /** 工具参数 schema：开放对象，允许模型按工具说明自行组织字段。 */
    private static final JsonObjectSchema OPEN_PARAMETERS = JsonObjectSchema.builder()
            // AgentTool 目前没有字段级参数声明，先允许任意字段，避免把模型的合法参数全部拒掉
            .additionalProperties(true)
            .build();

    /**
     * 启动时加载系统提示词。
     *
     * <p>提示词是 Agent 的行为准则。读不到时直接让启动失败，避免服务在「没有规则」
     * 的状态下对外提供对话能力；同时去掉模板开头的 HTML 注释——那是写给维护者看的，
     * 不应该进入模型的上下文。</p>
     *
     * @throws IllegalStateException 提示词文件缺失或读取失败
     */
    @PostConstruct
    void loadSystemPrompt() {
        org.springframework.core.io.Resource resource =
                resourceLoader.getResource("classpath:prompts/system-prompt.md");
        if (!resource.exists()) {
            throw new IllegalStateException("缺少系统提示词文件 classpath:prompts/system-prompt.md");
        }
        try {
            this.systemPrompt = stripLeadingHtmlComment(
                    resource.getContentAsString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new IllegalStateException("读取系统提示词失败: " + e.getMessage(), e);
        }
    }

    /**
     * 去掉模板开头的 HTML 注释块。
     *
     * @param text 模板原文
     * @return 从第一个非注释内容开始的提示词；没有注释时原样返回
     */
    private static String stripLeadingHtmlComment(String text) {
        String content = text.stripLeading();
        if (!content.startsWith("<!--")) {
            return content;
        }
        int end = content.indexOf("-->");
        // 注释没有闭合时保持原文，宁可多一段说明也不要把整份提示词吞掉
        return end < 0 ? content : content.substring(end + 3).stripLeading();
    }

    /**
     * 发起一次流式对话。
     *
     * @param request 已补齐默认值的对话请求
     * @return SSE 发射器；调用方负责把它返回给 Spring MVC
     */
    @Override
    public SseEmitter stream(ChatDtos.ChatRequest request) {

        // 1) 归一化参数（mode/docTopK/maxIterations 的默认值在这个方法里已经补过）
        ChatDtos.ChatRequest normalized = request.withDefaults();

        // 2) 会话 id：首轮由后端生成，通过 done 事件回传前端
        String sessionId = (normalized.sessionId() == null || normalized.sessionId().isBlank())
                ? cn.hutool.core.util.IdUtil.fastSimpleUUID()
                : normalized.sessionId();

        // 3) 建流并立刻绑定到总线：之后所有事件都往这条流写
        SseEmitter emitter = new SseEmitter(300_000L);
        SseAgentEventSink sink = new SseAgentEventSink(emitter);
        sessionBus.bind(sessionId, sink);

        // 4) 提前准备本轮记录器（也可以放进总线，这里用一个 Map 挂在 bus 里更省事）
        TurnRecorder recorder = sessionBus.recorderOf(sessionId);

        // 5) 把执行挪到独立线程：本方法必须立刻返回 emitter
        chatTurnExecutor.submit(() -> runTurn(sessionId, normalized, recorder));


        // 6) 前端主动断开时清理绑定，避免向已关闭的流写数据
        emitter.onCompletion(() -> sessionBus.detachQuietly(sessionId));
        emitter.onTimeout(() -> sessionBus.detachQuietly(sessionId));
        emitter.onError(ex -> sessionBus.detachQuietly(sessionId));
        return emitter;
    }



    /**
     * 真正执行一轮对话：装配模型、跑工具循环、发事件、落库。
     *
     * <p>本方法运行在 chatTurnExecutor 线程上，允许长时间阻塞（包括等待用户确认）。</p>
     *
     * @param sessionId 会话 id
     * @param request   归一化后的请求
     * @param recorder  本轮记录器
     */
    private void runTurn(String sessionId, ChatDtos.ChatRequest request, TurnRecorder recorder) {
        long startedAt = System.currentTimeMillis();
        // 本轮轮次 id：轨迹落库用它把同一轮的事件串起来
        String turnId = cn.hutool.core.util.IdUtil.fastSimpleUUID();
        traceEventSink.setTurnId(turnId);

        try {
            // 1) thinking：让用户立刻看到「我在动」，而不是盯着空屏幕
            sessionBus.emit(sessionId, chatEvents.thinking(sessionId, "start", 0, 0, "正在准备对话…"));

            // 2) 读历史并补种上下文（第一版可以只读条数，不真的补进模型）
            List<ChatMessage> history = chatMessageRepository.findBySessionIdOrderByIdAsc(sessionId);
            sessionBus.emit(sessionId, chatEvents.thinking(sessionId, "history",
                    System.currentTimeMillis() - startedAt, history.size(),
                    "已载入 " + history.size() + " 条历史消息"));

            // 3) 落用户消息（先落库，避免崩溃时丢失用户输入）
            persistMessage(sessionId, "user", request.message(), turnId);

            // 4) 建模型（供应商/模型名/密钥都在 buildModelSpec 里，已有实现不用动）
            LlmModelSpec spec = buildModelSpec();
            StreamingChatModel chatModel = llmModelFactoryRouter.createStreamingModel(spec);
            recorder.setModel(spec.model());

            // 5) 组装工具表：每个工具包一层 ChatToolExecutor，事件就有了
            Map<ToolSpecification, ToolExecutor> tools = buildEventedToolMap(sessionId, recorder);

            // 6) 建 AiServices：这里是「自动工具循环」——模型要工具就自动执行再回来
            Assistant assistant = AiServices.builder(Assistant.class)
                    .streamingChatModel(chatModel)
                    .systemMessage(systemPrompt)
                    .tools(tools)
                    .maxToolCallingRoundTrips(request.maxIterations())
                    .build();

            sessionBus.emit(sessionId, chatEvents.thinking(sessionId, "model",
                    System.currentTimeMillis() - startedAt, history.size(), "正在请求模型…"));

            // 7) 跑起来。start() 是阻塞的，直到整轮结束（含所有工具调用）
            assistant.chat(request.message())
                    .onPartialResponse(partial -> {
                        // 用户点了停止：不再转发增量，但模型那边没法取消，让它自己跑完
                        if (recorder.isStopped()) {
                            return;
                        }
                        recorder.appendAnswer(partial);
                        sessionBus.emit(sessionId, chatEvents.token(partial));
                    })
                    .onCompleteResponse(response -> {
                        // 模型侧结束：把用量记下来，真正的 done 在 finally 里统一发
                        TokenUsage usage = response.tokenUsage();
                        if (usage != null) {
                            recorder.setUsage(Map.of(
                                    "input_tokens", usage.inputTokenCount() == null ? 0 : usage.inputTokenCount(),
                                    "output_tokens", usage.outputTokenCount() == null ? 0 : usage.outputTokenCount(),
                                    "total_tokens", usage.totalTokenCount() == null ? 0 : usage.totalTokenCount(),
                                    "cost", 0.0));
                        }
                    })
                    .onError(error -> sessionBus.emit(sessionId,
                            chatEvents.error("模型调用失败：" + error.getMessage(),
                                    request.debug() ? stackOf(error) : null)))
                    .start();

        } catch (RuntimeException ex) {
            // 任何未预料异常都要变成 error 事件，否则前端只能干等到超时
            sessionBus.emit(sessionId, chatEvents.error(
                    "本轮对话失败：" + ex.getMessage(), request.debug() ? stackOf(ex) : null));
        } finally {
            // 8) 落助手消息 + 发 done + 关流。无论成功失败都要走到这里
            finishTurn(sessionId, request, recorder, turnId);
        }
    }


    /**
     * 收尾：落库、发 done（或 stopped）、关流、清理总线状态。
     *
     * @param sessionId 会话 id
     * @param request   请求
     * @param recorder  本轮记录器
     * @param turnId    轮次 id
     */
    private void finishTurn(String sessionId, ChatDtos.ChatRequest request, TurnRecorder recorder, String turnId) {
        String answer = recorder.answer();
        try {
            // 1) 助手消息落库（工具轨迹也一起存，历史回放要用）
            if (!answer.isBlank()) {
                persistMessage(sessionId, "assistant", answer, turnId);
            }
            // 2) 更新会话的 updated_at 与标题（首轮用第一句话当标题）
            touchSession(sessionId, request.message());
        } catch (RuntimeException ex) {
            // 落库失败不影响用户看到答案：只记日志
            log.warn("会话落库失败 sessionId={}", sessionId, ex);
        }

        // 3) 用户点了停止 → 发 stopped；否则发 done
        if (recorder.isStopped()) {
            sessionBus.emit(sessionId, chatEvents.stopped(sessionId, answer, "user_stop"));
        } else {
            sessionBus.emit(sessionId, chatEvents.done(
                    sessionId,
                    answer,
                    recorder.elapsedMs(),
                    recorder.toolCalls(),
                    countMessages(sessionId),
                    recorder.files(),
                    recorder.usage(),
                    recorder.steerCount(),
                    recorder.model()));
        }
        // 4) 关流并清理：前端收到 done 后会把 loading 关掉
        sessionBus.finish(sessionId);
        // 5) 清掉本线程的轮次 id：线程池复用线程，不清会把下一轮的轨迹记到本轮名下
        traceEventSink.clearTurnId();
    }



    /**
     * 组装工具表：每个工具包一层带事件的执行器。
     *
     * <p>与原来的 buildToolMap 唯一区别：执行器从 lambda 换成了 {@link ChatToolExecutor}，
     * 于是 tool_start / tool_end 事件自动就有了。</p>
     *
     * @param sessionId 会话 id
     * @param recorder  本轮记录器
     * @return ToolSpecification → ToolExecutor 的映射
     */
    private Map<ToolSpecification, ToolExecutor> buildEventedToolMap(String sessionId, TurnRecorder recorder) {
        Map<ToolSpecification, ToolExecutor> map = new LinkedHashMap<>();
        String permissionMode = readPermissionMode();
        for (AgentTool tool : toolRegistry.listForScope(false)) {
            ToolSpecification spec = ToolSpecification.builder()
                    .name(tool.name())
                    .description(tool.description())
                    .parameters(OPEN_PARAMETERS)
                    .build();
            // 包一层：执行前后发事件，并累积轨迹
            ToolExecutor executor = new ChatToolExecutor(
                    tool, sessionId, recorder, sessionBus, outputContract, chatEvents, permissionMode);
            map.put(spec, executor);
        }
        return map;
    }

    /**
     * 执行一次模型发起的工具调用。
     *
     * <p>这里必须自己设置 {@link ToolSession}：AiServices 的工具回调可能运行在模型 SDK
     * 的回调线程上，而不是 HTTP 请求线程，所以不能依赖 {@code stream()} 里的 ThreadLocal。</p>
     *
     * @param tool           被调用的工具
     * @param request        模型给出的工具调用请求（含 JSON 参数）
     * @param sessionId      会话 id
     * @param permissionMode 权限模式：ask / workspace / allow
     * @return 工具结果文本（ToolResult 已带 OK: / FAIL: 前缀）
     */
    private String executeTool(AgentTool tool, ToolExecutionRequest request,
                               String sessionId, String permissionMode) {
        Map<String, Object> arguments;
        try {
            String json = request.arguments();
            // 模型有时会省略参数，此时按空对象处理，让工具自己给出「缺少哪个参数」
            arguments = StrUtil.isBlank(json)
                    ? Map.of()
                    : JsonUtils.parse(json, new TypeReference<Map<String, Object>>() { });
        } catch (RuntimeException e) {
            // 参数不合法属于模型可自行修正的错误：回 FAIL 让它重试，不要打断整轮对话
            return ToolResult.fail(tool.name() + " 参数不是合法 JSON 对象: " + e.getMessage()).content();
        }

        ToolSession.setContext(new SessionContext(
                sessionId,
                // 工作区白名单沿用全局配置；本会话没有额外限制
                PathPolicy.workspaceRoots(),
                // 本会话没有显式禁用的工具
                Set.of(),
                // 本会话没有额外放行的命令前缀
                Set.of(),
                // 工作区 id 尚未落地，保留空串
                "",
                permissionMode,
                ToolSession.SCOPE_MAIN));
        try {
            // ToolRuntime 已把工具内部异常转成 FAIL；这里再兜一层，避免异常冒到框架回调
            return tool.execute(arguments).content();
        } catch (RuntimeException e) {
            return ToolResult.fail(tool.name() + " 执行失败: " + e.getMessage()).content();
        } finally {
            // 线程池会复用线程：不清理会让下一个会话读到本次的 session/权限
            ToolSession.clear();
        }
    }

    /**
     * 读取权限模式设置。
     *
     * @return ask / workspace / allow；读不到或为空时返回最严格的 ask
     */
    private String readPermissionMode() {
        try {
            Object value = settingsRegistry.getSetting("permission.mode");
            return value == null || StrUtil.isBlank(String.valueOf(value))
                    ? "ask"
                    : String.valueOf(value);
        } catch (RuntimeException e) {
            // 读配置失败时按最严格的 ask 处理：宁可多问一次，也不能默认放行
            return "ask";
        }
    }

    /**
     * 按当前设置装配一个流式模型所需的参数。
     *
     * <p>取值顺序与 Python 侧 {@code app/llm/factory.py} 对齐：</p>
     * <ul>
     *   <li>供应商 / 模型名 / 温度 / 输出上限：来自设置注册表，注册表已保证类型与范围合法；</li>
     *   <li>API Key：来自加密的密钥仓库，密钥名由供应商声明决定；</li>
     *   <li>接口地址：优先用设置里的 {@code llm.base_url}（允许走代理或中转站），
     *       留空才回落到供应商官方地址。</li>
     * </ul>
     *
     * @return 可直接交给工厂路由创建模型的参数
     * @throws ApiException 供应商未知（404）、供应商没有模型（404）、需要密钥但未配置（400）
     */
    private LlmModelSpec buildModelSpec() {
        // 注册表对这两个键的声明都是字符串类型，读不到时也会给默认值，因此不会为 null
        String providerId = (String) settingsRegistry.getSetting("llm.provider");
        String modelName = ((String) settingsRegistry.getSetting("llm.model")).trim();

        // 供应商决定默认地址、密钥名以及是否必须配置密钥
        LlmDtos.ProviderInfo provider = llmProviderRegistry.findProvider(providerId)
                .orElseThrow(() -> new ApiException(404, "未知的模型供应商：" + providerId));

        if (modelName.isEmpty()) {
            // 设置里没写模型名：用该供应商清单的第一个作为默认模型，与 Python 侧一致。
            // 注意：这里不调用 resolveModel()，因为设置允许手写清单外的新模型名，
            // 强制精确匹配会让「新模型不等代码更新」的约定失效。
            if (provider.models().isEmpty()) {
                throw new ApiException(404, "供应商 " + providerId + " 还没有配置任何模型");
            }
            modelName = provider.models().get(0).model();
        }

        // 密钥：Ollama 等本地供应商的 secretKey 为空，此时 apiKey 保持 null
        String apiKey = null;
        if (!StrUtil.isBlank(provider.secretKey())) {
            apiKey = secretStore.getSecret(provider.secretKey()).orElse(null);
        }
        if (provider.requiresKey() && StrUtil.isBlank(apiKey)) {
            // 提前给出「去设置页填哪一项」的提示，避免底层 SDK 抛难懂的 401
            throw new ApiException(400, "尚未配置 " + provider.label() + " 的 API 密钥，"
                    + "请到设置页的「模型」分区填写（对应设置项：" + provider.secretKey() + "）");
        }

        // 接口地址：
        //   - 自定义端点：必须用它自己的 base_url（用户就是冲着这个地址来的，不能被全局配置覆盖）
        //   - 内置供应商：保持「全局配置优先」，允许走代理/中转站
        String configuredBaseUrl = (String) settingsRegistry.getSetting("llm.base_url");
        String baseUrl;
        if (provider.isCustom()) {
            baseUrl = provider.baseUrl();
        } else {
            baseUrl = StrUtil.isBlank(configuredBaseUrl) ? provider.baseUrl() : configuredBaseUrl.trim();
        }

        // 温度在注册表里声明为 FLOAT，值已保证落在 0.0~2.0
        Double temperature = ((Number) settingsRegistry.getSetting("llm.temperature")).doubleValue();
        // 单轮输出上限声明为 INT；0 表示「不传」，交给供应商使用自己的默认值
        int configuredMaxTokens = ((Number) settingsRegistry.getSetting("llm.max_tokens")).intValue();
        Integer maxTokens = configuredMaxTokens > 0 ? configuredMaxTokens : null;

        return new LlmModelSpec(providerId, modelName, apiKey, baseUrl, temperature, maxTokens);
    }


    // 落用户消息
    private void persistMessage(String sessionId, String role, String content, String turnId) {
        chatPersistence.saveMessage(sessionId, role, content, "agent", null, null, null);
    }
    private void touchSession(String sessionId, String firstMessage) {
        chatPersistence.touchSession(sessionId, firstMessage);
    }
    private int countMessages(String sessionId) {
        return chatPersistence.countMessages(sessionId);
    }

    /**
     * 把异常转成字符串，只在 debug=true 时放进 error 事件的 detail 字段。
     *
     * <p>为什么不直接 ex.toString()：用户要的是「哪一行炸的」，只有堆栈能回答。</p>
     *
     * @param ex 异常
     * @return 完整堆栈文本
     */
    private String stackOf(Throwable ex) {
        StringWriter writer = new StringWriter();
        ex.printStackTrace(new PrintWriter(writer));
        return writer.toString();
    }

    /**
     * 把一段文本压成一行预览（标题/列表摘要用）。
     *
     * @param text 原始文本
     * @return 单行、最多 20 字
     */
    private String oneLinePreview(String text) {
        if (text == null) {
            return "";
        }
        String oneLine = text.replaceAll("\\s+", " ").strip();
        return oneLine.length() <= 20 ? oneLine : oneLine.substring(0, 20) + "…";
    }

    /**
     * 用户对确认弹窗做出决定后，恢复被挂起的那一轮。
     *
     * <p>本方法做三件事，顺序不能错：</p>
     * <ol>
     *   <li>把新的 SSE 流插到总线上（这样线程醒来后有地方写）；</li>
     *   <li>兑现挂起的 Future（线程解除阻塞）；</li>
     *   <li>返回新 emitter。</li>
     * </ol>
     *
     * @param request 恢复请求：session_id / interrupt_id / approved / remember
     * @return 新的 SSE 流
     */
    @Override
    public SseEmitter resume(ChatDtos.ChatResumeRequest request) {
        SseEmitter emitter = new SseEmitter(300_000L);
        SseAgentEventSink sink = new SseAgentEventSink(emitter);

        // 1) 先绑新流：必须赶在线程醒来之前，否则线程醒来那一瞬间的输出会丢
        sessionBus.bind(request.sessionId(), sink);

        // 2) 兑现决定。remember=true 时把「本工作区以后都同意」记下来（见 4.1.1）
        ToolApprovalGateway.ApprovalResult result = new ToolApprovalGateway.ApprovalResult(request.approved(), request.remember());
        boolean matched = sessionBus.answer(request.sessionId(), request.interruptId(), result);
        if (!matched) {
            // 没有匹配的等待：可能是超时了、或用户点了过期弹窗。
            // 直接发一条 error 并关流，比返回 500 更友好（前端会显示消息而不是崩掉）。
            sink.emit(chatEvents.error("这次确认已经失效（可能超时或已在别处处理），请重新发起对话。", null));
            sink.close();
            return emitter;
        }

        emitter.onCompletion(() -> sessionBus.detachQuietly(request.sessionId()));
        emitter.onTimeout(() -> sessionBus.detachQuietly(request.sessionId()));
        emitter.onError(ex -> sessionBus.detachQuietly(request.sessionId()));
        return emitter;
    }

    /**
     * 停止当前会话正在跑的一轮。
     *
     * <p>限制说明：LangChain4j 1.22 的 {@code TokenStream} <b>没有 cancel() 方法</b>
     * （我 javap 查过，只有 start/onPartialResponse/onCompleteResponse/onError 等）。
     * 所以「停止」是「温柔中断」：不再往前提转发增量、把等待中的确认按拒绝兑现、
     * 立刻发 stopped 并关流；模型侧那条 HTTP 流会在后台自己跑完，我们不再理会。</p>
     *
     * @param request 停止请求
     * @return 是否叫停成功
     */
    @Override
    public ChatDtos.ChatStopResult stop(ChatDtos.ChatStopRequest request) {
        String sessionId = request.sessionId();
        // 先问总线「确实有一轮在跑吗」：没有就直接回 false，别顺手建一个空状态出来
        boolean running = sessionBus.requestStop(sessionId);
        if (running) {
            TurnRecorder recorder = sessionBus.recorderOf(sessionId);
            recorder.markStopped();
            // 立刻给用户反馈：不要等他下一次看到 token
            sessionBus.emit(sessionId, chatEvents.stopped(sessionId, recorder.answer(), "user_stop"));
            // 关流：前端 loading 结束
            sessionBus.finish(sessionId);
        }
        return new ChatDtos.ChatStopResult(running, sessionId);
    }

    /**
     * 执行中插话：入队，等下一个工具边界注入。
     *
     * @param sessionId 会话 id
     * @param request   插话内容
     * @return 回执（前端拿 steer_id 对账）
     */
    @Override
    public ChatDtos.ChatSteerResult steer(String sessionId, ChatDtos.ChatSteerRequest request) {
        String steerId = steeringQueue.offer(sessionId, request.content());
        return new ChatDtos.ChatSteerResult(sessionId, steerId, request.content(), true,
                steeringQueue.pending(sessionId));
    }

    /**
     * 登记取消：下一个（或指定名的）工具不再执行。
     *
     * @param sessionId 会话 id
     * @param request   要取消的工具名；空串表示下一个工具
     * @return 回执
     */
    @Override
    public ChatDtos.ChatToolCancelResult cancelTool(String sessionId, ChatDtos.ChatToolCancelRequest request) {
        String tool = request.withDefaults().tool();
        toolCancelRegistry.register(sessionId, tool);
        return new ChatDtos.ChatToolCancelResult(sessionId, true, tool);
    }
    /**
     * 最近会话列表。
     *
     * @param limit    最多返回几条
     * @param query    标题模糊搜索；空串表示不过滤
     * @param archived 是否包含已归档
     * @return 会话列表
     */
    @Override
    public ChatDtos.ChatSessionList listSessions(int limit, String query, boolean archived) {
        // 上限由 controller 的 @Max 拦过，这里再夹一次是给「内部直接调用」兜底
        int safeLimit = PageLimits.clamp(limit, PageLimits.MAX_CHAT_SESSIONS);
        List<ChatSession> rows = chatPersistence.persistedSessions(archived);
        List<ChatDtos.ChatSessionInfo> items = new ArrayList<>();
        for (ChatSession row : rows) {
            // 标题过滤：空 query 不过滤
            if (query != null && !query.isBlank() && !row.getTitle().contains(query)) {
                continue;
            }
            List<ChatMessage> messages = chatPersistence.findMessages(row.getId());
            String preview = messages.isEmpty() ? "" : oneLinePreview(messages.get(messages.size() - 1).getContent());
            items.add(new ChatDtos.ChatSessionInfo(
                    row.getId(), row.getTitle(), "agent", messages.size(),
                    row.getCreatedAt(), row.getUpdatedAt(), preview,
                    Boolean.TRUE.equals(row.getPinned()), Boolean.TRUE.equals(row.getArchived())));
            if (items.size() >= safeLimit) {
                break;
            }
        }
        return new ChatDtos.ChatSessionList(items);
    }

    /**
     * 读取某个会话的历史消息。
     *
     * @param sessionId 会话 id
     * @param limit     最多返回多少条
     * @return 历史消息
     */
    @Override
    public ChatDtos.ChatHistory history(String sessionId, int limit) {
        // 上限由 controller 的 @Max 拦过，这里再夹一次是给「内部直接调用」兜底
        int safeLimit = PageLimits.clamp(limit, PageLimits.MAX_CHAT_HISTORY);
        // 多取一条：多出来的那条只用来判断「还有没有更早的」，省掉一次 COUNT 查询
        List<ChatMessage> rows = chatPersistence.findRecentMessages(sessionId, safeLimit + 1);
        boolean hasMore = rows.size() > safeLimit;
        // 按升序返回，多出来的那条是最早的，正好丢掉：剩下的就是最近 safeLimit 条
        if (hasMore) {
            rows = rows.subList(rows.size() - safeLimit, rows.size());
        }

        List<ChatDtos.StoredChatMessage> messages = rows.stream()
                .map(this::toStoredMessage).collect(Collectors.toList());

        return new ChatDtos.ChatHistory(sessionId, messages, hasMore);
    }

    /**
     * 修改会话标题/置顶/归档。
     *
     * @param sessionId 会话 id
     * @param patch     要修改的字段
     * @return 落库后的标记
     */
    @Override
    public ChatDtos.ChatSessionPatchResult patchSession(String sessionId, ChatDtos.ChatSessionPatch patch) {
        ChatSession row = chatPersistence.findSession(sessionId).orElse(null);
        // 会话不存在：回全空，前端据此提示「会话已不在」
        if (row == null) {
            return new ChatDtos.ChatSessionPatchResult(false, sessionId, "", false, false);
        }
        boolean renamed = false;
        // 只有传了非空标题、且与旧标题不同才算「真的改名」
        if (patch.title() != null && !patch.title().isBlank() && !patch.title().equals(row.getTitle())) {
            row.setTitle(patch.title());
            renamed = true;
        }
        // 置顶/归档用包装类型 Boolean，null 表示「没传、不改」
        if (patch.pinned() != null) {
            row.setPinned(patch.pinned());
        }
        if (patch.archived() != null) {
            row.setArchived(patch.archived());
        }
        chatSessionRepository.save(row);
        return new ChatDtos.ChatSessionPatchResult(
                renamed, sessionId, row.getTitle(),
                Boolean.TRUE.equals(row.getPinned()), Boolean.TRUE.equals(row.getArchived()));
    }

    /**
     * 导出会话内容；md 给人读，json 给再加工。
     *
     * @param sessionId 会话 id
     * @param format    md 或 json（不区分大小写）；其它值回落到 md
     * @return 导出结果（含建议文件名与全文）
     */
    @Override
    public ChatDtos.ExportedSession export(String sessionId, String format) {
        List<ChatMessage> rows = chatPersistence.findMessages(sessionId);
        String fmt = "json".equalsIgnoreCase(format) ? "json" : "md";
        String content;
        if ("json".equals(fmt)) {
            // JSON 导出：直接序列化还原后的消息结构，方便程序再加工
            try {
                content = objectMapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(rows.stream().map(this::toStoredMessage).toList());
            } catch (Exception e) {
                throw new ApiException(500, "序列化会话失败：" + e.getMessage());
            }
        } else {
            // Markdown 导出：标题 + 每条消息，适合人阅读
            StringBuilder sb = new StringBuilder();
            sb.append("# ").append(sessionTitle(sessionId)).append("\n\n");
            for (ChatMessage row : rows) {
                sb.append("## ").append("user".equals(row.getRole()) ? "用户" : "助手").append("\n\n");
                sb.append(row.getContent()).append("\n\n");
            }
            content = sb.toString();
        }
        return new ChatDtos.ExportedSession(sessionId, fmt, "chat-" + sessionId + "." + fmt, content, rows.size());
    }
    /**
     * 读取会话级用量汇总：总 token、总费用，并按模型拆分。
     *
     * <p>数据来源是助手消息上的四个用量列；用户消息与 doc 模式里未调用模型的轮次不计入 token，
     * 但轮次数仍然按助手消息条数统计（与旧行为保持一致）。</p>
     *
     * @param sessionId 会话 id
     * @return 用量汇总
     */
    @Override
    public ChatDtos.SessionUsage usage(String sessionId) {
        List<ChatMessage> rows = chatPersistence.findMessages(sessionId);
        // 按模型聚合：LinkedHashMap 保留「第一次出现」的顺序，面板看起来更稳定
        Map<String, ModelAccumulator> byModel = new LinkedHashMap<>();
        long turns = 0L;
        long inputTotal = 0L;
        long outputTotal = 0L;
        double costTotal = 0.0;

        for (ChatMessage row : rows) {
            // 只有助手消息带用量；用户消息直接跳过
            if (!"assistant".equals(row.getRole())) {
                continue;
            }
            turns++;
            long input = row.getInputTokens() == null ? 0L : row.getInputTokens();
            long output = row.getOutputTokens() == null ? 0L : row.getOutputTokens();
            double cost = row.getCost() == null ? 0.0 : row.getCost();

            inputTotal += input;
            outputTotal += output;
            costTotal += cost;

            // 早期数据 / doc 模式没有模型名：归到 unknown，前端照样能展示
            String model = (row.getModel() == null || row.getModel().isBlank())
                    ? "unknown"
                    : row.getModel();
            byModel.computeIfAbsent(model, ignored -> new ModelAccumulator()).add(input + output, cost);
        }

        List<ChatDtos.ModelUsage> perModel = new ArrayList<>(byModel.size());
        for (Map.Entry<String, ModelAccumulator> entry : byModel.entrySet()) {
            ModelAccumulator accumulator = entry.getValue();
            perModel.add(new ChatDtos.ModelUsage(
                    entry.getKey(), accumulator.turns, accumulator.tokens, round4(accumulator.cost)));
        }

        return new ChatDtos.SessionUsage(
                sessionId,
                turns,
                inputTotal,
                outputTotal,
                inputTotal + outputTotal,
                round4(costTotal),
                "CNY",
                perModel);
    }

    /**
     * 永久删除某个会话及其消息。
     *  <p>顺序：先删消息、再删会话；最后清掉运行时状态，避免侧边栏还显示「运行中」。</p>
     * @param sessionId 会话 id
     * @return 删除结果
     */
    @Override
    public ChatDtos.DeleteSessionResult deleteHistory(String sessionId) {
        boolean existed = chatPersistence.findSession(sessionId).isPresent();
        // 仓库没有按会话删除的派生方法，就把消息查出来整体删（会话级消息量不大，够用）
        List<ChatMessage> rows = chatMessageRepository.findBySessionIdOrderByIdAsc(sessionId);
        if (!rows.isEmpty()) {
            chatMessageRepository.deleteAll(rows);
        }
        if (existed) {
            chatSessionRepository.deleteById(sessionId);
        }
        // 清运行时状态（总线里的 Turn），让「已删会话」不再出现在运行态里
        sessionBus.finish(sessionId);
        return new ChatDtos.DeleteSessionResult(existed, sessionId);
    }

    /**
     * 查询会话运行时状态。
     *
     * @param sessionId 会话 id
     * @return 运行时状态
     */
    @Override
    public ChatDtos.SessionInfo sessionInfo(String sessionId) {
        ChatSession row = chatPersistence.findSession(sessionId).orElse(null);
        if (row == null) {
            // 不存在的会话：exists=false，其余字段一律 null
            return new ChatDtos.SessionInfo(false, sessionId, null, null, null, false);
        }
        return new ChatDtos.SessionInfo(
                true,
                sessionId,
                chatPersistence.countMessages(sessionId),
                parseEpochSeconds(row.getCreatedAt()),
                parseEpochSeconds(row.getUpdatedAt()),
                sessionBus.isRunning(sessionId));
    }

    /**
     * 清空会话上下文：只删消息、保留会话行（区别于 deleteHistory 的「连会话一起删」）。
     *
     * @param sessionId 会话 id
     * @return 清空结果
     */
    @Override
    public ChatDtos.ClearSessionResult clearSession(String sessionId) {
        boolean existed = chatPersistence.findSession(sessionId).isPresent();
        List<ChatMessage> rows = chatMessageRepository.findBySessionIdOrderByIdAsc(sessionId);
        if (!rows.isEmpty()) {
            chatMessageRepository.deleteAll(rows);
        }
        // 清掉运行时状态与检查点，让下一轮从干净状态开始
        sessionBus.finish(sessionId);
        return new ChatDtos.ClearSessionResult(existed, sessionId);
    }

    /**
     * 按续读标记读取工具的完整输出。
     *
     * <p>续读标记由 OutputContract 在截断时生成；过期/被清理后 readContinuation 返回 null。</p>
     *
     * @param ref 续读标记
     * @return 完整输出
     */
    @Override
    public ChatDtos.ToolOutputPayload toolOutput(String ref) {
        String content = outputContract.readContinuation(ref);
        boolean found = content != null;
        return new ChatDtos.ToolOutputPayload(
                ref == null ? "" : ref,
                found,
                found ? content : "",
                found ? content.length() : 0L);
    }

    /**
     * 返回对话事件协议说明，对应 GET /chat/events。
     *
     * @return 事件协议字典
     */
    @Override
    public Map<String, Object> events() {
        // 手写一份静态说明即可，不需要反射：这份清单本来就是给人看的
        return Map.of(
                "thinking", Map.of("desc", "思考/准备阶段提示", "fields", List.of("stage", "delay", "session_id", "history_len", "text")),
                "token", Map.of("desc", "模型增量文本", "fields", List.of("text")),
                "tool_start", Map.of("desc", "工具开始执行", "fields", List.of("name", "input")),
                "tool_end", Map.of("desc", "工具执行结束", "fields", List.of("name", "output", "total_chars", "truncated", "continuation_ref")),
                "confirm_required", Map.of("desc", "需要用户确认（发完即关流）", "fields", List.of("session_id", "interrupt_id", "tool", "title", "message", "args", "can_remember")),
                "stopped", Map.of("desc", "用户停止", "fields", List.of("session_id", "answer", "reason")),
                "done", Map.of("desc", "一轮结束", "fields", List.of("session_id", "answer", "elapsed", "tool_calls", "history_len", "files", "usage", "steer_count", "model")),
                "error", Map.of("desc", "出错", "fields", List.of("message", "detail")),
                "steer_injected", Map.of("desc", "插话已注入", "fields", List.of("session_id", "steer_id")),
                "budget_exceeded", Map.of("desc", "预算超限", "fields", List.of("session_id", "interrupt_id", "dimension", "current", "limit", "message")));
    }

    /**
     * 把一条落库消息还原成接口要的结构；tool_calls 是 JSON 字符串，这里解析成对象列表。
     *
     * <p>解析失败时按「无轨迹」处理，绝不让一条脏数据打断整个历史回放。</p>
     *
     * @param row 消息实体
     * @return 接口消息结构
     */
    private ChatDtos.StoredChatMessage toStoredMessage(ChatMessage row) {
        List<ChatDtos.ToolCallTrace> toolCalls = null;
        // tool_calls 只在助手消息里有值；用户消息是 null，直接跳过解析
        if (row.getToolCalls() != null && !row.getToolCalls().isBlank()) {
            try {
                toolCalls = objectMapper.readValue(row.getToolCalls(),
                        new TypeReference<List<ChatDtos.ToolCallTrace>>() { });
            } catch (Exception e) {
                // 历史里若存过旧格式，解析不动就丢弃轨迹，不影响正文回放
                toolCalls = null;
            }
        }
        return new ChatDtos.StoredChatMessage(
                row.getId() == null ? 0L : row.getId(),
                row.getRole(),
                row.getContent(),
                row.getMode(),
                toolCalls,
                row.getFinishReason(),
                row.getElapsed(),
                row.getCreatedAt());
    }

    /**
     * 把 ISO-8601 时间字符串转成 Unix 秒（浮点）。
     *
     * <p>SessionInfo 的 created_at / last_active 是「秒」；格式对不上时回 null，前端按「未知」展示。</p>
     *
     * @param iso 形如 2026-10-27T16:30:00 的字符串
     * @return Unix 秒；无法解析时为 null
     */
    private Double parseEpochSeconds(String iso) {
        if (iso == null || iso.isBlank()) {
            return null;
        }
        try {
            return Instant.parse(iso).toEpochMilli() / 1000.0;
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 取会话标题，导出 Markdown 的标题行用。
     *
     * @param sessionId 会话 id
     * @return 标题；会话不存在时回「会话」
     */
    private String sessionTitle(String sessionId) {
        return chatSessionRepository.findById(sessionId)
                .map(ChatSession::getTitle)
                .orElse("会话");
    }


    /**
     * 按模型聚合用量的小累加器（只在本类的 {@code usage()} 里使用）。
     */
    private static final class ModelAccumulator {

        /** 该模型的助手消息条数（= 轮次）。 */
        private long turns;

        /** 该模型累计 token（input + output）。 */
        private long tokens;

        /** 该模型累计费用（元）。 */
        private double cost;

        /**
         * 累加一轮。
         *
         * @param turnTokens 本轮 token（input + output）
         * @param turnCost   本轮费用（元）
         */
        void add(long turnTokens, double turnCost) {
            turns++;
            tokens += turnTokens;
            cost += turnCost;
        }
    }

    /**
     * 保留四位小数，避免浮点误差在用量面板里显示成 0.30000000000000004。
     *
     * @param value 原始值
     * @return 四舍五入到四位小数
     */
    private static double round4(double value) {
        return Math.round(value * 10_000.0) / 10_000.0;
    }
}
