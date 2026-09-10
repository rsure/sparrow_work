# backend_java —— Spring Boot + LangChain4j + LangGraph4j 后端

这是 Python(FastAPI + LangChain/LangGraph) 后端的 Java 对照实现。
目标是**结构与接口对齐**，而不是逐行翻译：

| Python | Java |
| --- | --- |
| FastAPI + uvicorn | Spring Boot 3.5 + 内嵌 Tomcat |
| Pydantic | Java record + Jakarta Validation + Jackson |
| LangChain | LangChain4j |
| LangGraph / AsyncSqliteSaver | LangGraph4j / SQLiteSaver |
| SSE（sse-starlette） | Spring MVC `SseEmitter` |
| SQLAlchemy + Alembic | JdbcTemplate + `schema.sql`（后续可换 Flyway） |
| PyInstaller 单 exe | Spring Boot 可执行 jar + `jpackage`/`jlink` |

> 写代码前先读 [`../AGENTS.md`](../AGENTS.md) 与
> [`../doc/java_langchan_doc/04-AI代码生成规范.md`](../doc/java_langchan_doc/04-AI代码生成规范.md)。
> 每个字段、方法、重要判断、import 都必须有中文注释。

---

## 1. 环境要求

- **JDK 17+**（推荐 17 或 21；本项目按 17 编译）
- 不需要全局安装 Maven：仓库已带 Maven Wrapper（`mvnw.cmd` / `mvnw`）
- 首次运行 Wrapper 会从 Maven Central 下载 Maven 3.9.11（约 9MB）

检查版本：

```powershell
java -version
# 必须看到 17 或更高；如果仍是 1.8，请把 JAVA_HOME 指到 JDK 17
```

Windows 下临时切换：

```powershell
$env:JAVA_HOME = "C:\Path\To\jdk-17"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
```

> 国内网络如果 Maven 下载慢，可以在 `%USERPROFILE%\.m2\settings.xml` 里配置阿里云镜像；
> 不要把镜像仓库写进 `pom.xml`，否则会影响其他环境。

---

## 2. 启动与构建

```powershell
# 开发态启动（默认 8000 端口，接口前缀 /api）
cd backend_java
.\mvnw.cmd spring-boot:run

# 指定端口
.\mvnw.cmd spring-boot:run "-Dspring-boot.run.arguments=--server.port=9000"

# 打包成可执行 jar（产物 target/backend-java.jar）
.\mvnw.cmd -DskipTests package

# 运行 jar
java -Dfile.encoding=UTF-8 -jar target/backend-java.jar
```

验证：

```powershell
curl http://127.0.0.1:8000/api/health
```

