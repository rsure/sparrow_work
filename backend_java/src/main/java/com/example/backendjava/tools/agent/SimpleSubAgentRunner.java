// 模块说明：子 agent 运行器的最小实现——用只读工具跑一轮同步工具循环，只把结论交回主对话。
//
// 为什么用「同步 ChatModel + AiServices」而不是 LangGraph 子图：
// 子 agent 的任务形态是「读几个地方 → 给一段结论」，没有中断、确认、计划更新这些需求；
// 用同步模型可以把实现压到一百行以内，也避免为了一个可选能力把主链路重构一遍。
package com.example.backendjava.tools.agent;

// 项目内：业务异常（模型配置缺失时给出可读提示）
import com.example.backendjava.common.ApiException;
// 项目内：供应商/模型描述（取默认模型、单价）
import com.example.backendjava.dto.LlmDtos;
// 项目内：装配一个模型所需的参数
import com.example.backendjava.dto.LlmModelSpec;
// 项目内：工具执行结果（失败时拼 FAIL: 文本回给模型）
import com.example.backendjava.dto.ToolResult;
// 项目内：模型工厂路由（按供应商创建同步模型）
import com.example.backendjava.llm.LlmModelFactoryRouter;
// 项目内：供应商与模型清单
import com.example.backendjava.llm.LlmProviderRegistry;
// 项目内：单项工具能力接口
import com.example.backendjava.service.AgentTool;
// 项目内：工具注册表（只读工具清单从这里取）
import com.example.backendjava.service.ToolRegistry;
// 项目内：密钥仓库（取当前供应商的 API Key）
import com.example.backendjava.settings.SecretStore;
// 项目内：设置注册表（模型名/地址/温度/权限模式）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：路径策略（工作区白名单）
import com.example.backendjava.tools.PathPolicy;
// 项目内：会话级权限上下文
import com.example.backendjava.tools.SessionContext;
// 项目内：把工具声明的参数字段翻译成模型库的 JSON Schema（主对话与子 Agent 共用一份逻辑）
import com.example.backendjava.tools.ToolSchemaMapper;
// 项目内：线程本地的会话上下文
import com.example.backendjava.tools.ToolSession;
// 项目内：JSON 工具（解析工具参数）
import com.example.backendjava.util.JsonUtils;

// Hutool：判断字符串是否空白（模型可能不传 context）
import cn.hutool.core.util.StrUtil;
// Hutool：生成短随机串，拼出唯一的子会话 id
import cn.hutool.core.util.IdUtil;
// Jackson：把工具参数 JSON 解析成 Map
import com.fasterxml.jackson.core.type.TypeReference;
// LangChain4j：模型给出的工具调用请求
import dev.langchain4j.agent.tool.ToolExecutionRequest;
// LangChain4j：工具规格（告诉模型有哪些工具）
import dev.langchain4j.agent.tool.ToolSpecification;
// LangChain4j：同步聊天模型
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j：助手工厂（把模型 + 工具 + 系统提示词组装成代理）
import dev.langchain4j.service.AiServices;
// LangChain4j：工具执行器（框架回调它，本项目再转给 AgentTool）
import dev.langchain4j.service.tool.ToolExecutor;

// Lombok：日志
import lombok.extern.slf4j.Slf4j;
// Spring：注册成 SubAgentRunner 的实现
import org.springframework.stereotype.Component;

// 标准库：LinkedHashMap 保持工具注入顺序，便于排查
import java.util.LinkedHashMap;
// 标准库：List 工具清单
import java.util.List;
// 标准库：Map 工具表与工具参数
import java.util.Map;
// 标准库：Set 构造「没有额外禁用/放行」的空集合
import java.util.Set;

/**
 * 子 agent 运行器的最小实现。
 *
 * <p><b>能力边界：</b>只给只读工具（{@code ToolRegistry#listForScope(true)}），
 * 权限模式固定 {@code ask}，作用域固定 {@code SCOPE_SUB}；它**不能写盘、不能执行命令、不能联网**。</p>
 *
 * <p><b>隔离手段：</b>每次派发都生成一个新的子会话 id（{@code 主会话-sub-随机后缀}），
 * 审计、预算、轨迹都会落在子会话名下，主对话只收到一段结论。</p>
 */
@Slf4j
@Component
public class SimpleSubAgentRunner implements SubAgentRunner {

    /** 子 agent 的工具循环上限：比主对话小，避免子任务无限自我循环。 */
    private static final int MAX_ROUND_TRIPS = 8;

    /** 子 agent 的系统提示词：把「只读、只回结论」写死，避免它模仿主对话去改文件。 */
    private static final String SUB_SYSTEM_PROMPT = """
            你是一个只读的调研子 agent。
            你只能使用只读工具（读文件、列目录、搜索），不能写盘、不能执行命令、不能联网。
            请围绕给定的子任务尽快得出结论：先用最少的工具调用收集证据，再给出结论。
            结论要求：先给 1~3 句直接回答，再列关键证据（文件路径 + 行号或片段）。
            不要输出寒暄，不要罗列你调用了哪些工具。
            """;

