# 03 · LangChain4j 与 LangGraph4j 集成指南

> 本文给出可直接照抄的骨架代码（省略了与本主题无关的 import 注释，
> 实际写进仓库时请按 [04-AI代码生成规范](./04-AI代码生成规范.md) 给每条 import 补注释）。
>
> 版本：LangChain4j `1.22.0`、LangGraph4j `1.9.6`、Spring Boot `3.5.16`、JDK 17。

---

## 1. 依赖关系

```xml
<!-- LangChain4j 核心：ChatModel / StreamingChatModel / EmbeddingModel / Tool 注解 -->
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j</artifactId>
</dependency>

<!-- OpenAI 兼容协议：OpenAI、DeepSeek、自定义中转站 -->
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j-open-ai</artifactId>
</dependency>

<!-- 其它供应商（按需实现工厂） -->
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j-anthropic</artifactId>
</dependency>
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j-google-ai-gemini</artifactId>
</dependency>
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j-ollama</artifactId>
</dependency>

<!-- MCP 客户端（beta 版本，需单独指定版本） -->
<dependency>
  <groupId>dev.langchain4j</groupId>
  <artifactId>langchain4j-mcp</artifactId>
  <version>1.22.0-beta32</version>
</dependency>

<!-- LangGraph4j：图运行时、LangChain4j 适配、SQLite 检查点 -->
<dependency>
  <groupId>org.bsc.langgraph4j</groupId>
  <artifactId>langgraph4j-core</artifactId>
</dependency>
<dependency>
  <groupId>org.bsc.langgraph4j</groupId>
  <artifactId>langgraph4j-langchain4j</artifactId>
</dependency>
<dependency>
  <groupId>org.bsc.langgraph4j</groupId>
  <artifactId>langgraph4j-sqlite-saver</artifactId>
</dependency>
```

版本由 `pom.xml` 里的两个 BOM 统一管理：

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>dev.langchain4j</groupId>
      <artifactId>langchain4j-bom</artifactId>
      <version>1.22.0</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
    <dependency>
      <groupId>org.bsc.langgraph4j</groupId>
      <artifactId>langgraph4j-bom</artifactId>
      <version>1.9.6</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

---

## 2. 模型：ChatModel 与 StreamingChatModel

### 2.1 同步模型

```java
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.openai.OpenAiChatModel;

ChatModel model = OpenAiChatModel.builder()
        .baseUrl("https://api.deepseek.com/v1") // 末尾不要带斜杠
        .apiKey(apiKey)
        .modelName("deepseek-flash")
        .temperature(0.0)
        .maxTokens(2048)
        .build();

ChatResponse response = model.chat("用一句话解释什么是 RAG");
String text = response.aiMessage().text();
```

- `ChatModel.chat(String)` 是最简入口；
- 需要多轮消息/工具时用 `chat(ChatRequest)`；
- `ChatResponse.aiMessage().text()` 取文本；
- `ChatResponse.tokenUsage()` 取 token 用量（可能为 null）。

### 2.2 流式模型

```java
import dev.langchain4j.model.chat.StreamingChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.chat.response.StreamingChatResponseHandler;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.openai.OpenAiStreamingChatModel;

StreamingChatModel streaming = OpenAiStreamingChatModel.builder()
        .baseUrl("https://api.deepseek.com/v1")
        .apiKey(apiKey)
        .modelName("deepseek-flash")
        .temperature(0.0)
        .build();

streaming.chat(
        ChatRequest.builder()
                .messages(UserMessage.from("讲一个程序员笑话"))
                .build(),
        new StreamingChatResponseHandler() {
            @Override
            public void onPartialResponse(String partial) {
                // 每个 token / 小块文本到达时回调；这里写 SSE
            }

            @Override
            public void onCompleteResponse(ChatResponse complete) {
                // 生成结束；complete.aiMessage().text() 是完整文本，tokenUsage() 是真实用量
            }

            @Override
            public void onError(Throwable error) {
                // 网络/鉴权/模型错误
            }
        });
```

> 注意：`onPartialResponse` 可能一次给你多个字符（不同供应商的切块粒度不同），
> 不要假设“一次回调 = 一个汉字”。

### 2.3 多供应商工厂

本工程已实现的扩展点：

