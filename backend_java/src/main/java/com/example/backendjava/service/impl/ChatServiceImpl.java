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
// 标准库：Duration 表达「最多等模型多久才收尾」，比裸数字更好读
import java.time.Duration;
// 标准库：Instant 记录消息/会话的创建时间（库里存 ISO 文本）
import java.time.Instant;
// 标准库：LocalDateTime 拼「今天」这类按天统计的边界
import java.time.LocalDateTime;
// 标准库：集合、Map、UUID 等日常容器（本文件里用于事件载荷、工具表、会话 id）
import java.util.*;
// 标准库：线程池接口，对话轮次与记忆抽取各用一个
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;
// 记忆服务：新对话注入工作区记忆 + 每轮结束异步抽取
import com.example.backendjava.service.MemoryService;
// 技能服务：把「技能名 + 描述」拼进系统提示词
import com.example.backendjava.service.SkillService;
// RAG 服务：\doc 模式下列表 / 删除 / 导入 / 检索
import com.example.backendjava.service.RagService;
// 记忆接口的请求 DTO：注入时用 search，抽取时用 extract
import com.example.backendjava.dto.MemoryDtos;
// 预算登记表：把本轮用量喂给熔断
import com.example.backendjava.tools.ToolBudgetRegistry;
// 进程内摘要缓存：同一批历史只摘要一次，不存在消息表里（重启后重新摘要一次即可）
import java.util.concurrent.ConcurrentHashMap;
// LangChain4j 用户消息：把数据库里的 user 行还原成模型认识的消息对象
import dev.langchain4j.data.message.UserMessage;
// LangChain4j 助手消息：把数据库里的 assistant 行还原成模型认识的消息对象
import dev.langchain4j.data.message.AiMessage;
// LangChain4j 对话记忆接口：AiServices 每轮自动带上这里的内容
import dev.langchain4j.memory.ChatMemory;
// LangChain4j 滑动窗口记忆：只保留最近 maxMessages 条，超出的自动丢弃
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
// LangChain4j 同步聊天模型：摘要压缩与 \doc 问答用它（不需要流式）
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式响应体：onCompleteResponse 回调的形参类型
import dev.langchain4j.model.chat.response.ChatResponse;
// 标准库：判断导入的文件是否存在 / 是不是目录
import java.nio.file.Files;
// 标准库：把用户输入的路径转成绝对路径（相对路径按后端进程的工作目录解析）
import java.nio.file.Path;
// 标准库：正则匹配器，解析 `\doc` 前缀后面的子命令
import java.util.regex.Matcher;
// 标准库：正则表达式，识别 `\doc` 前缀（大小写不敏感、允许换行）
import java.util.regex.Pattern;
// RAG 接口的请求/响应 DTO：文档列表、入库、检索都用到
import com.example.backendjava.dto.RagDtos;

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
    /** 预算登记表：本轮结束后把 token / 费用累加进去，供下一次工具调用前核对。 */
    @Resource
    private ToolBudgetRegistry toolBudgetRegistry;

    /** 记忆服务：首轮注入工作区记忆，每轮结束异步抽取。 */
    @Resource
    private MemoryService memoryService;

    /** 技能服务：把可用技能清单拼进系统提示词。 */
    @Resource
    private SkillService skillService;

    /** RAG 服务：`\doc` 模式的列表 / 删除 / 导入 / 检索都走它。 */
    @Resource
    private RagService ragService;

    /** 记忆抽取线程池：单线程、守护线程，避免占用对话轮次线程。 */
    @Resource
    private ExecutorService memoryExtractExecutor;

    /** 每次补种上下文最多读多少条历史；再早的内容只能靠摘要。 */
    private static final int MAX_SEED_MESSAGES = 200;

    /** 模型窗口未知时的兜底值（token）；宁可早压缩，也不要等供应商报 context length 错误。 */
    private static final int DEFAULT_CONTEXT_WINDOW = 32_768;

    /**
     * SSE 连接的最长存活时间（毫秒）。
     *
     * <p>Spring 到这个点还没收尾就会自己关流，前端表现为连接断开，所以「等模型」的上限
     * 必须比它小（见 {@link #TURN_TIMEOUT_SECONDS}）。普通对话与 `\doc` 命令共用这个值。</p>
     */
    private static final long SSE_TIMEOUT_MS = 300_000L;

    /**
     * 收尾预留时间（毫秒）。
     *
     * <p>为什么要有：等模型的上限必须比 {@link #SSE_TIMEOUT_MS} 小一点，
     * 好让落库、发 done、关流这些收尾动作在 Spring 判超时关连接之前做完。</p>
     */
    private static final long TURN_WRAP_UP_MS = 20_000L;

    /** 送去摘要的原文最大字符数；超出部分直接省略，避免「为了压缩反而先超窗」。 */
    private static final int MAX_SUMMARY_INPUT_CHARS = 8_000;

    /** 摘要本身的最大字符数；太长会挤占本轮的对话预算。 */
    private static final int MAX_SUMMARY_CHARS = 1_200;

    /** 最多注入多少个技能名；技能很多时只提示前 N 个，避免提示词被技能清单占满。 */
    private static final int MAX_INJECTED_SKILLS = 30;

    /** 技能描述压成一行后的最大字符数。 */
    private static final int MAX_SKILL_DESCRIPTION_CHARS = 120;
    /** `\doc -l` 最多列出多少篇文档；再多就建议用户去「知识库」页看。 */
    private static final int DOC_LIST_LIMIT = 50;

    /** `\doc` 后面什么都没写时的默认问题。 */
    private static final String DOC_DEFAULT_QUERY = "请概括这份文档的主要内容";

    /** 送进提示词的单个片段最大字符数。 */
    private static final int MAX_DOC_SNIPPET_CHARS = 1_200;

    /** 送进提示词的全部片段总字符上限，避免检索结果把窗口占满。 */
    private static final int MAX_DOC_CONTEXT_CHARS = 6_000;

    /** 识别 `\doc` 前缀：允许大小写混写，`.` 跨行匹配（用户可能粘贴多行内容）。 */
    private static final Pattern DOC_PREFIX =
            Pattern.compile("^\\\\doc\\b[ \\t]*(.*)$", Pattern.DOTALL | Pattern.CASE_INSENSITIVE);

    /** `\doc` 的帮助类动词。 */
    private static final Set<String> HELP_VERBS = Set.of("-h", "--help", "?", "？", "help");

    /** `\doc` 的列文档动词。 */
    private static final Set<String> LIST_VERBS = Set.of("-l", "--list", "-ls");

    /** `\doc` 的删除动词。 */
    private static final Set<String> DELETE_VERBS = Set.of("-d", "--delete", "-rm");

    /** `\doc` 的导入动词。 */
    private static final Set<String> IMPORT_VERBS = Set.of("-i", "--import", "-a", "--add");

    /** `\doc -h` 的完整用法文本；写入 Java 源码时反斜杠要写两遍（`\\doc`）。 */
    private static final String DOC_HELP_TEXT = """
            \\doc 知识库指令
              \\doc -h, --help, ?        显示本帮助
              \\doc -l, --list, -ls      列出已入库的文档（最多 50 篇）
              \\doc -d, --delete <名字>  按文档名或来源删除一篇文档
              \\doc -i, --import <路径>  把本地文件导入知识库（一次一个文件）
              \\doc <问题>               在知识库里检索并回答（片段数由请求里的 doc_top_k 决定）

            说明：
            - 名字可以只写一部分，按「完全匹配 → 包含匹配」的顺序找；
            - 不带 \\doc 前缀的消息仍按普通 Agent 对话处理。
            """;

    /**
     * 解析一条 `\doc` 指令。
     *
     * @param message 用户原始输入
     * @return 解析结果；永不为 null
     */
    private DocCommand parseDocCommand(String message) {
        String text = nvl(message).strip();
        Matcher matcher = DOC_PREFIX.matcher(text);
        // 没有 `\doc` 前缀：整句当作检索问题
        if (!matcher.matches()) {
            return new DocCommand("search", "", text);
        }
        String rest = matcher.group(1).strip();
        // 只写了 `\doc`：按「用户想看看怎么用」处理，直接回帮助
        if (rest.isEmpty()) {
            return new DocCommand("help", "", "");
        }
        String verb = rest.split("\\s+", 2)[0];
        String argument = rest.length() > verb.length()
                ? rest.substring(verb.length()).strip()
                : "";
        // 动词统一小写再比对，避免 `-L` / `-D` 之类因为大小写被当成问题
        String lower = verb.toLowerCase(Locale.ROOT);

        if (HELP_VERBS.contains(lower)) {
            return new DocCommand("help", "", "");
        }
        if (LIST_VERBS.contains(lower)) {
            return new DocCommand("list", "", "");
        }
        if (DELETE_VERBS.contains(lower)) {
            // 少了文件名：回 unknown，让 executeDocCommand 给出用法提示
            return argument.isEmpty()
                    ? new DocCommand("unknown", verb, "")
                    : new DocCommand("delete", argument, "");
        }
        if (IMPORT_VERBS.contains(lower)) {
            return argument.isEmpty()
                    ? new DocCommand("unknown", verb, "")
                    : new DocCommand("import", argument, "");
        }
        // 以 - 开头但不在任何命令表里：明确回「不认识」，不要当成问题去检索
        if (lower.startsWith("-")) {
            return new DocCommand("unknown", verb, argument);
        }
        // 其余情况：整段（含第一个词）都是问题
        return new DocCommand("search", "", rest);
    }

    /**
     * 执行一条 `\doc` 指令，返回要一次性推给前端的文本。
     *
     * @param request 本轮请求（用到 message / docTopK / mode）
     * @return 回答或提示文本；永不为 null
     */
    private String executeDocCommand(ChatDtos.ChatRequest request) {
        DocCommand command = parseDocCommand(request.message());
        return switch (command.action()) {
            case "help" -> DOC_HELP_TEXT;
            case "list" -> docList();
            case "delete" -> docDelete(command.target());
            case "import" -> docImport(command.target());
            case "unknown" -> "不认识的 \\doc 子命令：" + command.target() + "\n\n" + DOC_HELP_TEXT;
            case "search" -> docAnswer(command.query(), request.docTopK());
            // 理论上不会走到：动作集合是封闭的，兜底回帮助
            default -> DOC_HELP_TEXT;
        };
    }

    /**
     * `\doc -l`：列出已入库的文档。
     *
     * @return 文档清单文本
     */
    private String docList() {
        List<RagDtos.RagDocument> documents = ragService.listDocuments(DOC_LIST_LIMIT, 0);
        if (documents.isEmpty()) {
            return "知识库里还没有文档。用 `\\doc -i <文件路径>` 导入一份。";
        }
        StringBuilder text = new StringBuilder("知识库文档（最多显示 " + DOC_LIST_LIMIT + " 篇）：\n");
        for (RagDtos.RagDocument document : documents) {
            text.append("- #").append(document.id()).append(' ')
                    .append(docDisplayName(document))
                    .append("（").append(document.chunks()).append(" 个片段）\n");
        }
        text.append("\n删除用 `\\doc -d <名字>`，导入用 `\\doc -i <文件路径>`。");
        return text.toString();
    }

    /**
     * `\doc -d <名字>`：按名字删除一篇文档。
     *
     * @param target 用户写的文档名（允许只写一部分）
     * @return 操作结果文本
     */
    private String docDelete(String target) {
        RagDtos.RagDocument matched = findDoc(target);
        if (matched == null) {
            return "知识库里没有找到「" + target + "」。先发 `\\doc -l` 看看有哪些文档。";
        }
        ragService.deleteById(matched.id());
        return "已删除文档 #" + matched.id() + " " + docDisplayName(matched) + "。";
    }

    /**
     * `\doc -i <路径>`：把一个本地文件导入知识库。
     *
     * @param target 用户写的文件路径
     * @return 操作结果文本
     */
    private String docImport(String target) {
        Path path;
        try {
            path = Path.of(target).toAbsolutePath().normalize();
        } catch (RuntimeException e) {
            // 路径里有非法字符（例如 Windows 保留名）：给出可读提示而不是堆栈
            return "路径不合法：" + target;
        }
        if (!Files.exists(path)) {
            return "文件不存在：" + path;
        }
        if (Files.isDirectory(path)) {
            return "这是一个目录，不是文件：" + path + "\n一次只能导入一个文件，请指定目录里的具体文件。";
        }
        try {
            RagDtos.IndexResult result = ragService.indexFile(
                    new RagDtos.IndexFileRequest(path.toString(), path.toString(), null, false));
            return "已导入 " + path.getFileName() + "：动作 " + result.action()
                    + "，共 " + result.totalChunks() + " 个片段（本次新建 " + result.newChunks() + " 个）。";
        } catch (RuntimeException e) {
            return "导入失败：" + e.getMessage();
        }
    }

    /**
     * `\doc <问题>`：先检索，再让模型只依据检索结果回答。
     *
     * @param query 用户问题
     * @param topK  片段数上限（来自请求的 doc_top_k）
     * @return 回答文本；模型不可用时退回「直接给命中片段」
     */
    private String docAnswer(String query, int topK) {
        String question = nvl(query).strip();
        if (question.isEmpty()) {
            question = DOC_DEFAULT_QUERY;
        }

        List<RagDtos.SearchHit> hits;
        try {
            int safeTopK = Math.max(1, Math.min(20, topK));
            hits = ragService.search(new RagDtos.SearchRequest(
                    question, safeTopK, null, null, null));
        } catch (RuntimeException e) {
            return "检索失败：" + e.getMessage();
        }
        if (hits.isEmpty()) {
            return "知识库里没有找到与「" + question + "」相关的内容。可以先发 `\\doc -l` 看看有哪些文档。";
        }

        StringBuilder context = new StringBuilder();
        int used = 0;
        for (RagDtos.SearchHit hit : hits) {
            if (used >= MAX_DOC_CONTEXT_CHARS) {
                break;
            }
            String text = nvl(hit.text());
            if (text.length() > MAX_DOC_SNIPPET_CHARS) {
                text = text.substring(0, MAX_DOC_SNIPPET_CHARS) + "…";
            }
            context.append("[#").append(hit.chunkId()).append("] ")
                    .append(docDisplayName(hit)).append("：\n")
                    .append(text).append("\n\n");
            used += text.length();
        }

        String prompt = "请只依据下面的资料回答问题；资料里没有的内容就直接说「资料里没有提到」，不要编造。\n\n"
                + "资料：\n" + context + "\n问题：" + question;
        try {
            ChatModel chatModel = llmModelFactoryRouter.createChatModel(buildModelSpec());
            String answer = chatModel.chat(prompt);
            return answer == null || answer.isBlank() ? "（模型没有给出回答）" : answer.strip();
        } catch (RuntimeException e) {
            // 模型不可用时至少把命中片段给用户，别让 `\doc 问题` 完全无输出
            return "模型调用失败（" + e.getMessage() + "），先给你命中的资料：\n\n" + context;
        }
    }

    /**
     * 按名字找一篇文档：先精确匹配，再包含匹配。
     *
     * @param target 用户写的名字
     * @return 命中的文档；找不到时为 null
     */
    private RagDtos.RagDocument findDoc(String target) {
        String needle = nvl(target).strip();
        if (needle.isEmpty()) {
            return null;
        }
        List<RagDtos.RagDocument> documents = ragService.listDocuments(DOC_LIST_LIMIT, 0);
        // 第一轮：完全相等（忽略大小写），避免「报告」误删「年度报告」
        for (RagDtos.RagDocument document : documents) {
            if (needle.equalsIgnoreCase(docDisplayName(document))) {
                return document;
            }
        }
        // 第二轮：包含匹配，允许用户只写文件名的一部分
        for (RagDtos.RagDocument document : documents) {
            if (docDisplayName(document).contains(needle)) {
                return document;
            }
        }
        return null;
    }

    /**
     * 取文档的展示名：标题 → 文件名 → 来源。
     *
     * @param document 文档
     * @return 展示名；永不为 null
     */
    private static String docDisplayName(RagDtos.RagDocument document) {
        if (document.title() != null && !document.title().isBlank()) {
            return document.title();
        }
        if (document.name() != null && !document.name().isBlank()) {
            return document.name();
        }
        return nvl(document.source());
    }

    /**
     * 取检索命中的展示名：标题 → 来源。
     *
     * @param hit 检索命中
     * @return 展示名；永不为 null
     */
    private static String docDisplayName(RagDtos.SearchHit hit) {
        if (hit.title() != null && !hit.title().isBlank()) {
            return hit.title();
        }
        return nvl(hit.source());
    }
    /**
     * 会话级摘要缓存：sessionId → 已压缩内容的摘要。
     *
     * <p>放内存而不是落库：摘要属于「可重算的派生数据」，重启后重新摘要一次即可；
     * 落库反而要处理「消息被删了摘要还留着」的一致性问题。</p>
     */
    private final Map<String, SummaryCache> summaryCache = new ConcurrentHashMap<>();

    /** 系统提示词：启动时一次性读入，之后每轮对话复用；修改模板后需重启服务才会生效。 系统提示词不应该暴露给用户随意修改*/
    private String systemPrompt;

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
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
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
     * 真正执行一轮对话：补种上下文 → 落用户消息 → （doc 模式分支）→ 装配模型 → 跑工具循环 → 落库收尾。
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

            // 2) 先读历史（此时还不含本轮用户消息），必要时压缩；历史会真正进入模型请求
            SeedContext seed = buildSeedContext(sessionId);
            sessionBus.emit(sessionId, chatEvents.thinking(sessionId, "history",
                    System.currentTimeMillis() - startedAt, seed.recent().size(),
                    "已载入 " + seed.recent().size() + " 条历史消息"));

            // 3) 落用户消息（先落库，避免崩溃时丢失用户输入）
            persistMessage(sessionId, "user", request.message(), request.mode());

            // 3.1) doc 模式：解析 `\doc` 子命令，确定性分支不进模型工具循环
            if ("doc".equals(request.mode())) {
                String answer = executeDocCommand(request);
                recorder.appendAnswer(answer);
                // 一次性发给前端：doc 命令要么是即时结果，要么是同步问答，不需要逐字流
                sessionBus.emit(sessionId, chatEvents.token(answer));
                // 直接返回，finally 里统一 finishTurn（落库 + done + 关流）
                return;
            }

            // 4) 建模型（供应商/模型名/密钥都在 buildModelSpec 里）
            LlmModelSpec spec = buildModelSpec();
            StreamingChatModel chatModel = llmModelFactoryRouter.createStreamingModel(spec);
            recorder.setModel(spec.model());

            // 5) 组装工具表：每个工具包一层 ChatToolExecutor，事件就有了
            Map<ToolSpecification, ToolExecutor> tools = buildEventedToolMap(sessionId, recorder);

            // 6) 建 AiServices：
            //    - systemMessage 每轮现拼（记忆 / 技能 / 摘要），不写进记忆，避免被窗口挤掉；
            //    - chatMemory 负责把历史（以及本轮用户消息）真正带给模型。
            Assistant assistant = AiServices.builder(Assistant.class)
                    .streamingChatModel(chatModel)
                    .systemMessage(buildSystemMessage(seed, request.message()))
                    .chatMemory(buildChatMemory(seed.recent()))
                    .tools(tools)
                    .maxToolCallingRoundTrips(request.maxIterations())
                    .build();

            sessionBus.emit(sessionId, chatEvents.thinking(sessionId, "model",
                    System.currentTimeMillis() - startedAt, seed.recent().size(), "正在请求模型…"));

            // 7) 开本轮预算：工具边界会读它判断是否越线
            toolBudgetRegistry.startBudget(sessionId);

            // 8) 跑起来：start() 只负责「把请求发出去」，不阻塞等答案。
            //    langchain4j 1.22 实测：start() 约 0.5 秒返回，第一个 token 要 1.7 秒后才到，
            //    回调跑在别的线程上（ForkJoinPool.commonPool / HTTP 客户端线程），所以下面必须 await。
            StreamingTurn turn = StreamingTurn.start(
                    assistant.chat(request.message()),
                    partial -> {
                        // 用户点了停止：不再转发增量，但模型那边没法取消，让它自己跑完
                        if (recorder.isStopped()) {
                            return;
                        }
                        recorder.appendAnswer(partial);
                        sessionBus.emit(sessionId, chatEvents.token(partial));
                    },
                    response -> recordUsage(sessionId, recorder, response),
                    error -> sessionBus.emit(sessionId, chatEvents.error(
                            "模型调用失败：" + error.getMessage(),
                            request.debug() ? stackOf(error) : null)));

            // 9) 等整轮真的结束（含所有工具调用）再往下走。
            //    不能省：start() 一返回就走的话，答案还是空串，
            //    finishTurn 会「按空答案落库（等于不落）+ 提前发 done + 立刻关流」，
            //    模型随后吐出的内容全部写进已关闭的 SSE 流，前端只能看到 answer=""。
            //
            //    预算要用「本轮开始时刻」算：前面的补种上下文、建模型可能已经花掉几秒，
            //    扣掉之后剩下的时间与 SSE 的存活时间对齐，收尾才来得及。
            long deadline = startedAt + SSE_TIMEOUT_MS - TURN_WRAP_UP_MS;
            boolean finished = false;
            while (true) {
                long now = System.currentTimeMillis();
                long remaining = deadline - now;
                if (remaining <= 0L) {
                    // 等确认的窗口（10 分钟）比 SSE 长：此刻若正等用户点确认，
                    // 现在收尾会让这次确认彻底作废（/chat/resume 找不到待确认的轮次），
                    // 所以重新给一个完整窗口，等确认结果回来再算。
                    if (sessionBus.hasPending(sessionId)) {
                        deadline = now + SSE_TIMEOUT_MS - TURN_WRAP_UP_MS;
                        continue;
                    }
                    break;
                }
                if (turn.await(Duration.ofMillis(remaining))) {
                    finished = true;
                    break;
                }
            }
            if (!finished) {
                sessionBus.emit(sessionId, chatEvents.error(
                        "模型响应超时：" + SSE_TIMEOUT_MS / 1000 + " 秒内没有返回完整结果",
                        request.debug() ? "等待 onCompleteResponse / onError 超时" : null));
            }

        } catch (InterruptedException ex) {
            // 现在没有代码主动中断对话线程（线程池关闭用的是 shutdown()），这里是兜底：
            // 万一将来改成会中断的关闭方式，也别让前端一直转圈。
            // 恢复中断标记，让上层调用链知道该收手了。
            Thread.currentThread().interrupt();
            sessionBus.emit(sessionId, chatEvents.error(
                    "本轮对话被中断：" + ex.getMessage(), request.debug() ? stackOf(ex) : null));
        } catch (RuntimeException ex) {
            // 任何未预料异常都要变成 error 事件，否则前端只能干等到超时
            sessionBus.emit(sessionId, chatEvents.error(
                    "本轮对话失败：" + ex.getMessage(), request.debug() ? stackOf(ex) : null));
        } finally {
            // 10) 落助手消息 + 发 done + 关流。无论成功失败都要走到这里
            finishTurn(sessionId, request, recorder, turnId);
        }
    }


    /**
     * 收尾：落库（含用量与工具轨迹）、发 done（或 stopped）、关流、清理运行时状态、异步抽取记忆。
     *
     * @param sessionId 会话 id
     * @param request   请求
     * @param recorder  本轮记录器
     * @param turnId    轮次 id
     */
    private void finishTurn(String sessionId, ChatDtos.ChatRequest request, TurnRecorder recorder, String turnId) {
        String answer = recorder.answer();
        try {
            // 1) 助手消息落库：正文 + 模式 + 工具轨迹 + 用量 + 模型名，历史回放与用量面板都靠它
            if (!answer.isBlank()) {
                Map<String, Object> usage = recorder.usage();
                chatPersistence.saveAssistantMessage(
                        sessionId,
                        answer,
                        request.mode(),
                        toolCallsJson(recorder.toolCalls()),
                        recorder.isStopped() ? "stopped" : "done",
                        recorder.elapsedMs() / 1000.0,
                        recorder.model(),
                        longOf(usage, "input_tokens"),
                        longOf(usage, "output_tokens"),
                        doubleOf(usage, "cost"));
            }
            // 2) 更新会话的 updated_at 与标题（首轮用第一句话当标题）
            touchSession(sessionId, request.message());
        } catch (RuntimeException ex) {
            // 落库失败不影响用户看到答案：只记日志
            log.warn("会话落库失败 sessionId={} turnId={}", sessionId, turnId, ex);
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
        // 5) 清掉本轮预算：下一轮会重新 startBudget，留着旧数据只会误判
        toolBudgetRegistry.clearBudget(sessionId);
        // 6) 清掉本线程的轮次 id：线程池复用线程，不清会把下一轮的轨迹记到本轮名下
        traceEventSink.clearTurnId();
        // 7) 异步抽取记忆：失败只记日志，绝不影响本轮对话
        scheduleMemoryExtraction(sessionId);
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
                    .parameters(ToolSchemaMapper.toJsonSchema(tool.parameters()))
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


    /**
     * 落一条对话消息（只有用户消息走这里；助手消息带用量，走 saveAssistantMessage）。
     *
     * @param sessionId 会话 id
     * @param role      角色：user
     * @param content   正文
     * @param mode      对话模式：agent / doc
     */
    private void persistMessage(String sessionId, String role, String content, String mode) {
        chatPersistence.saveMessage(sessionId, role, content, mode, null, null, null);
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
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
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
        // 清掉摘要缓存与预算：否则清空上下文后，下一轮还会被塞进上一段摘要
        summaryCache.remove(sessionId);
        toolBudgetRegistry.clearBudget(sessionId);
        // 清运行时状态（总线里的 Turn），让「已删会话」不再出现在运行态里
        sessionBus.finish(sessionId);
        // 清掉摘要缓存与预算：否则清空上下文后，下一轮还会被塞进上一段摘要
        summaryCache.remove(sessionId);
        toolBudgetRegistry.clearBudget(sessionId);
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
        // 清掉摘要缓存与预算：否则清空上下文后，下一轮还会被塞进上一段摘要
        summaryCache.remove(sessionId);
        toolBudgetRegistry.clearBudget(sessionId);
        // 清掉运行时状态与检查点，让下一轮从干净状态开始
        sessionBus.finish(sessionId);
        // 清掉摘要缓存与预算：否则清空上下文后，下一轮还会被塞进上一段摘要
        summaryCache.remove(sessionId);
        toolBudgetRegistry.clearBudget(sessionId);


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

    // ------------------------------------------------------------------ //
    // 上下文补种与压缩（2.1 / 2.4）
    // ------------------------------------------------------------------ //

    /**
     * 读取本会话历史并准备成「可以直接喂给模型」的形态：最近 N 条原文 + 更早内容的摘要。
     *
     * <p>压缩触发条件（三条同时满足）：{@code context.auto_compress=true}、
     * 估算 token 超过 {@code maxMessages × compress_threshold}、历史条数大于 {@code keep_recent_n}。</p>
     *
     * @param sessionId 会话 id
     * @return 补种上下文（最近消息 + 摘要，摘要可能为空串）
     */
    private SeedContext buildSeedContext(String sessionId) {
        List<ChatMessage> recent = new ArrayList<>(
                chatPersistence.findRecentMessages(sessionId, MAX_SEED_MESSAGES));

        int keepRecent = intSetting("context.keep_recent_n", 10);
        // 历史本来就不多：原样带上，顺便把之前压过的摘要继续带着
        if (recent.size() <= keepRecent || !boolSetting("context.auto_compress", true)) {
            return new SeedContext(recent, cachedSummary(sessionId));
        }

        int contextWindow = resolveContextWindow();
        double threshold = doubleSetting("context.compress_threshold", 0.7);
        long estimated = 0L;
        for (ChatMessage row : recent) {
            estimated += estimateTokens(row.getContent());
        }
        // 没到阈值：全部原样带上（此时仍在窗口内，压缩反而损失信息）
        if (estimated <= (long) (contextWindow * threshold)) {
            return new SeedContext(recent, cachedSummary(sessionId));
        }

        // 触发了：最近 keepRecent 条原样保留，更早的压成一段摘要
        int splitAt = recent.size() - keepRecent;
        List<ChatMessage> older = new ArrayList<>(recent.subList(0, splitAt));
        List<ChatMessage> tail = new ArrayList<>(recent.subList(splitAt, recent.size()));
        String summary = summarize(sessionId, older);

        log.info("上下文压缩：session={} 估算 {} token > 窗口 {} 的 {}%，保留最近 {} 条，摘要 {} 字",
                sessionId, estimated, contextWindow, threshold, tail.size(), summary.length());
        return new SeedContext(tail, summary);
    }

    /**
     * 把一段较早的历史压成摘要；同一批消息只摘要一次。
     *
     * @param sessionId 会话 id（摘要缓存按它分组）
     * @param older     需要压缩的较早消息（时间正序）
     * @return 摘要文本；失败时返回上一次的摘要（可能为空串）
     */
    private String summarize(String sessionId, List<ChatMessage> older) {
        if (older.isEmpty()) {
            return cachedSummary(sessionId);
        }
        long lastMessageId = idOf(older.get(older.size() - 1));
        SummaryCache cached = summaryCache.get(sessionId);
        // 同一批消息已经摘要过：直接复用，省一次模型调用
        if (cached != null && cached.lastMessageId() == lastMessageId) {
            return cached.summary();
        }
        String previous = cached == null ? "" : cached.summary();

        String summary;
        try {
            ChatModel chatModel = llmModelFactoryRouter.createChatModel(buildModelSpec());
            summary = chatModel.chat(buildSummaryPrompt(previous, older));
        } catch (RuntimeException e) {
            // 摘要失败不能打断对话：退回「只保留最近 N 条」，模型至少还能看到最近的上下文
            log.warn("上下文摘要失败，本轮退回「只保留最近 N 条」 session={}：{}", sessionId, e.getMessage());
            return previous;
        }
        if (summary == null || summary.isBlank()) {
            return previous;
        }
        String trimmed = summary.strip();
        if (trimmed.length() > MAX_SUMMARY_CHARS) {
            trimmed = trimmed.substring(0, MAX_SUMMARY_CHARS);
        }
        summaryCache.put(sessionId, new SummaryCache(lastMessageId, trimmed));
        return trimmed;
    }

    /**
     * 拼摘要提示词。
     *
     * @param previous 上一次的摘要（可能为空串）；要求模型合并进来，避免「压一次丢一段」
     * @param older    需要压缩的消息（时间正序）
     * @return 提示词
     */
    private String buildSummaryPrompt(String previous, List<ChatMessage> older) {
        StringBuilder prompt = new StringBuilder();
        prompt.append("你在帮一个对话系统压缩上下文。请把下面的历史对话压成一段摘要，")
                .append("保留：用户的目标与偏好、已经确认的结论、未完成的事项、关键文件路径与命令。")
                .append("不要编造，不要输出客套话，直接给摘要正文，控制在 ")
                .append(MAX_SUMMARY_CHARS).append(" 字以内。\n\n");
        if (previous != null && !previous.isBlank()) {
            prompt.append("已有的更早摘要（请合并进来，不要丢掉里面的事实）：\n")
                    .append(previous).append("\n\n");
        }
        prompt.append("需要压缩的对话片段：\n");
        int used = 0;
        for (ChatMessage row : older) {
            if (used >= MAX_SUMMARY_INPUT_CHARS) {
                prompt.append("…（更早的内容已省略）\n");
                break;
            }
            String text = nvl(row.getContent());
            int budget = MAX_SUMMARY_INPUT_CHARS - used;
            if (text.length() > budget) {
                text = text.substring(0, budget);
            }
            prompt.append("user".equals(row.getRole()) ? "用户：" : "助手：")
                    .append(text).append('\n');
            used += text.length();
        }
        return prompt.toString();
    }

    /**
     * 把最近的消息还原成 LangChain4j 的记忆。
     *
     * <p><b>为什么每轮新建：</b>记忆只服务于「这一次请求」。新建一个窗口记忆、把历史灌进去，
     * 请求结束即丢弃，既不会跨会话串味，也不用处理「多线程同时改同一个 memory」的问题。</p>
     *
     * @param recent 最近的消息（时间正序，不含本轮用户消息）
     * @return 已灌好历史的窗口记忆
     */
    private ChatMemory buildChatMemory(List<ChatMessage> recent) {
        ChatMemory memory = MessageWindowChatMemory.builder()
                .maxMessages(MAX_SEED_MESSAGES)
                .build();
        for (ChatMessage row : recent) {
            String text = nvl(row.getContent());
            if (text.isBlank()) {
                continue;
            }
            if ("user".equals(row.getRole())) {
                memory.add(UserMessage.from(text));
            } else if ("assistant".equals(row.getRole())) {
                memory.add(AiMessage.from(text));
            }
            // system / tool 行不补：它们不是对话轮次，塞进窗口只会挤掉真正的上下文
        }
        return memory;
    }

    /**
     * 读会话级摘要缓存。
     *
     * @param sessionId 会话 id
     * @return 摘要；没有压缩过时为空的字符串（调用方不需要判空）
     */
    private String cachedSummary(String sessionId) {
        SummaryCache cached = summaryCache.get(sessionId);
        return cached == null ? "" : cached.summary();
    }

    // ------------------------------------------------------------------ //
    // 系统提示词动态拼装（2.6）
    // ------------------------------------------------------------------ //

    /**
     * 拼本轮的完整系统提示词：基础模板 + 工作区记忆（仅首轮）+ 可用技能 + 更早内容的摘要。
     *
     * <p>这些内容都放在 systemMessage 而不是 chatMemory 里：systemMessage 每轮现拼、不占历史窗口，
     * 也不会因为窗口滑动被挤掉。</p>
     *
     * @param seed        补种上下文
     * @param userMessage 本轮用户输入（用来检索相关记忆）
     * @return 完整的系统提示词
     */
    private String buildSystemMessage(SeedContext seed, String userMessage) {
        StringBuilder system = new StringBuilder(systemPrompt);
        // 记忆只在新对话的第一条消息注入：这是设置项 memory.inject_enabled 声明的语义
        appendMemoryBlock(system, userMessage, seed.recent().isEmpty());
        appendSkillBlock(system);
        if (!seed.summary().isBlank()) {
            system.append("\n\n## 本会话更早内容的摘要（系统自动压缩，供你回忆）\n\n")
                    .append(seed.summary());
        }
        return system.toString();
    }

    /**
     * 追加「工作区记忆」段落（受 memory.enabled / memory.inject_enabled 控制）。
     *
     * @param system    正在拼装的系统提示词
     * @param query     检索关键词（本轮用户输入）
     * @param firstTurn 是否为新对话的第一条消息
     */
    private void appendMemoryBlock(StringBuilder system, String query, boolean firstTurn) {
        // 只有首轮注入；后续轮次模型已经能从历史里看到这些记忆
        if (!firstTurn || query == null || query.isBlank()) {
            return;
        }
        if (!boolSetting("memory.enabled", true) || !boolSetting("memory.inject_enabled", true)) {
            return;
        }
        int topK = intSetting("memory.top_k", 5);
        int minImportance = intSetting("memory.min_importance", 1);

        List<String> lines = new ArrayList<>();
        try {
            Map<String, Object> result = memoryService.search(
                    new MemoryDtos.MemorySearchRequest(null, query, topK));
            Object rawHits = result.get("hits");
            if (!(rawHits instanceof List<?> hits)) {
                return;
            }
            for (Object element : hits) {
                if (!(element instanceof Map<?, ?> hit)) {
                    continue;
                }
                // 重要度不达标的记忆不注入：低价值记忆只会干扰模型
                // hit 是 Map<?, ?>，不能直接传 longOf(Map<String,Object>)，这里就地取值
                long importance = hit.get("importance") instanceof Number number
                        ? number.longValue()
                        : 0L;
                if (importance < minImportance) {
                    continue;
                }
                String content = stringOf(hit, "content");
                if (content.isBlank()) {
                    continue;
                }
                String category = stringOf(hit, "category");
                lines.add("- [" + (category.isBlank() ? "fact" : category) + "] " + content);
            }
        } catch (RuntimeException e) {
            // 记忆检索失败按「没有记忆」处理：这是增强能力，不能拖垮主流程
            log.warn("记忆注入失败，本轮按无记忆处理：{}", e.getMessage());
            return;
        }
        if (lines.isEmpty()) {
            return;
        }
        system.append("\n\n## 工作区记忆（用户此前确认过的偏好与事实，可直接引用）\n\n")
                .append(String.join("\n", lines));
    }

    /**
     * 追加「可用技能」段落（受 skill.enabled / skill.auto_inject 控制）。
     *
     * <p>只放「技能名 + 一行描述」，完整正文仍由模型用 {@code read_skill} 按需读取：
     * 几十个技能全文塞进来，提示词会直接爆掉。</p>
     *
     * @param system 正在拼装的系统提示词
     */
    private void appendSkillBlock(StringBuilder system) {
        if (!boolSetting("skill.enabled", true) || !boolSetting("skill.auto_inject", true)) {
            return;
        }
        List<String> lines = new ArrayList<>();
        try {
            Map<String, Object> snapshot = skillService.snapshot();
            Object rawSkills = snapshot.get("skills");
            if (!(rawSkills instanceof List<?> skills)) {
                return;
            }
            for (Object element : skills) {
                if (lines.size() >= MAX_INJECTED_SKILLS) {
                    break;
                }
                if (!(element instanceof Map<?, ?> skill)) {
                    continue;
                }
                // 被用户在设置里禁用的技能不提示：避免模型读到却调不动
                if (Boolean.FALSE.equals(skill.get("enabled"))) {
                    continue;
                }
                String name = stringOf(skill, "name");
                String description = stringOf(skill, "description");
                if (name.isBlank() || description.isBlank()) {
                    continue;
                }
                lines.add("- " + name + "：" + oneLine(description, MAX_SKILL_DESCRIPTION_CHARS));
            }
        } catch (RuntimeException e) {
            // 技能扫描失败按「没有技能」处理
            log.warn("技能注入失败，本轮按无技能处理：{}", e.getMessage());
            return;
        }
        if (lines.isEmpty()) {
            return;
        }
        system.append("\n\n## 可用技能（需要时先调用 read_skill 读取完整说明）\n\n")
                .append(String.join("\n", lines));
    }

    // ------------------------------------------------------------------ //
    // 用量记录与预算
    // ------------------------------------------------------------------ //

    /**
     * 记录一次模型调用的用量：写进本轮记录器（随 done 事件下发），并累加到预算熔断。
     *
     * @param sessionId 会话 id
     * @param recorder  本轮记录器
     * @param response  模型返回的完整响应（含 tokenUsage，可能为 null）
     */
    private void recordUsage(String sessionId, TurnRecorder recorder, ChatResponse response) {
        TokenUsage usage = response == null ? null : response.tokenUsage();
        long input = (usage == null || usage.inputTokenCount() == null) ? 0L : usage.inputTokenCount();
        long output = (usage == null || usage.outputTokenCount() == null) ? 0L : usage.outputTokenCount();

        // 单价来自模型清单；手写的新模型名查不到时按 0 计，费用显示 0 而不是报错
        LlmDtos.ModelInfo info = resolveModelInfo(recorder.model());
        double cost = (input * info.priceIn() + output * info.priceOut()) / 1_000_000.0;

        recorder.setUsage(Map.of(
                "input_tokens", input,
                "output_tokens", output,
                "total_tokens", input + output,
                "cost", round4(cost)));

        // 喂给预算熔断：下一次工具调用前它会据此判断是否越线
        toolBudgetRegistry.addUsage(sessionId, input, output, info.priceIn(), info.priceOut());
    }

    /**
     * 异步抽取本轮记忆（受 memory.enabled / memory.extract_enabled 控制）。
     *
     * @param sessionId 会话 id
     */
    private void scheduleMemoryExtraction(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return;
        }
        if (!boolSetting("memory.enabled", true) || !boolSetting("memory.extract_enabled", true)) {
            return;
        }
        memoryExtractExecutor.submit(() -> {
            try {
                memoryService.extract(new MemoryDtos.MemoryExtractRequest(sessionId, null));
            } catch (RuntimeException e) {
                // 抽取失败只记日志：它是一次「顺手」的额外调用，不能影响用户已经看到的回答
                log.warn("记忆抽取失败 sessionId={}：{}", sessionId, e.getMessage());
            }
        });
    }

    // ------------------------------------------------------------------ //
    // 小工具
    // ------------------------------------------------------------------ //

    /**
     * 取当前供应商 id。
     *
     * @return 供应商 id；设置为空时按 deepseek 兜底
     */
    private String providerId() {
        Object value = settingsRegistry.getSetting("llm.provider");
        return (value == null || String.valueOf(value).isBlank()) ? "deepseek" : String.valueOf(value);
    }

    /**
     * 取当前设置的模型名。
     *
     * @return 模型名；设置为空时为空串（调用方再用供应商默认模型兜底）
     */
    private String currentModelName() {
        Object value = settingsRegistry.getSetting("llm.model");
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 解析模型描述（窗口、单价）。查不到时返回一个「单价 0、窗口兜底」的描述。
     *
     * @param modelName 模型名；可为空
     * @return 模型描述；永不为 null
     */
    private LlmDtos.ModelInfo resolveModelInfo(String modelName) {
        String name = modelName == null ? "" : modelName;
        try {
            return llmProviderRegistry.resolveModel(providerId(), name);
        } catch (RuntimeException e) {
            // 手写的新模型名可能不在清单里：用量统计不该因此中断
            return new LlmDtos.ModelInfo(
                    name, name, DEFAULT_CONTEXT_WINDOW, true, false, 0.0, 0.0);
        }
    }

    /**
     * 取当前模型的上下文窗口。
     *
     * @return 窗口大小（token）；未知时返回兜底值
     */
    private int resolveContextWindow() {
        int window = resolveModelInfo(currentModelName()).contextWindow();
        return window > 0 ? window : DEFAULT_CONTEXT_WINDOW;
    }

    /**
     * 粗估一段文本占多少 token。
     *
     * @param text 文本
     * @return 估算 token 数（按 1 字符 ≈ 1 token）
     */
    private static int estimateTokens(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        // 按「1 字符 ≈ 1 token」粗估：中文接近真实值，英文偏高。
        // 宁可早一点触发压缩，也不要等供应商报 context length 错误。
        return text.length();
    }

    /**
     * 取消息主键（null 视为 0）。
     *
     * @param row 消息实体
     * @return 主键
     */
    private static long idOf(ChatMessage row) {
        return row.getId() == null ? 0L : row.getId();
    }

    /**
     * 把文本压成一行并截断。
     *
     * @param text     原始文本
     * @param maxChars 最大字符数
     * @return 单行文本
     */
    private static String oneLine(String text, int maxChars) {
        String oneLine = nvl(text).replaceAll("\\s+", " ").strip();
        return oneLine.length() <= maxChars ? oneLine : oneLine.substring(0, maxChars) + "…";
    }

    /**
     * 空字符串安全访问：null 转成空串。
     *
     * @param text 文本
     * @return 非 null 的文本
     */
    private static String nvl(String text) {
        return text == null ? "" : text;
    }

    /**
     * 把工具轨迹序列化成 JSON；空轨迹返回 null（数据库里就不存 "[]"）。
     *
     * @param traces 工具轨迹
     * @return JSON 字符串或 null
     */
    private String toolCallsJson(List<ChatDtos.ToolCallTrace> traces) {
        if (traces == null || traces.isEmpty()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(traces);
        } catch (Exception e) {
            // 序列化失败只丢轨迹，不能影响正文落库
            log.warn("工具轨迹序列化失败，本条消息不存轨迹：{}", e.getMessage());
            return null;
        }
    }

    /**
     * 读布尔设置。
     *
     * @param key      设置键
     * @param fallback 读取失败时的兜底值
     * @return 布尔值
     */
    private boolean boolSetting(String key, boolean fallback) {
        try {
            return Boolean.TRUE.equals(settingsRegistry.getSetting(key));
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    /**
     * 读整数设置。
     *
     * @param key      设置键
     * @param fallback 读取失败时的兜底值
     * @return 整数值
     */
    private int intSetting(String key, int fallback) {
        try {
            Object value = settingsRegistry.getSetting(key);
            return value instanceof Number number ? number.intValue() : fallback;
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    /**
     * 读浮点设置。
     *
     * @param key      设置键
     * @param fallback 读取失败时的兜底值
     * @return 浮点值
     */
    private double doubleSetting(String key, double fallback) {
        try {
            Object value = settingsRegistry.getSetting(key);
            return value instanceof Number number ? number.doubleValue() : fallback;
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    /**
     * 从 Map 里读 long（不存在或类型不对时返回 0）。
     *
     * @param map 数据来源
     * @param key 字段名
     * @return long 值
     */
    private static long longOf(Map<String, Object> map, String key) {
        if (map == null) {
            return 0L;
        }
        Object value = map.get(key);
        return value instanceof Number number ? number.longValue() : 0L;
    }

    /**
     * 从 Map 里读 double（不存在或类型不对时返回 0）。
     *
     * @param map 数据来源
     * @param key 字段名
     * @return double 值
     */
    private static double doubleOf(Map<String, Object> map, String key) {
        if (map == null) {
            return 0.0;
        }
        Object value = map.get(key);
        return value instanceof Number number ? number.doubleValue() : 0.0;
    }

    /**
     * 从 Map 里读字符串（不存在时返回空串）。
     *
     * @param map 数据来源
     * @param key 字段名
     * @return 去首尾空白后的字符串
     */
    private static String stringOf(Map<?, ?> map, String key) {
        if (map == null) {
            return "";
        }
        Object value = map.get(key);
        return value == null ? "" : String.valueOf(value).strip();
    }

    // ------------------------------------------------------------------ //
    // 内部数据载体
    // ------------------------------------------------------------------ //

    /**
     * 一轮补种上下文：最近消息 + 更早内容的摘要。
     *
     * @param recent  最近的消息（时间正序，不含本轮用户消息）
     * @param summary 更早内容的摘要；从未压缩过时为空串
     */
    private record SeedContext(
            // 最近的消息，按「最早 → 最新」排列
            List<ChatMessage> recent,
            // 更早内容的摘要；空串表示没有压缩过
            String summary
    ) {
    }

    /**
     * 会话摘要缓存项。
     *
     * @param lastMessageId 这段摘要覆盖到的最后一条消息 id
     * @param summary       摘要正文
     */
    private record SummaryCache(
            // 覆盖到的最后一条消息 id：id 相同说明没有新消息，可以复用摘要
            long lastMessageId,
            // 摘要正文
            String summary
    ) {
    }

    /**
     * 一条解析后的 `\doc` 指令。
     *
     * @param action help / list / delete / import / search / unknown
     * @param target 删除或导入的目标（文档名或文件路径）；其它动作为空串
     * @param query  检索问题；只在 action=search 时有值
     */
    private record DocCommand(
            // 动作：help / list / delete / import / search / unknown
            String action,
            // 删除或导入的目标
            String target,
            // 检索问题
            String query
    ) {
    }
}
