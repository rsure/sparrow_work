# Java 后端（backend_java）文档索引

本目录是 Java 后端的设计、集成与开发规范文档。
目标读者是**准备把 Python 后端仿写成 Java 后端的学习者**，默认你已了解 Spring Boot 基础，
但不要求你熟悉 LangChain4j / LangGraph4j。

> 👉 **如果你是 LangChain4j 新手，先看 [07-手把手实施计划](./07-手把手实施计划.md)。**
> 01~06 讲的是「设计成什么样」，07 讲的是「你今天动手要新建哪个文件、改哪个方法」，
> 每一段代码都能直接粘。看不懂 01~03 是正常的，从 07 开始，做完再回头看设计文档。

## 1. 阅读顺序

| 顺序 | 文档 | 先解决什么问题 |
| --- | --- | --- |
| 0 | [07-手把手实施计划](./07-手把手实施计划.md) | 我现在该做什么：全功能点打勾表 + 逐个文件的完整代码 + 验收命令 |
| 1 | [01-总体架构与集成方案](./01-总体架构与集成方案.md) | Java 后端长什么样，各层怎么分工，为什么这样选型 |
| 2 | [02-开发步骤与里程碑](./02-开发步骤与里程碑.md) | 先写哪一块、每块的验收标准是什么 |
| 3 | [03-LangChain4j与LangGraph4j集成指南](./03-LangChain4j与LangGraph4j集成指南.md) | 模型、工具、图、检查点、中断恢复、MCP、RAG 具体怎么写 |
| 4 | [04-AI代码生成规范](./04-AI代码生成规范.md) | 让 AI 生成的 Java 代码符合本仓库的注释与命名要求 |
| 5 | [05-API对照表](./05-API对照表.md) | Python 的每个接口在 Java 里对应哪个 Controller / 方法 |
| 6 | [06-Electron后端切换说明](./06-Electron后端切换说明.md) | 怎么让 Electron 在 Java / Python 后端之间切换 |

## 2. 当前完成度（2026-10 实测，按代码逐文件核对）

> 与旧版表格的区别：旧版写「实现返回 501」，那是**刚搭骨架时**的状态。
> 实际上除对话外的模块大多已经写完了，真正缺的集中在「对话链路」和 6 个空 Service。

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Maven 工程 / Spring Boot 启动 | ✅ | `backend_java/`，`mvnw` 已生成 |
| 统一响应 / 全局异常 / CORS | ✅ | `common/`、`config/` |
| 健康检查 | ✅ | `GET /api/health`，有 `HealthControllerTest` |
| 设置 / 密钥库 / 工作区 | ✅ | `SettingsServiceImpl`（37K，最大的一个实现） |
| 文件（目录/预览/搜索/原文） | ✅ | `FileServiceImpl` |
| RAG（文档增删查、检索、重建索引） | ✅ | `RagServiceImpl`（33K） |
| MCP（服务清单/重载/测试） | ✅ | `McpServiceImpl`（31K） |
| 技能（清单/重载/详情） | ✅ | `SkillServiceImpl` |
| 工具集（文件/命令/网络/RAG/技能/SQL） | ✅ | `tools/` 下 20+ 个工具，`DefaultToolRegistry` 做了重名与权限校验 |
| 工具运行时（权限/预算/审计/截断/插话） | ✅ | `ToolRuntime` 七道关卡已完整 |
| 模型注册表 | ✅ | `GET /api/llm/providers`、`POST /api/llm/probe` |
| 模型工厂（OpenAI 兼容） | ✅ | `OpenAiCompatibleLlmModelFactory` |
| 模型工厂（Anthropic / Gemini / Ollama） | ❌ | 供应商已在清单里声明，工厂类「待实现」（见 `LlmProviderRegistry.java:56,69`） |
| SQLite 业务表 | ✅ | `schema.sql`（`ddl-auto=update` 会自动补列） |
| LangGraph4j 检查点 Bean | ✅ | `AgentGraphConfig` 用 `SQLiteSaver`，但**还没有图在用它** |
| **对话 SSE（事件流）** | 🚧 | 只有 `ChatServiceImpl.stream()` 半成品：只发 `delta` 事件，前端不认识；`resume/stop/steer` 等 13 个方法是 `return null` |
| 轨迹 / 审计 / 记忆 / 扫描 / 命令 / 诊断 | ❌ | Controller 与 Service 接口在，**没有实现类**，调用返回 501 |
| Electron 目标切换 | ✅ | `backend.config.json`，默认 Java |
| 打包脚本 | ✅ | `pnpm run build:backend:java` |

逐项怎么做（含每个文件的完整代码）见 [07-手把手实施计划](./07-手把手实施计划.md)：
第 2 章是打勾表，第 3 章讲事件，第 4 章讲 resume/stop/steer，第 5 章讲 13 个空方法，第 6 章讲 6 个空 Service。


## 3. 三条硬性约定

1. **每个字段都要注释**：Java 字段用 Javadoc；record 用 `@param`；枚举常量用行尾注释。
2. **每个方法都要注释**：说明“为什么需要它、调用后发生什么”，不要只翻译方法名。
3. **每个 import 都要注释**：说明在本文件里承担什么职责。

完整可执行版本见 [04-AI代码生成规范](./04-AI代码生成规范.md)。

## 4. 一句话选型结论

Python 侧的核心是 **LangChain + LangGraph**；Java 侧对应选择：

- **LangChain4j** 负责模型、工具、RAG、MCP；
- **LangGraph4j** 负责状态图、检查点、中断/恢复；
- 不引入 Spring AI，避免把“图运行时”换成“只有 ChatClient 的客户端”。

FAISS 在 Java 侧没有官方 LangChain4j 构件，RAG 的第一版用
`InMemoryEmbeddingStore` 或自定义 `EmbeddingStore`，详见 03 文档。