```java
public interface LlmModelFactory {
    boolean supports(String providerId);
    ChatModel createChatModel(LlmModelSpec spec);
    StreamingChatModel createStreamingModel(LlmModelSpec spec);
}
```

- `OpenAiCompatibleLlmModelFactory` 已支持 `openai` / `deepseek` / `custom-*`；
- 新增 Anthropic：

```java
@Component
public class AnthropicLlmModelFactory implements LlmModelFactory {
    @Override
    public boolean supports(String providerId) {
        return "anthropic".equals(providerId);
    }

    @Override
    public ChatModel createChatModel(LlmModelSpec spec) {
        return AnthropicChatModel.builder()
                .apiKey(spec.apiKey())
                .modelName(spec.model())
                .temperature(spec.temperature())
                .maxTokens(spec.maxTokens())
                .build();
    }

    @Override
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        return AnthropicStreamingChatModel.builder()
                .apiKey(spec.apiKey())
                .modelName(spec.model())
                .temperature(spec.temperature())
                .maxTokens(spec.maxTokens())
                .build();
    }
}
```

- Gemini：`GoogleAiGeminiChatModel` / `GoogleAiGeminiStreamingChatModel`；
- Ollama：`OllamaChatModel` / `OllamaStreamingChatModel`。

具体 builder 方法以对应模块的源码为准；原则是**只从 `LlmModelSpec` 取值**，
不要在工厂里读环境变量或数据库。

---

## 3. 工具调用

### 3.1 声明式：@Tool + AiServices

```java
import dev.langchain4j.agent.tool.Tool;

public class FileTools {

    @Tool("列出目录下的文件；path 必须是绝对路径")
    public String listDir(String path) {
        // 返回字符串；模型会把它当作工具结果
        return "...";
    }
}
```

```java
import dev.langchain4j.service.AiServices;

interface Assistant {
    String chat(String userMessage);
}

Assistant assistant = AiServices.builder(Assistant.class)
        .chatModel(model)
        .tools(new FileTools())
        .build();

String answer = assistant.chat("看看 D:/docs 下有什么");
```

- `@Tool` 的描述会被模型用来决定是否调用；
- 参数类型要简单（String / int / boolean / 简单对象），复杂对象需要写清楚 JSON 结构；
- 工具抛异常会被框架转成错误结果，但最好自己捕获并返回 `FAIL: ...`。

### 3.2 图内工具：LC4jToolService

LangGraph4j 与 LangChain4j 的桥接模块提供 `LC4jToolService`：

```java
import org.bsc.langgraph4j.langchain4j.tool.LC4jToolService;

LC4jToolService toolService = LC4jToolService.builder()
        .toolsFromObject(new FileTools())
        .build();

// 给模型看的工具描述
var specs = toolService.toolSpecifications();

// 执行模型返回的工具调用请求
var command = toolService.execute(
        toolExecutionRequests,   // List<ToolExecutionRequest>
        invocationContext,
        "messages"               // 把工具结果写回 state 的哪个键
).join();
```

本工程的 `service/AgentTool` 是**领域接口**，实现后可以：
- 用 `LC4jToolService.builder().toolsFromObject(...)` 直接挂到图；
- 或自己把 `AgentTool.execute(Map)` 包成 `ToolExecutor`。

### 3.3 工具策略

```java
public enum ToolPolicy {
    READ_ONLY, WRITE, EXECUTE, NETWORK, DATABASE;

    public boolean requiresConfirmation() {
        return this == WRITE || this == EXECUTE || this == DATABASE;
    }
}
```

建图时按策略分流：

```text
agent 节点 → 模型返回 toolCalls
  ├─ 全部 READ_ONLY → tools 节点直接执行
  └─ 含 WRITE/EXECUTE → confirm 节点（触发中断）→ 用户确认 → tools 节点
```

---

## 4. LangGraph4j：建图

### 4.1 状态

最简单的状态是 `MessagesState<ChatMessage>`：

```java
import org.bsc.langgraph4j.prebuilt.MessagesState;
import dev.langchain4j.data.message.ChatMessage;

// MessagesState.SCHEMA 定义了 messages 键使用“追加”通道
var graph = new StateGraph<MessagesState<ChatMessage>>(
        MessagesState.SCHEMA,
        MessagesState::new
);
```