期望响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "ok",
    "service": "vue3-electron-fastapi-java",
    "runtime": "Java",
    "runtime_version": "17.x"
  }
}
```

---

## 3. 目录结构

```text
backend_java/
├─ pom.xml                         # Maven 依赖与构建
├─ mvnw / mvnw.cmd                 # Maven Wrapper（无需全局 Maven）
├─ src/main/java/com/example/backendjava/
│  ├─ BackendJavaApplication.java  # 启动类（根包只放它）
│  ├─ controller/                  # HTTP 接口层：14 个 XxxController，只做协议适配
│  ├─ service/                     # 业务层接口与业务契约
│  │  ├─ XxxService.java           # 各域业务接口（多数待实现）
│  │  ├─ AgentRuntime.java         # Agent 图运行时接口
│  │  ├─ AgentEventSink.java       # Agent 事件出口（SSE / 落库由调用方决定）
│  │  ├─ AgentTool / ToolRegistry  # 工具契约与工具注册表
│  │  └─ LlmModelFactory / Router  # 模型装配扩展点与路由
│  │  └─ impl/                     # 业务实现：SettingsServiceImpl、DefaultLlmService、
│  │                               #   OpenAiCompatibleLlmModelFactory
│  ├─ dto/                         # 请求/响应结构：每域一个 XxxDtos 容器
│  │                               #   + HealthData / LlmModelSpec / ToolResult
│  ├─ entity/                      # 数据实体（当前为空：表结构在 schema.sql，用 JdbcTemplate 直读）
│  ├─ config/                      # AppProperties / CorsConfig / ParentProcessGuard / GraphConfig
│  ├─ common/                      # ApiResponse / PageResult / ApiException /
│  │                               #   GlobalExceptionHandler / ToolPolicy
│  └─ util/                        # ServiceSupport：Service 未实现时统一返回 501
├─ src/main/resources/
│  ├─ application.yml              # 端口、数据源、上下文路径、app.*
│  ├─ schema.sql                   # SQLite 业务表
│  └─ prompts/system-prompt.md     # 主 Agent 系统提示词模板
└─ src/test/java/.../controller/HealthControllerTest.java
```

> 为什么 `entity` 是空的：本工程不用 ORM，建表语句集中在 `schema.sql`，
> Service 实现需要持久化时直接注入 `JdbcTemplate` 读写表。
> 以后若引入 JPA/MyBatis，实体类就放这个包。

---

## 4. 已实现 / 待实现

**已实现（可直接运行）**

- `GET /api/health`：健康检查，Electron 探活依赖它
- `GET /api/llm/providers`：内置供应商与模型清单
- `POST /api/llm/probe`：OpenAI 兼容端点（OpenAI / DeepSeek / 自定义中转）连通性测试
- SQLite 业务表初始化（`schema.sql`）
- LangGraph4j `SQLiteSaver` 检查点 Bean（`AgentGraphConfig`）
- 全局 CORS、统一响应、全局异常处理、父进程守护

**待实现（接口已给出，Controller 返回 501）**

- `ChatService`：SSE 对话、工具循环、中断/恢复、会话历史、用量统计
- `ScanServiceImpl`：扫描任务、SSE 进度
- `RagService`：文档解析、切块、向量化、检索
- `SettingsService`：设置读写、工作区、密钥
- `SkillService` / `McpService` / `MemoryService` / `TraceService`
- `AuditService` / `FileService` / `DiagnosticService` / `CommandService`

实现任何一个接口时，只要加一个 `@Service` 实现类，Controller 会自动找到它，
不需要修改 Controller 或注册表。

---

## 5. 配置

`application.yml` 中的关键项都可以用环境变量覆盖：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_HOST` | `127.0.0.1` | 监听地址 |
| `APP_PORT` | `8000` | 监听端口，必须与 Electron 一致 |
| `APP_APP_NAME` | `vue3-electron-fastapi-java` | `/api/health` 返回的服务名 |
| `APP_VERSION` | `0.1.0` | 版本号 |
| `APP_ENV` | `development` | 运行环境 |
| `APP_DB_PATH` | `app.db` | 业务 SQLite 文件 |
| `APP_CHECKPOINT_DB_PATH` | `app.db` | LangGraph4j 检查点 SQLite 文件 |
| `APP_PARENT_GUARD` | 未设置 | 设为 `1` 时启用 stdin 父进程守护（Electron 自动注入） |

---

## 6. 重要限制

1. **FAISS 没有官方 LangChain4j 构件**。Maven Central 上没有 `langchain4j-faiss`，
   本工程默认用 LangChain4j 的 `InMemoryEmbeddingStore`，或由你实现一个
   `EmbeddingStore` 适配器。详见 `doc/java_langchan_doc/03-...md`。
2. **中断粒度是节点级**。LangGraph4j 的 `interruptBefore/After` 作用在节点边界；
   Python 侧“在工具内部调用 interrupt()”的写法需要包一层确认节点，或走应用层
   pending_action 表。
3. **当前机器可能只有 JDK 8**。启动前务必确认 `JAVA_HOME` 指向 JDK 17+，
   否则会出现 `UnsupportedClassVersionError`。

---

## 7. 相关文档

- [总体架构与集成方案](../doc/java_langchan_doc/01-总体架构与集成方案.md)
- [开发步骤与里程碑](../doc/java_langchan_doc/02-开发步骤与里程碑.md)
- [LangChain4j 与 LangGraph4j 集成指南](../doc/java_langchan_doc/03-LangChain4j与LangGraph4j集成指南.md)
- [AI 代码生成规范](../doc/java_langchan_doc/04-AI代码生成规范.md)
- [API 对照表](../doc/java_langchan_doc/05-API对照表.md)
- [Electron 后端切换说明](../doc/java_langchan_doc/06-Electron后端切换说明.md)