    /** 工具注册表：只读工具清单的来源。 */
    private final ToolRegistry toolRegistry;

    /** 设置注册表：模型名 / 接口地址 / 密钥名 / 权限模式。 */
    private final SettingsRegistry settingsRegistry;

    /** 供应商清单：默认地址、密钥名、是否必须配置密钥。 */
    private final LlmProviderRegistry llmProviderRegistry;

    /** 密钥仓库：取 API Key。 */
    private final SecretStore secretStore;

    /** 模型工厂路由：按供应商创建同步模型。 */
    private final LlmModelFactoryRouter llmModelFactoryRouter;

    /**
     * 构造器注入。
     *
     * @param toolRegistry          工具注册表
     * @param settingsRegistry      设置注册表
     * @param llmProviderRegistry   供应商清单
     * @param secretStore           密钥仓库
     * @param llmModelFactoryRouter 模型工厂路由
     */
    public SimpleSubAgentRunner(ToolRegistry toolRegistry,
                                SettingsRegistry settingsRegistry,
                                LlmProviderRegistry llmProviderRegistry,
                                SecretStore secretStore,
                                LlmModelFactoryRouter llmModelFactoryRouter) {
        this.toolRegistry = toolRegistry;
        this.settingsRegistry = settingsRegistry;
        this.llmProviderRegistry = llmProviderRegistry;
        this.secretStore = secretStore;
        this.llmModelFactoryRouter = llmModelFactoryRouter;
    }

    /**
     * 子 agent 的同步助手接口：AiServices 按它生成代理。
     */
    public interface SubAssistant {

        /**
         * 跑一轮同步工具循环并返回最终回答。
         *
         * @param userMessage 子任务描述 + 主对话补充的背景
         * @return 结论文本
         */
        String chat(String userMessage);
    }

    /**
     * 跑一个只读子任务并返回结论文本。
     *
     * @param task      子任务描述
     * @param context   主对话补充的背景；可为空
     * @param sessionId 主对话会话 id（据此派生子会话 id）
     * @return 子 agent 的结论；失败时返回一段可读的说明而不是抛异常
     */
    @Override
    public String run(String task, String context, String sessionId) {
        if (StrUtil.isBlank(task)) {
            return "";
        }
        String subSessionId = subSessionIdOf(sessionId);
        try {
            LlmModelSpec spec = buildModelSpec();
            ChatModel chatModel = llmModelFactoryRouter.createChatModel(spec);

            SubAssistant assistant = AiServices.builder(SubAssistant.class)
                    .chatModel(chatModel)
                    .systemMessage(SUB_SYSTEM_PROMPT)
                    .tools(buildReadOnlyTools(subSessionId))
                    .maxToolCallingRoundTrips(MAX_ROUND_TRIPS)
                    .build();

            // 在本线程设置子会话上下文：工具执行时 ToolRuntime 从这里读 session/scope/权限
            ToolSession.setSessionId(subSessionId);
            ToolSession.setAgentScope(ToolSession.SCOPE_SUB);
            ToolSession.setContext(new SessionContext(
                    subSessionId,
                    // 工作区白名单沿用全局配置
                    PathPolicy.workspaceRoots(),
                    // 本会话没有额外禁用的工具
                    Set.of(),
                    // 子 agent 不放行任何命令前缀（它本来也拿不到执行工具）
                    Set.of(),
                    // 工作区 id 尚未落地，保留空串
                    "",
                    // 子 agent 一律走最严权限：任何有副作用的操作都会弹确认
                    "ask",
                    ToolSession.SCOPE_SUB));

            String answer = assistant.chat(buildUserMessage(task, context));
            return answer == null ? "" : answer.strip();
        } catch (ApiException e) {
            // 配置类问题（没填密钥 / 供应商不存在）：把可读原因交给主对话，让它自己决定要不要继续
            return "子 agent 启动失败：" + e.getMessage();
        } catch (RuntimeException e) {
            log.warn("子 agent 执行失败 subSession={}：{}", subSessionId, e.getMessage(), e);
            return "子 agent 执行失败：" + e.getMessage();
        } finally {
            // 线程会被复用：不清会把子会话上下文串到下一轮
            ToolSession.clear();
        }
    }

    /**
     * 组装只读工具表：{@code listForScope(true)} 已经过滤掉写盘 / 执行类工具。
     *
     * @param subSessionId 子会话 id
     * @return ToolSpecification → ToolExecutor 的映射
     */
    private Map<ToolSpecification, ToolExecutor> buildReadOnlyTools(String subSessionId) {
        Map<ToolSpecification, ToolExecutor> tools = new LinkedHashMap<>();
        for (AgentTool tool : toolRegistry.listForScope(true)) {
            ToolSpecification specification = ToolSpecification.builder()
                    .name(tool.name())
                    .description(tool.description())
                    // 参数 schema 由工具自己声明：模型才知道该传哪些字段，而不是靠猜参数名
                    .parameters(ToolSchemaMapper.toJsonSchema(tool.parameters()))
                    .build();
            // 工具执行可能发生在模型 SDK 的回调线程：执行器里重新设置一次上下文，别依赖 run() 的 ThreadLocal
            tools.put(specification, (request, memoryId) -> executeTool(tool, request, subSessionId));
        }
        return tools;
    }