需要额外字段（如 `approved`、`pending_action`）时：

- 用 `StateGraph(Map<String, Channel<?>> channels, AgentStateFactory<State>)` 自定义 schema；
- 或继承 `AgentState`，在 `data()` 里读写。

### 4.2 节点与边

```java
import org.bsc.langgraph4j.GraphDefinition;
import org.bsc.langgraph4j.StateGraph;
import org.bsc.langgraph4j.action.AsyncNodeAction;

var graph = new StateGraph<MessagesState<ChatMessage>>(
        MessagesState.SCHEMA,
        MessagesState::new
)
.addNode("agent", AsyncNodeAction.node_async(this::agentNode))
.addNode("tools", AsyncNodeAction.node_async(this::toolsNode))
.addNode("confirm", AsyncNodeAction.node_async(this::confirmNode))
.addEdge(GraphDefinition.START, "agent")
.addConditionalEdges("agent", this::routeAfterAgent, Map.of(
        "tools", "tools",
        "confirm", "confirm",
        "end", GraphDefinition.END
))
.addEdge("tools", "agent")
.addEdge("confirm", "agent");
```

节点方法签名：

```java
private Map<String, Object> agentNode(MessagesState<ChatMessage> state) {
    // 1) 取消息
    var messages = state.messages();
    // 2) 调模型
    ChatResponse response = model.chat(ChatRequest.builder().messages(messages).build());
    // 3) 返回“状态增量”；messages 是追加通道，所以只放新消息
    return Map.of("messages", List.of(response.aiMessage()));
}
```

### 4.3 条件边

```java
private AsyncCommandAction<MessagesState<ChatMessage>> routeAfterAgent() {
    return (state, config) -> {
        var last = state.lastMessage().orElseThrow();
        if (last instanceof AiMessage ai && ai.hasToolExecutionRequests()) {
            return CompletableFuture.completedFuture(new Command("tools"));
        }
        return CompletableFuture.completedFuture(new Command(GraphDefinition.END));
    };
}
```

> 具体 `Command` 的构造方式以 1.9.6 源码为准；核心思想是“返回下一个节点名”。

### 4.4 编译

```java
import org.bsc.langgraph4j.CompileConfig;
import org.bsc.langgraph4j.CompiledGraph;

CompiledGraph<MessagesState<ChatMessage>> compiled = graph.compile(
        CompileConfig.builder()
                .checkpointSaver(saver)
                .recursionLimit(25)
                .interruptBefore("confirm")
                .build()
);
```

`recursionLimit` 对应 Python 的 `max_iterations`；太小会在多轮工具调用时抛异常。

---

## 5. 检查点：SQLiteSaver

本工程的 `AgentGraphConfig` 已经装配好：

```java
@Bean
public BaseCheckpointSaver checkpointSaver(AppProperties properties) throws Exception {
    var serializer = new LC4jJacksonStateSerializer<AgentState>(AgentState::new);
    return SQLiteSaver.builder()
            .databasePath(properties.getCheckpointDbPath())
            .createTables(true)
            .stateSerializer(serializer)
            .build();
}
```

使用：

```java
var config = RunnableConfig.builder()
        .threadId(sessionId)   // 会话 id 就是 threadId
        .build();

compiled.invoke(Map.of("messages", List.of(UserMessage.from("你好"))), config);

// 读取当前状态
var snapshot = compiled.getState(config);
// 读取历史
var history = compiled.getStateHistory(config);
```

`SQLiteSaver` 会自己创建检查点表；不要用业务表替代它。

---

## 6. 中断与恢复（HITL）

### 6.1 静态中断

```java
CompileConfig.builder()
        .checkpointSaver(saver)
        .interruptBefore("confirm")   // 执行到 confirm 节点之前暂停
        .build();
```

流程：

```text
graph.stream(inputs, config)
  → 执行到 confirm 前暂停
  → ChatService 发 confirm_required 事件
  → 前端 POST /api/chat/resume
  → graph.stream(GraphInput.resume(Map.of("approved", true)), config)
  → 从 confirm 节点继续
```

### 6.2 动态中断

`InterruptibleAction` 可以在节点执行前后根据状态决定是否暂停：

```java
public class ConfirmAction implements InterruptibleAction<MessagesState<ChatMessage>> {
    @Override
    public Optional<InterruptionMetadata<MessagesState<ChatMessage>>> interrupt(
            String nodeId,
            MessagesState<ChatMessage> state,
            RunnableConfig config
    ) {
        if (需要确认(state)) {
            return Optional.of(
                    InterruptionMetadata.builder(nodeId, state)
                            .reason("write_file 需要用户确认")
                            .build()
            );
        }
        return Optional.empty();
    }
}
```

### 6.3 关键约束

1. **threadId 必须一致**：首次执行与恢复用同一个 `sessionId`；
2. **中断在节点边界**：不是在工具方法内部；
3. **恢复前可以改状态**：用 `graph.updateState(config, values, asNode)`；
4. **前端必须保存 interrupt_id**：恢复时校验，避免恢复错现场。

### 6.4 Python 与 Java 的差异

| Python | Java |
| --- | --- |
| 工具内部 `interrupt()` | 把工具包成 confirm 节点，或用应用层 pending_action 表 |
| `Command(resume=...)` | `GraphInput.resume(Map.of(...))` |
| `AsyncSqliteSaver` | `SQLiteSaver` |
| `thread_id` | `RunnableConfig.threadId(...)` |
| `astream_events` | `compiled.stream(...)` + `NodeOutput` |

---

## 7. SSE 集成

### 7.1 Controller

```java
@PostMapping("/stream")
public SseEmitter stream(@Valid @RequestBody ChatDtos.ChatRequest request) {
    return ServiceSupport.require(chatService, "对话服务").stream(request.withDefaults());
}
```

### 7.2 Service 内部

```java
SseEmitter emitter = new SseEmitter(0L); // 0 = 不超时

try {
    emitter.send(SseEmitter.event().name("token").data(Map.of("text", "你")));
} catch (IOException e) {
    // 客户端断开：停止生成、释放资源
    emitter.completeWithError(e);
    return emitter;
}

// 结束
emitter.complete();
```

### 7.3 事件协议

与 Python 侧保持一致：

```text
event: thinking
data: {"stage":"正在理解问题"}

event: token
data: {"text":"你"}

event: tool_start
data: {"name":"read_file","input":{"path":"D:/a.md"}}

event: tool_end
data: {"name":"read_file","ok":true,"elapsed":0.03}

event: confirm_required
data: {"interrupt_id":"...","action":"write_file","preview":"..."}

event: done
data: {"session_id":"...","answer":"...","usage":{...}}

event: error
data: {"message":"..."}
```

### 7.4 并发

- 同一 `sessionId` 同时只允许一条流：用 `ConcurrentHashMap<String, RunState>`；
- `RunState` 里放 `AtomicBoolean cancelled`、`SseEmitter`、当前工具名；
- `/chat/stop` 置位 `cancelled`，流在下一个检查点退出并发送 `stopped`。

---

## 8. MCP

### 8.1 stdio 客户端

```java
import dev.langchain4j.mcp.client.DefaultMcpClient;
import dev.langchain4j.mcp.client.transport.stdio.StdioMcpTransport;

var transport = StdioMcpTransport.builder()
        .command(List.of("npx", "-y", "@modelcontextprotocol/server-filesystem", "D:/docs"))
        .build();

var client = DefaultMcpClient.builder()
        .transport(transport)
        .clientName("backend-java")
        .clientVersion("0.1.0")
        .build();

var tools = client.listTools();
```

### 8.2 HTTP / SSE

```java
import dev.langchain4j.mcp.client.transport.http.StreamableHttpMcpTransport;

var transport = StreamableHttpMcpTransport.builder()
        .url("http://127.0.0.1:3001/mcp")
        .build();
```

### 8.3 挂到 Agent

```java
var toolService = LC4jToolService.builder()
        .tool(mcpClient)   // 直接把 MCP 工具加进工具表
        .build();
```

### 8.4 失败隔离

- 单个 server 连接失败只记录日志，不影响内置工具；
- 工具名加 server 前缀，避免冲突；
- 配置变更后 `reload`，并清空 Agent 缓存。

---

## 9. RAG

### 9.1 组件