    /**
     * 执行一次工具调用。
     *
     * @param tool         被调用的工具
     * @param request      模型给出的调用请求（含 JSON 参数）
     * @param subSessionId 子会话 id
     * @return 工具结果文本（已带 OK: / FAIL: 前缀）
     */
    private String executeTool(AgentTool tool, ToolExecutionRequest request, String subSessionId) {
        Map<String, Object> arguments;
        try {
            String json = request.arguments();
            // 模型有时会省略参数：按空对象处理，让工具自己给出「缺少哪个参数」
            arguments = StrUtil.isBlank(json)
                    ? Map.of()
                    : JsonUtils.parse(json, new TypeReference<Map<String, Object>>() { });
        } catch (RuntimeException e) {
            // 参数不合法属于模型可自行修正的错误：回 FAIL 让它重试
            return ToolResult.fail(tool.name() + " 参数不是合法 JSON 对象: " + e.getMessage()).content();
        }

        ToolSession.setSessionId(subSessionId);
        ToolSession.setAgentScope(ToolSession.SCOPE_SUB);
        ToolSession.setContext(new SessionContext(
                subSessionId,
                PathPolicy.workspaceRoots(),
                Set.of(),
                Set.of(),
                "",
                "ask",
                ToolSession.SCOPE_SUB));
        try {
            return tool.execute(arguments).content();
        } catch (RuntimeException e) {
            // ToolRuntime 已把业务异常转成 FAIL；这里再兜一层，避免异常冒到框架回调
            return ToolResult.fail(tool.name() + " 执行失败: " + e.getMessage()).content();
        }
    }

    /**
     * 拼子任务消息：任务描述 + 主对话补充的背景。
     *
     * @param task    子任务描述
     * @param context 主对话补充的背景；可为空
     * @return 发给子 agent 的用户消息
     */
    private static String buildUserMessage(String task, String context) {
        if (StrUtil.isBlank(context)) {
            return "子任务：\n" + task;
        }
        return "子任务：\n" + task + "\n\n主对话补充的背景：\n" + context;
    }

    /**
     * 生成子会话 id：主会话 id + "-sub-" + 8 位随机串。
     *
     * @param sessionId 主会话 id；可为空
     * @return 子会话 id
     */
    private static String subSessionIdOf(String sessionId) {
        String suffix = IdUtil.fastSimpleUUID().substring(0, 8);
        String prefix = StrUtil.isBlank(sessionId) ? "sub" : sessionId + "-sub";
        return prefix + "-" + suffix;
    }

    /**
     * 按当前设置装配模型参数（与 ChatServiceImpl#buildModelSpec 保持一致的取值顺序）。
     *
     * @return 模型装配参数
     * @throws ApiException 供应商未知、没有模型或缺少密钥时
     */
    private LlmModelSpec buildModelSpec() {
        String providerId = String.valueOf(settingsRegistry.getSetting("llm.provider"));
        String modelName = String.valueOf(settingsRegistry.getSetting("llm.model")).trim();

        LlmDtos.ProviderInfo provider = llmProviderRegistry.findProvider(providerId)
                .orElseThrow(() -> new ApiException(404, "未知的模型供应商：" + providerId));
        if (modelName.isEmpty()) {
            if (provider.models().isEmpty()) {
                throw new ApiException(404, "供应商 " + providerId + " 还没有配置任何模型");
            }
            modelName = provider.models().get(0).model();
        }

        String apiKey = null;
        if (!StrUtil.isBlank(provider.secretKey())) {
            apiKey = secretStore.getSecret(provider.secretKey()).orElse(null);
        }
        if (provider.requiresKey() && StrUtil.isBlank(apiKey)) {
            throw new ApiException(400, "尚未配置 " + provider.label() + " 的 API 密钥，"
                    + "请到设置页的「模型」分区填写（对应设置项：" + provider.secretKey() + "）");
        }

        // 接口地址：自定义端点用自己的地址，内置供应商保持「全局配置优先」
        String configuredBaseUrl = String.valueOf(settingsRegistry.getSetting("llm.base_url"));
        String baseUrl = provider.isCustom()
                ? provider.baseUrl()
                : (configuredBaseUrl.isBlank() ? provider.baseUrl() : configuredBaseUrl.trim());

        Double temperature = ((Number) settingsRegistry.getSetting("llm.temperature")).doubleValue();
        int configuredMaxTokens = ((Number) settingsRegistry.getSetting("llm.max_tokens")).intValue();
        Integer maxTokens = configuredMaxTokens > 0 ? configuredMaxTokens : null;

        return new LlmModelSpec(providerId, modelName, apiKey, baseUrl, temperature, maxTokens);
    }
}