| 阶段 | LangChain4j 组件 |
| --- | --- |
| 解析 | `DocumentParser`（PDFBox / POI / Tika，按需加依赖） |
| 切块 | `DocumentSplitter` / `DocumentSplitters.recursive(...)` |
| 向量化 | `EmbeddingModel` |
| 存储 | `EmbeddingStore`（`InMemoryEmbeddingStore` 或自定义） |
| 检索 | `EmbeddingStoreContentRetriever` |

### 9.2 最简链路

```java
EmbeddingModel embeddingModel = ...;
EmbeddingStore<TextSegment> store = new InMemoryEmbeddingStore<>();

List<Document> documents = ...;
DocumentSplitter splitter = DocumentSplitters.recursive(500, 80);
List<TextSegment> segments = splitter.split(documents);
List<Embedding> embeddings = embeddingModel.embedAll(segments).content();
store.addAll(embeddings, segments);

EmbeddingStoreContentRetriever retriever =
        EmbeddingStoreContentRetriever.builder()
                .embeddingStore(store)
                .embeddingModel(embeddingModel)
                .maxResults(10)
                .minScore(0.6)
                .build();
```

### 9.3 FAISS 说明

- Maven Central 上没有 `dev.langchain4j:langchain4j-faiss`；
- 不要照搬 Python 的 `faiss_index/`；
- 第一版建议 `InMemoryEmbeddingStore`：
  - 启动时从 `rag_chunk` 读向量重建；
  - 适合教学与单机小数据；
- 数据量大时：
  - 换 Milvus / Elasticsearch / Qdrant；
  - 或自己实现 `EmbeddingStore`，把向量存 SQLite BLOB。

### 9.4 维度一致性

更换 embedding 模型后，向量维度可能变化；必须重建全部向量，
否则余弦相似度没有意义。建议在 `rag_meta` 或 `app_settings` 里记录
`embedding_model` 与 `dimension`，入库前校验。

---

## 10. 测试

### 10.1 模型工厂

不要真的请求网络；用假的 `ChatModel`：

```java
ChatModel fake = new ChatModel() {
    @Override
    public ChatResponse doChat(ChatRequest request) {
        return ChatResponse.builder()
                .aiMessage(AiMessage.from("pong"))
                .build();
    }
};
```

### 10.2 图

- 用 `MemorySaver` 代替 SQLiteSaver，测试更快；
- 用固定 `threadId` 验证暂停/恢复；
- 用 `graph.getState(config)` 断言 `next` 节点。

### 10.3 SSE

- `MockMvc` 的 `asyncDispatch` 可以读事件流；
- 或起随机端口，用 `WebTestClient` 订阅。

---

## 11. 常见坑

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `UnsupportedClassVersionError` | 用了 JDK 8 | `JAVA_HOME` 指向 17+ |
| 401 / `No OpenAiApi instance` | 密钥或 baseUrl 不对 | 打印最终请求 URL，检查 `/v1` 是否重复 |
| `404 /chat/completions` | baseUrl 末尾多了 `/v1` 或斜杠 | baseUrl 只给到 `/v1`，不要带 `/chat/completions` |
| 中断后恢复从头发车 | `threadId` 不一致 | 首次与恢复用同一个 `sessionId` |
| `database is locked` | SQLite 多连接写 | Hikari `maximum-pool-size=1` |
| 中文日志乱码 | Windows 控制台 GBK | `-Dfile.encoding=UTF-8` |
| Maven 首次启动超时 | 下载依赖慢 | `startupTimeoutMs=180000`；先跑 `pnpm run setup:java` |
| 工具调用死循环 | 模型反复调用同一工具 | `recursionLimit` + 系统提示词约束 + 工具结果写清 FAIL |
| 子 Agent 写了文件 | 工具作用域没过滤 | `ToolRegistry.listForScope(true)` 只返回 READ_ONLY |

---

## 12. 推荐的学习路径

1. 先跑通 `OpenAiChatModel.chat("ping")`；
2. 再跑通 `StreamingChatModel` + 控制台打印 token；
3. 再写一个 `@Tool`，用 `AiServices` 调一次；
4. 再建一张只有 `agent → END` 的图；
5. 再加 `tools` 节点与条件边；
6. 再加 `SQLiteSaver`；
7. 最后加 `interruptBefore("confirm")` 与恢复；
8. 每一步都写测试，不要一次写完再调。
