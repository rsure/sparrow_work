# 03 · Java / Spring Boot 后端卷（JV-01 ~ JV-40）

> **本卷定位**：一面技术面用。面试官照着念、照着追问；候选人 1~3 年经验。
> **全部题目锚定本仓库真实代码**：`backend_java/`（Spring Boot 3 + LangChain4j 1.22 + SQLite），对照组素材来自 `backend/app/`（FastAPI + LangGraph）。
> 锚点里的 `.../` 是包路径省略（`backend_java/...` 即 `backend_java/src/main/java/com/example/backendjava`），**类名与方法名都是真的**，行号以当前工作副本为准，代码改动后可能漂移 1~3 行。
> 本卷不出「提示词该怎么写」的题，那部分在 `05-prompt.md`。

## 一、卷面构成

| 块 | 题号 | 题数 | 考什么 |
| --- | --- | --- | --- |
| A. AI 服务端化 | JV-01 ~ JV-16 | 16 | LangChain4j / LangGraph4j 装配、SseEmitter 并发、工具权限、预算记账、记忆窗口、密钥与设置表 |
| B. 双后端对照 | JV-17 ~ JV-28 | 12 | 同一能力在 Python（LangGraph）与 Java（LangChain4j）的差异与一致性 |
| C. Java / Spring 通用 | JV-29 ~ JV-40 | 12 | 分层、统一返回体、异常处理、事务、并发容器、record/枚举、测试 |

## 二、分堆规则（面试现场怎么用）

- **必答 12 道**：开场 15 分钟内问完，判断「能不能上手这个后端」。
- **抽答 20 道**：按候选人简历方向挑 5~8 道，AI 经验多的多问 A/B 块，纯业务后端多的多问 C 块。
- **加分 8 道**：前两堆答得顺再问，用来分辨「背过」和「真读过并发/框架源码」。
- **难度配额**：L1 = 6 道（热身）、L2 = 27 道（主体）、L3 = 7 道（加分位，全部落在加分堆）。L3 上限 8 道，本卷用 7 道。

## 三、40 题速查表

| 题号 | 难度 | 题型 | 分堆 | 锚点 |
| --- | --- | --- | --- | --- |
| JV-01 | L1 | 基础 | 必答 | `backend_java/src/main/resources/application.yml:12` |
| JV-02 | L2 | 找坑 | 必答 | `backend_java/.../chat/runtime/StreamingTurn.java:73-107` |
| JV-03 | L2 | 读代码 | 必答 | `backend_java/.../chat/event/SseAgentEventSink.java:25-60` |
| JV-04 | L2 | 设计 | 必答 | `backend_java/.../tools/AbstractGuardedTool.java:71-99` |
| JV-05 | L2 | 读代码 | 必答 | `backend_java/.../tools/ToolBudgetRegistry.java:89-156` |
| JV-06 | L1 | 基础 | 必答 | `backend_java/.../service/impl/ChatServiceImpl.java:1655-1697` |
| JV-07 | L2 | 找坑 | 抽答 | `backend_java/.../tools/OutputContract.java:100-190` |
| JV-08 | L3 | 找坑 | 加分 | `backend_java/.../tools/PathLock.java:38-159` |
| JV-09 | L2 | 读代码 | 抽答 | `backend_java/.../tools/PathPolicy.java:57-115` |
| JV-10 | L2 | 设计 | 抽答 | `backend_java/.../settings/SecretStore.java:64-215` |
| JV-11 | L2 | 读代码 | 抽答 | `backend_java/.../settings/SettingsRegistry.java:118-210` |
| JV-12 | L3 | 找坑 | 加分 | `backend_java/.../tools/ToolRuntime.java:100-160` |
| JV-13 | L2 | 读代码 | 抽答 | `backend_java/.../chat/runtime/ChatSessionBus.java:248-290` |
| JV-14 | L3 | 设计 | 加分 | `backend_java/.../service/impl/ChatServiceImpl.java:1539-1600` |
| JV-15 | L2 | 读代码 | 抽答 | `backend_java/.../chat/runtime/ChatToolExecutor.java:87-130` |
| JV-16 | L2 | 设计 | 抽答 | `backend_java/.../tools/ToolPolicyRegistry.java:39-60`、`:183-257` |
| JV-17 | L2 | 读代码 | 必答 | `backend_java/.../service/impl/ChatServiceImpl.java:1079-1086` + `backend/app/controllers/chat_controller.py:1067-1100` |
| JV-18 | L3 | 找坑 | 加分 | `backend/app/controllers/chat_controller.py:1106-1171` + `backend_java/.../service/impl/ChatServiceImpl.java:1539-1600` |
| JV-19 | L2 | 设计 | 必答 | `backend/app/llm/state.py:1-19` + `backend_java/.../service/impl/ChatServiceImpl.java:691-697` |
| JV-20 | L2 | 读代码 | 必答 | `backend_java/.../service/impl/ChatServiceImpl.java:1655` + `backend/app/services/context_manager.py:1-22` |
| JV-21 | L2 | 找坑 | 抽答 | `backend/app/services/context_manager.py:66-84` + `backend_java/.../service/impl/ChatServiceImpl.java:1926` |
| JV-22 | L2 | 读代码 | 抽答 | `backend/app/agents/rag_agent.py:184-201`、`:211-258` |
| JV-23 | L2 | 找坑 | 抽答 | `backend/app/services/context_manager.py:13-22` + `backend_java/.../service/impl/ChatServiceImpl.java:1699-1730` |
| JV-24 | L2 | 设计 | 抽答 | `backend_java/.../settings/SecretStore.java:46-66` + `backend/app/services/secrets.py` |
| JV-25 | L3 | 设计 | 加分 | `backend/app/agents/rag_agent.py:204-208` + `backend_java/.../tools/ToolPolicyRegistry.java:324` |
| JV-26 | L1 | 基础 | 抽答 | `backend_java/.../common/PageLimits.java:28-99` |
| JV-27 | L1 | 基础 | 抽答 | `backend_java/.../chat/event/SseAgentEventSink.java:51-77` |
| JV-28 | L2 | 找坑 | 抽答 | `backend_java/.../controller/ChatController.java:46-58` |
| JV-29 | L1 | 基础 | 必答 | `backend_java/.../common/ApiResponse.java:12-52` |
| JV-30 | L2 | 读代码 | 必答 | `backend_java/.../common/GlobalExceptionHandler.java:44-184` |
| JV-31 | L2 | 找坑 | 必答 | `backend_java/.../util/ServiceSupport.java:32-42` |
| JV-32 | L2 | 找坑 | 抽答 | `backend_java/.../dto/ChatDtos.java:56-118` |
| JV-33 | L1 | 基础 | 抽答 | `backend_java/.../controller/ChatController.java:55`、`:78-81`、`:144-155` |
| JV-34 | L2 | 读代码 | 抽答 | `backend_java/.../chat/runtime/ChatPersistence.java:62-130` |
| JV-35 | L2 | 设计 | 抽答 | `backend_java/.../settings/SettingsRegistry.java:197-210` |
| JV-36 | L2 | 读代码 | 抽答 | `backend_java/.../chat/runtime/TurnRecorder.java` + `ChatSessionBus.java:88-145` |
| JV-37 | L3 | 找坑 | 加分 | `backend_java/src/main/resources/application.yml:22-30` |
| JV-38 | L2 | 读代码 | 抽答 | `backend_java/.../llm/LlmModelFactoryRouter.java` |
| JV-39 | L2 | 设计 | 加分 | `backend_java/src/test/.../controller/PageLimitContractTest.java` |
| JV-40 | L3 | 设计 | 加分 | `backend_java/.../config/AgentGraphConfig.java:95` |

---

## A. AI 服务端化（JV-01 ~ JV-16）

### JV-01｜L1｜基础｜必答｜锚点 `backend_java/src/main/resources/application.yml:12`

**题**：这个后端的 `application.yml` 里为什么一行模型配置都没有？

**口语答案**：这是桌面应用，模型供应商、baseUrl、模型名、温度、max_tokens 全都是用户在自己机器上随时切换的东西，写进 yml 就等于写死在安装包里，改一次要重启、还要重新打包。所以配置全部落在 SQLite 的设置表里，由 `SettingsRegistry` 管默认值和校验，每次请求再由 `ChatServiceImpl.buildModelSpec()` 读出来拼一个 `LlmModelSpec`。密钥更不可能进配置文件——它在 `SecretStore` 里加密落库。yml 里只剩服务层面的东西：绑定 `127.0.0.1`、端口 8000、`context-path: /api`、数据源。

**关键听到**：**配置来自设置表不是配置文件** / **每次请求现拼 ModelSpec** / **密钥不进 yml**

**追问**：那模型实例是单例吗？（答：不是，`ChatServiceImpl` 每轮 `llmModelFactoryRouter.createStreamingModel(spec)` 现建，见 JV-19）；设置页改完怎么立刻生效？（答：`SettingsRegistry.putSettings` 落库后按前缀广播变更事件，下一次请求读到的就是新值）

**常见错答**：「放 `@Value` 里就行」——`@Value` 也是启动期注入一次，用户运行时改设置照样不生效。

### JV-02｜L2｜找坑｜必答｜锚点 `backend_java/.../chat/runtime/StreamingTurn.java:73-107`

**题**：这里的流式为什么要自己再包一层 `CountDownLatch`？

**口语答案**：LangChain4j 1.22 的 `TokenStream.start()` 只是把 HTTP 请求发出去，实测 **474ms 就返回、第一个 token 1.7 秒后才到**。如果以为它阻塞，start() 一回来就把助手消息落库、发 done、关 SSE 流，库里存的就是一条空答案。所以用 `CountDownLatch(1)` 等 `onComplete`/`onError` 其中任意一个到达再往下走，`releaseAfter()` 在 `finally` 里 `countDown()`，保证回调抛异常也不会把调用方永久挂死。代价是要占住一个线程等，所以 `await(Duration)` 必须带超时。

**关键听到**：**start() 不阻塞** / **先收尾就会落库空答案** / **finally 里 countDown 防挂死**

**追问**：三个回调为什么要先挂再 `start()`？（答：1.22 里 token 可能来得极快，start 之后再挂就漏帧了）；`await` 返回 `false` 是什么意思？（答：超时，没收到任何终态，由上层发「模型响应超时」）

**常见错答**：「加个 `sleep` 等一会」——用时间猜完成，网络慢一点就翻车。

### JV-03｜L2｜读代码｜必答｜锚点 `backend_java/.../chat/event/SseAgentEventSink.java:25-60`

**题**：`SseAgentEventSink.emit()` 里那把 `Object lock` 是防什么？

**口语答案**：防两个线程同时往同一个 `SseEmitter` 写。流式回答时模型回调线程在发增量，工具线程在发 `tool_start`/`tool_end`，SseEmitter 内部是有缓冲的，并发写可能丢帧或者直接抛 `IllegalStateException`。这里用一把自己的锁加双重检查：方法开头先看 `volatile boolean closed`，进锁再看一次，然后才 `emitter.send(...)`。捕获到 `IOException | IllegalStateException` 就把 `closed` 置 true、按「前端已经断开」处理，不打 ERROR 日志——用户关页面不是故障。

**关键听到**：**两个写者线程** / **双重检查 + volatile** / **写失败视为对端已关闭**

**追问**：为什么不直接 `synchronized (emitter)`？（答：锁对象会暴露给别的代码，`close()` 也得拿同一把锁才安全，锁在自己类里最可控）；帧格式有要求吗？（答：必须和 Python 侧一致 `event: xxx\ndata: {...}\n\n`，前端一套解析器吃两边）

**常见错答**：「`SseEmitter` 自己线程安全」——它只保证单次 send 不崩，`close` 与 `send` 竞态照样抛异常。

### JV-04｜L2｜设计｜必答｜锚点 `backend_java/.../tools/AbstractGuardedTool.java:71-99`

**题**：工具基类为什么把 `execute` 写成 `final`，只留 `buildAction` 和 `run` 给子类？

**口语答案**：这是模板方法。`execute` 里的顺序是固定的：先 `buildAction` 把参数解析成一个只读的 `ToolAction`，再交给 `runtime.execute(...)` 走「策略裁决 → 预算熔断 → 人工确认 → 真正执行 → 输出截断 → 审计」这条链。如果让每个工具自己实现 `execute`，早晚有工具忘了查权限或者忘了截断。写成 `final` 就是结构上不给这个机会。子类只回答两个问题：我要做什么（`buildAction`）、真的做的时候干什么（`run`）。

**关键听到**：**模板方法固定关卡顺序** / **final 让「忘记检查」不可能发生** / **子类只写两件事**

**追问**：`buildAction` 为什么要求「只读、不能有副作用」？（答：它可能在确认之前就被调用，用户点拒绝时不能已经动过手）；`policy()` 那个 switch 是干什么的？（答：把 `ToolKind` 映射成 `ToolPolicy`，工具自己声明种类，权限由注册表统一判）

**常见错答**：「子类里再判断一次权限更保险」——两处判断必然逐渐不一致，以注册表为唯一来源才对。

### JV-05｜L2｜读代码｜必答｜锚点 `backend_java/.../tools/ToolBudgetRegistry.java:89-156`

**题**：一轮对话的预算超了，是怎么被发现并拦下来的？

**口语答案**：`startBudget()` 从设置表读三个阈值——token 上限默认 50 万、费用上限默认 5 元、时长上限默认 30 分钟。每轮模型返回后 `recordUsage()` 调 `addUsage()` 记账（`(input*单价 + output*单价)/1e6`），`addUsage` 和 `exceeded` 都是 `synchronized`，因为记账和判定必须原子。下一次工具调用前 `ToolRuntime.checkBudget` 调 `exceeded()`，命中就弹预算窗；用户选继续就 `release(dimension)` 让这个维度本轮不再提醒，选停止就 `block()`，那个 `volatile boolean blocked` 一置位，后面所有工具直接拒绝、连窗都不弹。

**关键听到**：**三维阈值来自设置表** / **记账与判定都 synchronized** / **release 单维放行、block 全局熔断**

**追问**：为什么不拦纯文本生成？（答：没有工具的循环烧不了多少钱，拦文本会打断正常回答）；为什么单任务口径是「一轮用户请求」？（答：一轮结束预算清零，用户下次提问重新给额度）

**常见错答**：「超了直接抛异常」——抛异常会把整轮 Agent 打断，用户连「我已经做了什么」的总结都拿不到。

### JV-06｜L1｜基础｜必答｜锚点 `backend_java/.../service/impl/ChatServiceImpl.java:1655-1697`

**题**：`buildChatMemory` 为什么每轮都 new 一个 `MessageWindowChatMemory`，而不是做成 Bean 复用？

**口语答案**：因为记忆只服务这一次请求。做成 Bean 就要处理「多个会话同时流式」时互相踩同一个 memory，还要处理会话切换时清空，全是并发坑。每轮新建、请求结束就丢，天然不会有跨会话串味。窗口大小 `maxMessages(200)` 和读历史用的 `MAX_SEED_MESSAGES` 是同一个数，保证「读出来多少就喂进去多少」。灌的时候只灌 user 和 ai 两种消息，system 和 tool 行不补——它们不是对话轮次，塞进窗口只会把真正的上下文挤掉。

**关键听到**：**每轮新建避免跨会话污染** / **窗口 200 与读历史同源** / **只灌 user/ai，system 每轮现拼**

**追问**：system 提示词去哪了？（答：`AiServices.builder().systemMessage(...)` 每轮现拼，不进记忆窗口）；为什么不是全量历史？（答：有上下文压缩在前面挡着，最近 200 条足够，全量塞进去会撞模型窗口）

**常见错答**：「做成 `@Bean` 单例性能好」——省下的那点对象分配，换来的是会话之间互相污染。

### JV-07｜L2｜找坑｜抽答｜锚点 `backend_java/.../tools/OutputContract.java:100-190`

**题**：工具输出太长时发生了什么？为什么砍的是尾部？

**口语答案**：`OutputContract.apply()` 从设置读 `context.tool_output_truncate`（默认开）和上限 `context.max_tool_output_chars`（默认 8000 字符），超了就保留**前** 8000 个字符，尾部砍掉，然后拼一句「已截断，共 N 字符，完整内容可用续读标记 xxx 取回」。完整文本以 JSON 字符串写进 `app_settings`，标记形如 `tool-out-<uuid>`，前端或模型再调 `/chat/tool-output/{ref}` 读全文。砍头不砍尾是因为工具输出的有效信息基本在开头，而且 `OK:` / `FAIL:` 前缀在头一行，砍尾不会破坏它。

**关键听到**：**上限来自设置、默认 8000** / **砍尾保头，前缀语义不丢** / **全文落库 + 续读 ref**

**追问**：`MAX_CONTINUATION_CHARS = 2_000_000` 是防什么？（答：防一次工具输出把设置表撑爆）；`takeLastTruncation` 为什么要「取走即删」？（答：截断信息是这一轮的，留到下一轮会串到别的工具事件上）

**常见错答**：「截断就是 `substring(0, n)`，没啥可想的」——不落全文，模型就永远看不到被砍掉的那半，用户也没法自查。

### JV-08｜L3｜找坑｜加分｜锚点 `backend_java/.../tools/PathLock.java:38-159`

**题**：路径锁的 `LOCKS` 是个静态 `ConcurrentHashMap`，为什么还要在里面存引用计数？

**口语答案**：锁是按「文件绝对路径」给的，同一个路径可能被同一线程连续取两次——比如写文件前先备份、再写入。所以 `LockEntry` 里放的是 `ReentrantLock`，同线程可以重入。但 `ConcurrentHashMap` 不能存一把裸锁：取锁这个动作本身要「有则取、无则建并把计数加一」，`get` 加 `synchronized` 两步做是竞态，两个人可能各拿到一把锁锁同一个文件，所以用 `LOCKS.compute(...)` 把整段合成原子操作。释放走 `computeIfPresent`，`refs--` 归零就 `return null`，`ConcurrentHashMap` 自动删键——不然这个 map 会随着跑过的文件无限涨。

**关键听到**：**ReentrantLock 支持同线程重入** / **compute 把取建与计数合成原子** / **归零返回 null 让 map 自删**

**追问**：`tryLock(30, SECONDS)` 超时了怎么办？（答：抛 `IllegalStateException("等待文件锁超时（30s）：" + path)`，让工具调用失败而不是永久阻塞）；`lockKey()` 为什么要 normalize + 转小写？（答：Windows 路径大小写不敏感，`C:\A` 和 `c:\a` 必须算同一把锁）

**常见错答**：「用 `synchronized` 方法一把大锁锁所有文件操作」——读操作之间本来可以并行，一把大锁把并发全废了。

### JV-09｜L2｜读代码｜抽答｜锚点 `backend_java/.../tools/PathPolicy.java:57-115`

**题**：`PathPolicy` 里的规则表为什么写成声明式，而不是一串 `if`？

**口语答案**：模块注释说得直白——每加一个工具就抄一遍路径判断，一定会漏一处。现在 `PATH_RULES` 里只有一条规则：`backend_java` 自己的源码目录只允许 `read`，不允许写和执行，理由是「改了就跑不起来了」。判定顺序是先看受保护目录（按表顺序，第一条命中就生效），再看工作区白名单。关键那句是 `if (OP_READ.equals(op) || effectiveRoots.isEmpty()) return null;`——**读一律放行**，白名单只约束有副作用的 write/exec，否则用户根本没法在界面上浏览自己机器。

**关键听到**：**规则表替代散落的 if** / **第一条命中生效** / **读放行，白名单只管 write/exec**

**追问**：工作区换了怎么办？（答：`refreshWorkspaceRoots` 写 `volatile List<Path>`，其它线程立刻可见，不用重启）；`detectBackendRoot()` 为什么不能直接 `user.dir`？（答：`user.dir` 是启动目录，从 IDE 跑和从 jar 跑不一样，先用系统属性 `app.backend.root`，否则从 `CodeSource` 的 location 推）

**常见错答**：「路径判断放工具里各自判断」——那 `write_file` 和 `edit_file` 的规则迟早不一致。

### JV-10｜L2｜设计｜抽答｜锚点 `backend_java/.../settings/SecretStore.java:64-215`

**题**：密钥为什么要自己实现 AES/GCM，每个加密都换 IV？

**口语答案**：不用明文是因为 `app_settings` 会被导出、备份、贴进 issue，明文密钥等于泄露；不用 Python 侧的 Fernet 是因为 Java 没有内置等价实现。选 `AES/GCM/NoPadding` 是因为它是带认证的加密——篡改密文解密会失败，不会悄悄解出错的内容。参数是 32 字节 key、12 字节 IV、128 bit tag，输出 `base64(iv || 密文+tag)`，IV 每次加密重新随机：**GCM 下 IV 重用会直接摧毁安全性**。key 文件在 `~/.vue3-ts-python-learn/app-secret.key`，尽力 `rw-------`；Windows 不支持 POSIX 权限会抛异常，那里静默跳过。

**关键听到**：**GCM 带认证、篡改可发现** / **IV 每次随机，绝不能重用** / **解密失败当「未配置」而不是 500**

**追问**：`getSecret` 解密失败为什么返回 empty？（答：换机器、密钥文件丢了必然走到这里，设置页要是 500 用户就进不去了）；为什么 key 缓存在字段里？（答：每读一个设置就解一次 AES 太浪费，缓存且只在文件变化前有效）

**常见错答**：「固定 IV 更简单」——固定 IV 下相同明文出相同密文，等于把密钥交给差分分析。

### JV-11｜L2｜读代码｜抽答｜锚点 `backend_java/.../settings/SettingsRegistry.java:118-210`

**题**：`SettingsRegistry` 的三条约定「读宽松、写严格、改完广播」具体是怎么落的？

**口语答案**：读宽松——`getSetting` 拿不到值、类型对不上、`coerce` 抛异常，一律回落声明的默认值，调用方永远不用判空；设置表里的值以 JSON 文本存，这样 int/float/string 的类型差别不会丢。写严格——`putSettings` 第一步把所有键整体 `coerce` 一遍，任何一个失败整批拒绝、库一个字节都没动，避免「一半生效」；全部通过才逐个写，写成功后再统一 `publish`。改完广播——`subscribe(prefix, listener)` 用 `ConcurrentHashMap<String, CopyOnWriteArrayList<...>>`，遍历时有人增删监听者不会抛并发异常，单个监听者抛异常只 `log.warn`，不影响已经成功的保存。

**关键听到**：**读宽松：任何异常都回落默认值** / **写严格：先整体校验再落库** / **广播失败不影响保存结果**

**追问**：为什么用 `TreeMap` 再 `unmodifiableMap`？（答：按键升序，设置页展示稳定）；`secrets.` 和标了 `secret()` 的键为什么禁止出现在 `getAllSettings`？（答：全量设置接口会被前端整页拿走，密钥只能单独走掩码接口）

**常见错答**：「先写库再校验」——写一半失败就留下一个自相矛盾的设置状态。

### JV-12｜L3｜找坑｜加分｜锚点 `backend_java/.../tools/ToolRuntime.java:100-160`

**题**：一次工具调用要过几道关？顺序为什么不能换？

**口语答案**：`execute()` 里顺序是固定的：`policyRegistry.decide(...)` 裁决 → `checkBudget` 预算 → ASK 才 `resolveAsk` 弹确认 → `body.get()` 执行 → `outputContract.apply()` 截断 → `audit()` 审计 → 最后追加用户插话。第一条铁律是 **DENY 一定在预算和确认之前返回**，任何权限模式都改不了它；第二条是预算在确认之前，不然用户会连着被打扰两次（先弹「要执行吗」再弹「超预算了」）；第三条是先治理再审计，保证模型看到的文本和审计记录的文本是同一份。另外构造器里 `ObjectProvider.getIfAvailable()` 拿不到确认网关时，默认实现是 **fail-closed** 的——一律 `DENIED`，而不是放行。

**关键听到**：**DENY 优先于一切** / **预算早于确认，少打扰一次** / **缺实现时 fail-closed 不是 fail-open**

**追问**：`body.get()` 抛 `RuntimeException` 怎么处理？（答：转成 `ToolResult.fail`，让模型看到失败原因继续，而不是把整轮 Agent 打断）；`appendSteering` 为什么放在最后？（答：用户插话不该被截断，也不该被记成工具输出）

**常见错答**：「先执行再看权限」——工具已经有副作用了，再拒也没意义。

### JV-13｜L2｜读代码｜抽答｜锚点 `backend_java/.../chat/runtime/ChatSessionBus.java:248-290`

**题**：工具要用户确认时，为什么要把当前的 SSE 流关掉，再让前端开一条新流？

**口语答案**：前端的契约是 `confirm_required` 事件一到就结束当前这次 `await`、弹出确认框，用户点完再调 `/chat/resume` 开一条新流继续看后面的输出。所以执行线程不能和某一条具体的 `SseEmitter` 绑死：`askAndWait` 先发事件、`detach(sessionId)` 把当前 sink 关掉（关掉前端那次 await 才会返回），然后阻塞在 `future.get(10 分钟)` 上；用户点同意后 `/chat/resume` 先 `bind` 新的 sink，再 `answer(sessionId, interruptId, result)` 把 future 兑现。interruptId 不匹配就返回 false、回一句「这次确认已经失效」，而不是 500——用户点的很可能是上一次已经超时的弹窗。

**关键听到**：**执行线程不绑定具体 emitter** / **detach 关流才会让前端弹框** / **interruptId 校验防串号**

**追问**：这个设计的代价是什么？（答：一个待确认的轮次会占住一个线程；进程重启后待确认的轮次直接丢，Python 侧靠 LangGraph checkpoint 解决）；`requestStop` 为什么要顺手 `complete(DENIED)`？（答：否则线程要等到 10 分钟超时）

**常见错答**：「一直复用同一条 SSE 流不就行了」——前端已经 `await` 结束了，那条流没法复活。

### JV-14｜L3｜设计｜加分｜锚点 `backend_java/.../service/impl/ChatServiceImpl.java:1539-1600`

**题**：上下文压缩什么时候触发？三条条件为什么是「与」的关系？

**口语答案**：`buildSeedContext` 里三条同时满足才压缩：设置里 `context.auto_compress` 开着、估算 token 超过 `contextWindow × compress_threshold`（默认 0.7）、消息条数超过 `context.keep_recent_n`（默认 10）。少任何一条都不划算——关掉开关就不该动；没超预算压了纯浪费一次模型调用；条数太少压完剩下的还没原文长。触发后最近 10 条原样保留，更早的交给模型总结，摘要按 `sessionId → (lastMessageId, summary)` 缓存在 `SummaryCache` 里，同一批消息不会重复调用模型。摘要失败只 `log.warn` 并退回上一次摘要——压缩是优化，不能成为对话的前置条件。

**关键听到**：**三条件与关系，缺一不压** / **最近 N 条保留原文，只压更早的** / **摘要失败降级不阻塞对话**

**追问**：token 怎么估的？（答：`estimateTokens(text)` 直接 `return text.length()`，见 JV-21）；压缩结果写回库了吗？（答：Java 侧没写回，Python 侧写了，见 JV-18）

**常见错答**：「只看条数够了就压」——200 条短消息可能才几千 token，压了反而丢信息。

### JV-15｜L2｜读代码｜抽答｜锚点 `backend_java/.../chat/runtime/ChatToolExecutor.java:87-130`

**题**：工具执行完，为什么要在 `finally` 里 `ToolSession.clear()`？

**口语答案**：`ChatToolExecutor` 跑在线程池里，一个线程处理完这个会话的工具，下一个请求可能还是这条线程。`ToolSession` 是 ThreadLocal 语义的当前会话上下文（sessionId、权限模式、作用域），不清理就会串到下一个请求上——最坏的情况是伪造出别的会话的权限。所以 `setContext` 之后在 `finally` 里 `clear()`，不管 execute 正常还是抛异常都执行。同一条链上还有两件事：一开始就查 `recorder.isStopped()`，用户已经点了停止就返回「未执行」并补发 `tool_end`，不让模型以为工具跑过了；最后 `takeLastTruncation` 把这一轮的截断信息取走即删。

**关键听到**：**ThreadLocal 在池化线程里必须手动清** / **停止标志要在执行前查** / **截断信息取走即删防串轮**

**追问**：`tool_end` 事件为什么要带 `total_chars`/`truncated`/`continuation_ref`？（答：前端要显示「已截断 3000 字，点此看全文」，模型也要知道内容不完整）；为什么一个工具一个执行器实例？（答：`ToolExecutor` 的粒度就是「这一轮的这个工具」，状态天然不共享）

**常见错答**：「ThreadLocal 用完 GC 会清」——线程活着就不会清，池化线程更是长期活着。

### JV-16｜L2｜设计｜抽答｜锚点 `backend_java/.../tools/ToolPolicyRegistry.java:39-60`、`:183-257`

**题**：为什么「没登记策略的工具一律 DENY」，而不是默认允许？

**口语答案**：`DEFAULT_LEVELS` 里只有 READ 是 ALLOW，WRITE、EXEC、NET、MCP 全都是 DENY。这样「新增工具忘记加检查」在结构上就不可能发生——没登记的工具根本跑不起来，作者第一件事就是去 `builtinPolicies()` 里声明一条策略。`decide()` 的判定顺序是：策略未登记 DENY → 会话级 denyTools → `offByDefault` 且功能开关没开 DENY（联网三个工具就是这种，读设置失败按关闭）→ 逐个路径过 `PathPolicy` → 才轮到等级判定。子 agent 那条红线更严：只把本来是 ALLOW 的升级成 ASK，DENY 保持 DENY，**安全等级只能收紧不能放松**。

**关键听到**：**fail-closed：未声明即拒绝** / **联网类 offByDefault + 读设置失败当关闭** / **子 agent 只收紧不放松**

**追问**：MCP 工具是运行时才知道的，怎么登记？（答：`registerDynamic` 以最新声明为准，`unregisterPrefix("mcp__")` 清残留，启动时 `verifyAllToolsRegistered` 自检）；`run_command` 的白名单怎么放行？（答：EXEC 且会话有 `allowedCommands` 时，取命令头两个词命中就直接 `allow`）

**常见错答**：「默认允许、以后再加限制」——限制永远加不完，而默认允许的窗口就是漏洞窗口。

---

## B. 双后端对照（JV-17 ~ JV-28）

> 这一块的 Python 侧事实来自 `backend/app/`，答题时必须说清「Java 侧是……，Python 侧是……」。

### JV-17｜L2｜读代码｜必答｜锚点 `backend_java/.../service/impl/ChatServiceImpl.java:1079-1086` + `backend/app/controllers/chat_controller.py:1067-1100`

**题**：同样一个「停止生成」，Java 和 Python 两套后端各自是怎么做到的？

**口语答案**：Java 侧是**温柔中断**。LangChain4j 1.22 的 `TokenStream` 没有 `cancel()`（`ChatServiceImpl` 的 Javadoc 里写着「我 javap 查过」），所以 `stop()` 能做的是：`recorder.markStopped()` 让后续增量不再转发、把正在等待的确认按拒绝兑现、立刻发 `stopped` 事件并关流；模型那边的 HTTP 流在后台自己跑完，只是没人看。Python 侧是**真停**：`_iter_until_stop` 用 `asyncio.wait({取下一帧, 停止信号}, return_when=FIRST_COMPLETED)` 让两件事赛跑，停止信号赢了就 `next_ev.cancel()`、`gather` 等它停稳、再 `agen.aclose()` 关掉异步生成器。

**关键听到**：**Java 没有 cancel()，只能停止转发** / **Python 用 FIRST_COMPLETED 赛跑** / **cancel 之后还要 aclose 才算真停**

**追问**：为什么 Java 不能像 Python 那样直接取消？（答：`TokenStream` 是基于回调的阻塞式 API，底层 HTTP 流的生命周期框架没暴露出来）；两种做法对用户体验有差别吗？（答：用户看到的都是「立刻停住」，差别在于 Python 能省下后续 token 的钱）

**常见错答**：「`stop()` 就是把线程 interrupt 掉」——interrupt 打断的是等待的线程，模型调用还在跑，还可能把连接池搞坏。

### JV-18｜L3｜找坑｜加分｜锚点 `backend/app/controllers/chat_controller.py:1106-1171` + `backend_java/.../service/impl/ChatServiceImpl.java:1539-1600`

**题**：上下文压缩之后，两套后端都把结果写回「历史」了吗？

**口语答案**：写法完全不同。Python 侧压缩完调 `agent.aupdate_state(config, {"messages": new_messages})` 把摘要 + 最近消息**写回 checkpointer**，也就是说下一轮 `aget_state` 拿到的就是压缩后的历史，不用每轮重算。Java 侧**不写回**：消息表里永远是原始记录，压缩只影响本轮拼给模型的 seed，摘要靠 `SummaryCache` 按 `(sessionId, lastMessageId)` 复用，避免重复调用模型。这两种取舍各有代价：Python 省了每轮的估算和摘要钱，但改写了「历史」这份事实数据；Java 保留了完整原文（可回看、可导出），代价是每轮都要重新估算一次、缓存失效就得再摘要一遍。

**关键听到**：**Python 写回 checkpointer** / **Java 只影响本轮 seed，原文不动** / **各有代价：省算力 vs 保原文**

**追问**：Python 侧压缩为什么放在「本轮开始前」？（答：结束之后再压，下一轮的输入仍然膨胀，模型已经付过那份钱）；Java 的 `SummaryCache` 为什么按 `lastMessageId` 做 key？（答：最后一条消息没变就说明消息集合没变，摘要可以复用）

**常见错答**：「两边都是压缩历史，应该一样吧」——一个改数据源，一个只改视图，差的是「谁能回看原文」。

### JV-19｜L2｜设计｜必答｜锚点 `backend/app/llm/state.py:1-19` + `backend_java/.../service/impl/ChatServiceImpl.java:691-697`

**题**：为什么 Python 侧要缓存模型和 Agent 图，Java 侧却每轮都新建？

**口语答案**：代价不一样。Python 的 `create_agent()` 会编译出一张 LangGraph 图，构建开销是几十毫秒级，每轮重建会明显拖长首字时间，所以 `llm/state.py` 按「provider + model + 参数」算一个指纹 `"main:deepseek:deepseek-chat:0.0:25"` 缓存实例，设置变更事件来了就失效——事件驱动，不是轮询。而且它是按作用域分槽的，MAIN 和 SUB 各存一份，否则「每派一次子任务就把主对话图顶掉重建」。Java 侧 `AiServices.builder(...)` 只是拼几个对象引用，microsecond 级，而且 memory、工具表、systemMessage 每轮都不一样——缓存反而要额外处理失效，不如不缓存。

**关键听到**：**Python 缓的是编译好的图，开销几十毫秒** / **指纹 + 设置事件驱动失效** / **Java 每轮建的对象很轻，缓存不划算**

**追问**：Python 缓存为什么还要加锁？（答：SSE 并发下两个请求同时命中「缓存为空」时只该构建一份）；Java 不缓存会不会导致「设置改了不生效」？（答：正好相反，每轮现读设置表，改了下一轮就生效）

**常见错答**：「缓存一定更快」——缓存的对象越轻、失效条件越多，缓存本身就是负担。

### JV-20｜L2｜读代码｜必答｜锚点 `backend_java/.../service/impl/ChatServiceImpl.java:1655` + `backend/app/services/context_manager.py:1-22`

**题**：「历史」在两套后端里分别存在哪，为什么这个差别会影响压缩怎么写？

**口语答案**：Python 侧的历史在图的状态里，由 checkpointer 持久化，每轮 `aget_state` 把整段 `messages` 塞给模型——所以才有「几十轮后输入膨胀」这个问题，也才需要把压缩结果写回状态。Java 侧的历史在消息表里，每轮读出最近 200 条（`MAX_SEED_MESSAGES`）灌进一个新建的 `MessageWindowChatMemory(200)`，窗口本身就是一层天然上限。这个差别决定了两边的压缩目标不同：Python 压缩是为了「别让状态无限长」，Java 压缩是为了「别让本轮输入超预算」。

**关键听到**：**Python 历史在 checkpointer，Java 在消息表** / **窗口 200 是 Java 的天然兜底** / **压缩目标因此不同：状态长度 vs 本轮输入**

**追问**：Java 侧既然有 200 条窗口，为什么还要压缩？（答：200 条长消息照样能撑爆模型窗口，token 才是真约束）；Python 侧压缩有哪条硬约束？（答：不能把 `AIMessage(tool_calls)` 和紧跟的 `ToolMessage` 拆开，切分点只能落在用户消息上）

**常见错答**：「记忆窗口就是上下文压缩」——一个是硬截断，一个是先总结再截断，丢的信息量完全不同。

### JV-21｜L2｜找坑｜抽答｜锚点 `backend/app/services/context_manager.py:66-84` + `backend_java/.../service/impl/ChatServiceImpl.java:1926`

**题**：两边估算 token 的口径一样吗？谁更保守？

**口语答案**：不一样。Python 的 `estimate_tokens` 是分段的：CJK 字符按 1 字 1 token，其它字符按 4 字符 1 token，最后 `+1`；docstring 解释了为什么不用 tiktoken——要按模型下载词表，离线环境直接失败，误差跟自己估也差不多。Java 的 `estimateTokens` 更粗暴，直接 `return text.length()`，按「1 字符 ≈ 1 token」算。对中文来说两者接近；对英文 Java 会把 token 数估高 3~4 倍，结果是**更早触发压缩**。这个偏差是刻意留的：宁可比预算早一点压缩，也不要等供应商报 context length 错误。

**关键听到**：**Python 分段：CJK 1/字，其它 4 字符** / **Java 就是 length()** / **英文高估 → 早压缩，是安全方向**

**追问**：为什么都不用 tiktoken/官方分词器？（答：离线不可用、每换模型要换词表，收益抵不上复杂度）；Java 的 `String.length()` 还有什么坑？（答：按 UTF-16 码元计数，emoji 会被算成 2，跟 Python 的字符数对不上）

**常见错答**：「token 数可以让模型返回的 usage 拿到」——那是**已经花掉**的，压缩决策必须在发请求之前做。

### JV-22｜L2｜读代码｜抽答｜锚点 `backend/app/agents/rag_agent.py:184-201`、`:211-258`

**题**：子 Agent 的工具权限，Python 侧和 Java 侧分别在哪一层裁的？

**口语答案**：Python 侧是**构建时裁剪**：`build_tools(scope)` 在 SUB 作用域下只返回 `SUB_TOOLS`——只读工具 + glob + sql + skill，刻意不含写盘、执行、文件管理、联网和 MCP，理由写得直接：「能力未知，无法保证只读」。而且 `_SUB_EXCLUDED_READ_TOOLS` 里专门排除了 `index_path` 和 `delete_index`，因为名字像读、实际上会改知识库。Java 侧是**运行期裁决**：`buildEventedToolMap` 给的是全量工具，靠 `ToolPolicyRegistry.decide()` 按 `ToolSession.SCOPE_SUB` 把 WRITE/EXEC 强制升级成 ASK。

**关键听到**：**Python 在构建期就把工具拿掉** / **Java 拿全量、靠裁决收紧** / **名字带 read 不代表只读**

**追问**：两种做法各自的取舍？（答：构建期裁剪更安全但改配置要重建工具表；运行期裁决灵活但每次调用都要判一次）；Java 那边子 agent 为什么不能直接 DENY？（答：子 agent 也有正常写盘需求，只是必须逐次确认，所以升级成 ASK 而不是拒绝）

**常见错答**：「工具名字以 read 开头就是只读」——`index_path` 就是反例，所以 Python 专门维护了一份排除表。

### JV-23｜L2｜找坑｜抽答｜锚点 `backend/app/services/context_manager.py:13-22` + `backend_java/.../service/impl/ChatServiceImpl.java:1699-1730`

**题**：压缩出来的摘要，两套后端分别放在消息列表的什么位置？

**口语答案**：Python 侧特意**不用 `SystemMessage`**：`create_agent` 每轮自己在最前面插系统提示词，再塞一条 system 就变成「两条 system」，Anthropic 这类供应商会直接拒绝，所以用一条带明显标记的 `HumanMessage` 承载摘要。Java 侧正相反，摘要作为 `buildSystemMessage` 里的一个块拼进 system——因为 Java 侧的 systemMessage 是每轮现拼、不写进记忆窗口的，不存在「两条 system」的问题。

**关键听到**：**Python 不能用 SystemMessage，会变两条 system** / **Java 摘要进现拼的 systemMessage** / **差别来自「谁负责插系统提示词」**

**追问**：Java 的 systemMessage 为什么每轮现拼而不写进记忆？（答：写进 200 条窗口里会被挤掉，而且它不是对话轮次）；Python 那条 HumanMessage 为什么要带明显标记？（答：模型得知道这是「之前的对话摘要」，不是用户刚说的话）

**常见错答**：「摘要塞 system 最合适，system 优先级高」——前提是你能控制 system 的唯一性，这里控制不了。

### JV-24｜L2｜设计｜抽答｜锚点 `backend_java/.../settings/SecretStore.java:46-66` + `backend/app/services/secrets.py`

**题**：同一件事（加密存密钥），为什么两套后端用了不同的算法？

**口语答案**：Python 侧用 Fernet，标准库生态里有现成实现、自带版本与时间戳。Java 侧没有 Fernet 的等价实现，于是选了 `AES/GCM/NoPadding`——同样是带认证的加密，密钥 32 字节、IV 每次随机 12 字节、tag 128 bit，密文格式 `base64(iv || 密文+tag)`，主密钥单独存在用户目录下。两侧的共同约定是一致的：库里只存密文、接口只回掩码（前 3 + `****` + 后 4）和「是否已配置」的布尔值、解密失败一律当「未配置」而不是报错。

**关键听到**：**Fernet vs AES/GCM，都是认证加密** / **存密文、回掩码、只给 has_secret** / **解密失败降级为未配置**

**追问**：为什么不自己拼 `AES/CBC + HMAC`？（答：等于手写认证加密，很容易漏掉「先验签再解密」这类细节）；掩码为什么长度小于 8 就直接返回 `****`？（答：短密钥露 3+4 位等于露大半）

**常见错答**：「用 base64 就算加密了」——base64 是编码，谁都能解。

### JV-25｜L3｜设计｜加分｜锚点 `backend/app/agents/rag_agent.py:204-208` + `backend_java/.../tools/ToolPolicyRegistry.java:324`

**题**：两套后端都在启动时校验「每个工具都有策略」，为什么这件事必须做成启动自检？

**口语答案**：因为工具是分批来自不同来源的：内置的、按设置动态加的、MCP 连上之后才有的。任何一个漏了策略，运行期的表现就是「用户点了才发现这个工具没有权限判断」，或者更糟——被默认放行。Python 侧在模块导入时就 `install_builtin_policies()` + `verify_all_tools_registered(TOOLS)`，并且连 `SUBAGENT_TOOLS` 也一起登记，注释写着「否则用户一打开开关就撞上启动自检，表现为开了就崩」；MCP 工具是运行期才发现的，所以 `build_tools` 最后再自检一次。Java 侧 `verifyAllToolsRegistered` 直接抛 `IllegalStateException("以下工具没有登记安全策略，拒绝启动")`——启动期 fail-fast，比线上 fail-silent 好得多。

**关键听到**：**工具来源分批，漏一个就是一个洞** / **启动期失败好过运行期静默** / **动态来源要二次自检**

**追问**：Java 侧 MCP 工具怎么办？（答：`registerDynamic(policy)` 以最新声明为准，`unregisterPrefix("mcp__")` 清残留）；为什么不干脆把所有工具注册成 DENY 兜底？（答：那会让「忘记声明」变成「功能不能用」，作者会去改 DEFAULT 而不是补策略，反而更糟）

**常见错答**：「自检没必要，代码评审能看出来」——工具表会持续变长，靠人看必然漏。

### JV-26｜L1｜基础｜抽答｜锚点 `backend_java/.../common/PageLimits.java:28-99`

**题**：分页参数 `limit` 的默认值和上限为什么要单独抽一个类？

**口语答案**：抽出来是因为以前写崩过：controller 里写默认值 20/200/50/100/500、service 里再各自 clamp 一次，同一个仓里出现四种写法，结果是「前端按 200 请求，Java 后端悄悄截到 100，用户打开长会话少了一半消息」。现在 `PageLimits` 是 Java 侧唯一来源，Python 侧镜像在 `backend/app/core/limits.py`，两边数字必须逐项一致。分工也写清楚了：HTTP 入口用 `@Min(1) @Max(...)`，越界**直接 400**，不做悄悄纠正；`clamp(limit, max)` 只给内部调用兜底，防止 `Pageable.ofSize(0)` 这种非法翻页大小。

**关键听到**：**一处定义，不是统一成一个数值** / **入口越界就 400，不悄悄改** / **内部入口用 clamp 兜底**

**追问**：为什么不同端点上限不同？（答：左栏会话列表一屏 20 条够，历史回填要 200，轨迹排查一次要 500，统一成一个数只会让某类端点变难用）；越界的约定文档在哪？（答：`docs/adr/0001-limit-越界一律报错.md`：省略=取默认值，显式越界=报错）

**常见错答**：「用 `Math.min` 截一下更友好」——客户端永远不知道自己只拿到一部分，这比报错更难查。

### JV-27｜L1｜基础｜抽答｜锚点 `backend_java/.../chat/event/SseAgentEventSink.java:51-77`

**题**：SSE 的帧长什么样？为什么两套后端要保证帧格式一致？

**口语答案**：一帧是 `event: <事件名>`、`data: <JSON>`、再加一个空行。Java 侧用 `SseEmitter.event().name(event.type()).data(event.data(), MediaType.APPLICATION_JSON)` 发，Python 侧拼字符串发同样的形状。必须一致的原因是前端只有一套解析器——切后端是用户点一下的事，帧格式差一个字段或者少个空行，前端就整片解析失败。事件名两边是同一套字典：`thinking`、`partial`、`tool_start`、`tool_end`、`confirm_required`、`budget_exceeded`、`done`、`stopped`、`error`，`/chat/events` 接口可以查。

**关键听到**：**event + data + 空行** / **前端一套解析器吃两边** / **事件名是共用字典**

**追问**：SSE 的全局超时怎么配的？（答：`spring.mvc.async.request-timeout: -1`，交给业务控制，`ChatServiceImpl` 自己用 300 秒窗口 + 20 秒收尾余量）；为什么要有收尾余量？（答：留时间把助手消息落库、发 done、关流）

**常见错答**：「SSE 就是 WebSocket 的简版」——SSE 是单向、基于 HTTP、断线要靠客户端重连，不能双向推。

### JV-28｜L2｜找坑｜抽答｜锚点 `backend_java/.../controller/ChatController.java:46-58`

**题**：其它接口都返回 `ApiResponse`，为什么 `/chat/*` 这些返回裸 JSON？

**口语答案**：为了前端零改动切换后端。前端的 `services/chat.ts` 里 `chatJson()` 直接读裸对象——`{sessions:[...]}`、`{stopped:true}`，Python 侧的 `/chat/*` 辅助端点也是这么返回的。如果 Java 侧为了「统一」套一层 `ApiResponse`，前端就得为两套后端写两种解析。所以类注释里明确写了这个例外，同时把另一半也写清楚：`/chat/stream` 和 `/chat/resume` 返回的是 `text/event-stream`，不是 JSON。

**关键听到**：**为兼容前端和 Python 侧的裸 JSON** / **流式接口是 text/event-stream 第三种形态** / **一致性优先于「看起来统一」**

**追问**：那 `ApiResponse` 里的 `code` 和 HTTP 状态码是什么关系？（答：解耦，业务错误用 code 表达，HTTP 仍是 200，见 JV-29）；这种「例外」怎么写才不坑后来人？（答：写在类 Javadoc 里并说明原因，否则下一个人一定会「顺手统一」掉）

**常见错答**：「返回格式必须全站统一」——统一是为了减少认知负担，破坏兼容性的统一是负收益。

---

## C. Java / Spring 通用（JV-29 ~ JV-40）

### JV-29｜L1｜基础｜必答｜锚点 `backend_java/.../common/ApiResponse.java:12-52`

**题**：统一返回体为什么用 `record`，`code` 为什么不直接用 HTTP 状态码？

**口语答案**：`record ApiResponse<T>(int code, String message, T data)` 三个组件就是三个字段，`equals`/`hashCode`/`toString` 自动生成，天然不可变，非常适合这种纯数据载体。配两个静态工厂：`ok(data)` 给 `code=0`、`message="ok"`，`error(code, message)` 的 `data` 为 null。业务码和 HTTP 状态码解耦，是因为前端已经有了一套 `code !== 0` 的错误处理，如果业务失败也回 4xx/5xx，前端要同时处理「HTTP 层失败」和「业务层失败」两套语义，很容易出现「弹了两次 toast」。

**关键听到**：**record 不可变 + 自动生成样板方法** / **静态工厂替代多构造器** / **业务码与 HTTP 解耦，避免前端两套错误语义**

**追问**：那 HTTP 状态码还有用吗？（答：有，传输层错误、参数校验失败、未实现仍然是真 4xx/5xx，见 JV-30）；泛型 `<T>` 带来什么？（答：`data` 不用写成 `Object`，调用方拿到就是强类型，前端也不需要额外解析）

**常见错答**：「业务失败就该回 400」——那前端没法区分「请求写错了」和「业务规则不允许」。

### JV-30｜L2｜读代码｜必答｜锚点 `backend_java/.../common/GlobalExceptionHandler.java:44-184`

**题**：`@RestControllerAdvice` 里为什么要有 9 个 `@ExceptionHandler`？少几个会怎样？

**口语答案**：因为这 9 类异常在 Spring MVC 里抛出的时机完全不同，兜底到一个 handler 就分不清该回 400 还是 500。`ApiException` 是业务错误（HTTP 200 + 业务码，只有 code=501 时用真 HTTP 501）、`MethodArgumentNotValidException` 和 `ConstraintViolationException` 是校验失败（400，前者把每个 FieldError 拼成「字段: 原因」）、`HttpMessageNotReadableException` 是请求体不是合法 JSON、两个参数类异常是缺参数/类型不匹配、`UnsupportedOperationException` 是 501、`NoResourceFoundException` 是 404。最后一个 `Exception` 兜底：`log.error` 打完整堆栈，但响应只给「服务器内部错误，请查看后端日志」——堆栈不能漏给前端。

**关键听到**：**按异常来源分类映射状态码** / **`NoResourceFoundException` 不处理会被兜底成 500** / **兜底 handler 只给通用文案，堆栈进日志**

**追问**：为什么 `NoResourceFoundException` 要单独写？（答：Spring Boot 3.2+ 访问不存在的路径抛的是它，不单独处理会被 `Exception` 兜底成 500，日志里全是误导性的 500）；`ApiException` 为什么默认回 HTTP 200？（答：前端按业务码分支，HTTP 层保持「请求处理完成」的语义）

**常见错答**：「一个 `@ExceptionHandler(Exception.class)` 就够了」——所有错误都变 500，前端没法区分自己写错了还是服务端炸了。

### JV-31｜L2｜找坑｜必答｜锚点 `backend_java/.../util/ServiceSupport.java:32-42`

**题**：Controller 里为什么注入 `ObjectProvider<ChatService>`，而不是直接注入 `ChatService`？

**口语答案**：因为这个工程是给学习者练手的，Controller 全部依赖接口，实现由学习者后补。直接注入接口，只要容器里没有实现，Spring 启动就失败——整个应用一个接口都没法用。改成 `ObjectProvider` 之后，应用照常启动，被调到的接口由 `ServiceSupport.require()` 抛一个 `ApiException(501, "XXX 尚未实现：请实现对应 Service 接口并注册为 Spring Bean")`，用户看到的是明确提示。`getIfAvailable()` 的语义是「恰好一个 Bean 时返回，没有就 null」，也不会有 `NoSuchBeanDefinitionException`。

**关键听到**：**直接注入接口会让整个应用启动失败** / **ObjectProvider 让缺失变成运行期 501** / **错误信息要告诉人下一步做什么**

**追问**：生产项目里也这么写吗？（答：不。生产项目实现是必须有的，用构造器直接注入才能「启动即校验依赖」；这里是为了教学工程的可运行性做的例外）；`getIfAvailable` 和 `getIfUnique` 有什么区别？（答：后者在有多个实现且没有 `@Primary` 时抛异常，前者只处理「没有」）

**常见错答**：「加个 `@Autowired(required = false)` 也一样」——字段注入 + 判空散落各处，还拿不到「一个接口一个提示」的统一文案。

### JV-32｜L2｜找坑｜抽答｜锚点 `backend_java/.../dto/ChatDtos.java:56-118`

**题**：`docTopK`、`maxIterations` 为什么声明成 `Integer` 而不是 `int`？

**口语答案**：因为 Jackson 反序列化时对**缺失的**原始类型字段会填 0，而 0 会被 `@Min(1)` 判成越界——请求在参数校验阶段就被 400 掉，`withDefaults()` 里写的默认值永远来不及生效。换成 `Integer` 之后，「没传」是 null，`@Min`/`@Max` 对 null 是放行的，于是能在 `withDefaults()` 里补默认值；显式传 0 仍然被 `@Min(1)` 拦住回 400。这段推理就写在字段的 Javadoc 里，注释还特意说明「`@Min(1)` 拦在入口，不能在这里再悄悄改成默认值」。

**关键听到**：**Jackson 把缺失的 int 填成 0** / **@Min/@Max 对 null 放行** / **默认值在 withDefaults，越界仍然报错**

**追问**：`withDefaults()` 返回新对象还是改自己？（答：record 不可变，返回新实例）；这种「DTO 自带默认值」和「Controller 用 `@RequestParam(defaultValue=...)`」冲突吗？（答：不冲突，一个是请求体、一个是查询参数，但两者的约定必须一致：省略=默认，越界=报错）

**常见错答**：「用 `int` 性能好一点」——省几个字节，换来一个永远生效不了的默认值。

### JV-33｜L1｜基础｜抽答｜锚点 `backend_java/.../controller/ChatController.java:55`、`:78-81`、`:144-155`

**题**：`@Validated` 标在类上、`@Valid` 标在参数上，各管什么？

**口语答案**：`@Valid` 标在 `@RequestBody` 参数上，触发 DTO 内部字段上的约束（`@NotBlank`、`@Min`、`@Max`），失败抛 `MethodArgumentNotValidException`。类上的 `@Validated` 是 Spring 的校验开关：**方法参数上的** `@Min`/`@Max`（比如 `@RequestParam int limit`）只有在类上标了它才会被校验，失败抛 `ConstraintViolationException`。两个异常都在 `GlobalExceptionHandler` 里映射成 400，所以前端拿到的都是「参数不对」，看不出是哪条链路拦的——这也正是要写契约测试的原因（见 JV-39）。

**关键听到**：**@Valid 管请求体 DTO** / **@Validated 才让方法参数上的约束生效** / **两条链路抛的异常类型不同，但都映射 400**

**追问**：不标 `@Validated` 会怎样？（答：`@Min` 静默失效，越界值直接进业务代码）；消息怎么定制？（答：注解上写 `message = "max_iterations 最大为 50"`，契约测试就是断言这句）

**常见错答**：「DTO 上标了注解就自动校验」——没有 `@Valid` 触发，注解只是元数据。

### JV-34｜L2｜读代码｜抽答｜锚点 `backend_java/.../chat/runtime/ChatPersistence.java:62-130`

**题**：`@Transactional` 为什么加在 `ChatPersistence` 的单个写方法上，而不是整个 `runTurn` 上？

**口语答案**：`runTurn` 一跑可能就是几十秒：流式等模型、等用户确认（最长 10 分钟）。事务开在那里会把数据库连接占满整轮，而 `application.yml` 里 Hikari 的 `maximum-pool-size` 是 1（SQLite 单文件库，写锁粒度粗），一条连接被占住，其它请求全部排队，前端表现为「什么都点不动」。所以事务边界收到最小：`saveMessage`、`saveAssistantMessage`、`touchSession` 各管一次写，各自短事务。另外这类方法里绝不能有网络调用——事务里等 HTTP，等于拿着连接睡觉。

**关键听到**：**事务边界要贴着「一次写」** / **长事务 + 连接池 1 条 = 全站堵死** / **事务里不做 IO/网络调用**

**追问**：那「先存用户消息、再存助手消息」两条不做原子性吗？（答：故意不做的，用户消息要先落库，崩溃时至少不丢输入）；`@Transactional(readOnly = true)` 用在哪合适？（答：纯查询方法，`RagServiceImpl` 里就有几个，能提示驱动走只读路径、少一次 flush）

**常见错答**：「一个请求一个事务最省事」——流式 + 人工确认的场景里，这就是把连接池当锁用。

### JV-35｜L2｜设计｜抽答｜锚点 `backend_java/.../settings/SettingsRegistry.java:197-210`

**题**：这个后端里 `ConcurrentHashMap`、`CopyOnWriteArrayList`、`volatile`、`synchronized` 各用在哪，怎么选？

**口语答案**：按访问模式选。`ConcurrentHashMap` 用在「按 key 存状态」的地方：`PathLock.LOCKS`、`ToolBudgetRegistry.budgets`、`ChatSessionBus.turns`、`ToolCancelRegistry.cancelled`，而且尽量用 `compute`/`computeIfAbsent`/`computeIfPresent` 把这些操作做成原子的——`PathLock` 的引用计数就是靠 `computeIfPresent` 归零返回 null 来自动删键。`CopyOnWriteArrayList` 用在「读极多、写极少」的监听者列表上，设置变更广播时遍历数组快照，不用怕遍历中有人增删监听者。`volatile` 只做可见性标记：`ToolBudgetRegistry.blocked`、`SseAgentEventSink.closed`、`Turn.sink`，都不需要原子复合操作。`synchronized` 用在必须整体互斥的小段逻辑：`TurnBudget.addUsage/exceeded`、`TurnRecorder` 的所有方法——模型回调线程和工具线程会同时写。

**关键听到**：**按读写模式选容器** / **能 compute 就不要 get + synchronized** / **volatile 只做可见性，不做互斥**

**追问**：`synchronized` 方法和 `ReentrantLock` 怎么选？（答：需要 tryLock 超时、需要可中断就用 lock，其它情况 `synchronized` 更不容易漏 unlock）；`CopyOnWriteArrayList` 的代价是什么？（答：每次写都复制整个数组，写多就完了）

**常见错答**：「所有地方都 `Collections.synchronizedMap`」——遍历还得自己加锁，而且拿不到 `computeIfAbsent` 的原子性。

### JV-36｜L2｜读代码｜抽答｜锚点 `backend_java/.../chat/runtime/TurnRecorder.java` + `backend_java/.../chat/runtime/ChatSessionBus.java:88-145`

**题**：`PendingAsk` 用 `record`，`Turn` 和 `TurnRecorder` 用普通类，判断依据是什么？

**口语答案**：看字段需不需要就地改。`PendingAsk(interruptId, future, event)` 是一次性快照，创建后不再变，用 `record` 最省事。`Turn` 不行：`sink`、`stopRequested`、`pending`、`interruptId` 都要被别的线程就地改，而且必须是 `volatile`，`record` 的 final 字段做不到，代码注释里也直接写了「用普通内部类而非 record，因为字段要就地修改」。`TurnRecorder` 是「一轮对话的记事本」，`answer` 是 `StringBuilder`、`toolCalls` 是 `List`、`files` 是 `LinkedHashSet`，全是可变状态，方法统一 `synchronized`，因为模型回调线程和工具线程可能同时往里写。

**关键听到**：**record = 不可变快照** / **需要逐字段 volatile 就只能普通类** / **可变聚合状态用 synchronized 方法**

**追问**：`record` 里的 `List` 字段还能改吗？（答：引用 final，内容能改——所以 `record` 只是浅不可变，`TurnRecorder.toolCalls()` 就特意返回 `List.copyOf`）；为什么 `files` 用 `LinkedHashSet`？（答：去重又保序，用户看到的文件清单顺序要稳定）

**常见错答**：「record 更现代，全用 record」——字段要跨线程就地改的场景，`record` 根本表达不了。

### JV-37｜L3｜找坑｜加分｜锚点 `backend_java/src/main/resources/application.yml:22-30`

**题**：`hikari.maximum-pool-size: 1` 为什么是 1？这不是把并发废了吗？

**口语答案**：是的，就是把并发退化成串行，因为底下是 SQLite 单文件库——它的写锁是库级的，多个连接同时写只会排队，还可能撞上 `database is locked`。配 1 条连接意味着「同一时刻只有一个写」，把锁冲突从运行期挪到了连接池等待，行为更可预测。代价也很明确：任何慢查询或长事务都会把整站阻塞，所以配套的纪律是事务只包单条写（见 JV-34）、不在事务里做网络调用。如果换成 MySQL/PostgreSQL，这个值当然要调大——这是「跟着存储引擎选参数」，不是通用最佳实践。

**关键听到**：**SQLite 写锁是库级的** / **连接数 1 把冲突变成可预期的排队** / **代价是全站串行，必须配合短事务**

**追问**：为什么 `minimum-idle` 也是 1？（答：只有一个连接，空闲连接数不可能更多，配大了没意义）；`spring.sql.init.mode: always` 会不会每次启动重建表？（答：不会，`schema.sql` 里全是 `CREATE TABLE IF NOT EXISTS`）

**常见错答**：「连接池当然越大越好」——对 SQLite 来说池越大，锁冲突越多。

### JV-38｜L2｜读代码｜抽答｜锚点 `backend_java/.../llm/LlmModelFactoryRouter.java`

**题**：新增一个模型供应商，需要改哪些地方？

**口语答案**：只需要加一个类：实现 `LlmModelFactory`，写 `supports(providerId)` 和 `createChatModel`/`createStreamingModel`，标上 `@Component`。`LlmModelFactoryRouter` 构造器注入的是 `List<LlmModelFactory>`——Spring 会把容器里所有实现收集进来，路由靠 `streams().filter(f -> f.supports(providerId)).findFirst()`。找不到就抛 `ApiException(501, "供应商 X 的模型工厂尚未实现：请实现 LlmModelFactory 并注册为 Spring Bean")`，而不是 NPE 或者默默用了错的模型。现在容器里已经有四个：OpenAI 兼容（openai / deepseek / `custom-*`）、Anthropic、Gemini、Ollama。

**关键听到**：**List 注入收集所有实现（策略模式）** / **按 supports() 路由** / **找不到就 501，不猜默认**

**追问**：为什么参数校验放在工厂里而不是 Router 里？（答：每个供应商必填项不同，OpenAI 兼容要 apiKey/baseUrl/model，本地 Ollama 不要 key）；`custom-*` 前缀为什么必须显式给 baseUrl？（答：自定义端点没有可信默认值，猜错就是把密钥发到别人域名）

**常见错答**：「用 `switch (providerId)` 写在一个类里」——每加一个供应商都改同一个类，还容易漏改分支。

### JV-39｜L2｜设计｜加分｜锚点 `backend_java/src/test/.../controller/PageLimitContractTest.java`

**题**：为什么 `limit` 这类参数要用 `@SpringBootTest` + `MockMvc` 做契约测试，而不是单测 service？

**口语答案**：因为契约的真身不是任何一行 Java 代码，而是「注解 + Spring 的校验链路 + 异常处理器」三者联合产生的行为。单测 service 看不到「客户端传 `limit=0` 真的会收到 400」、看不到「默认值真的来自 controller 的 `defaultValue`」、也看不到「`has_more` 真的出现在 JSON 里」。所以用 `@SpringBootTest + @AutoConfigureMockMvc`，断言 `status().isBadRequest()` 加 `jsonPath("$.code").value(400)`，并且两个边界都要测：`0` 和 `max+1` 报错，`max` 本身必须通过。类上还有 `@Transactional`，让每个用例跑完回滚，不污染本地 `app.db`。

**关键听到**：**契约是注解+校验+异常处理的联合行为** / **两个边界都测：越界报错、上限本身通过** / **@Transactional 让用例可重复**

**追问**：为什么单独建 `PageLimitContractTest`，不都塞进 `ChatLimitContractTest`？（答：只测 chat 的话，其它端点悄悄退回「静默截断甚至完全不校验」都不会被发现，`rag/documents` 以前正是完全没有上限的那个）；为什么请求路径要带 `/api`？（答：`context-path=/api`，MockMvc 还要 `.contextPath("/api")`）

**常见错答**：「单测覆盖 service 就够了」——service 里根本没有校验逻辑，测了个空气。

### JV-40｜L3｜设计｜加分｜锚点 `backend_java/.../config/AgentGraphConfig.java:95`

**题**：`AgentGraphConfig.agentGraph()` 直接 `return null`，为什么还能跑？这样写合理吗？

**口语答案**：能跑是因为**实际执行路径根本不走这张图**：对话是 `ChatServiceImpl.runTurn` 里 `AiServices.builder(...).build()` 出来的代理在跑，工具循环由 LangChain4j 的 `maxToolCallingRoundTrips` 控制。LangGraph4j 目前只装配了 `checkpointSaver`（`GraphConfig` 里那个单例 SQLiteSaver），图本身还是注释里的设计草图：`agent →（有工具调用）tools → agent`，`interruptBefore(confirm)`。合理不合理看阶段——作为学习工程，把检查点先接上、图留 TODO 是能接受的；但 Javadoc 里那句 TODO 和 `return null` 必须显式写清楚，否则下一个人会以为「已经有图了」。另外那段注释里有个容易被忽略的设计：**刻意不注入 `StreamingChatModel`**，因为模型每轮按设置现建，容器里没有这个 Bean，声明成形参会让启动直接失败。

**关键听到**：**实际路径是 AiServices，不是图** / **只装配了 checkpointSaver** / **不注入 StreamingChatModel 是刻意的**

**追问**：为什么检查点先接上？（答：图一旦接上，`interruptBefore` + 同一 `threadId` 的 `GraphInput.resume` 就能做「确认后恢复」，而现在的实现是靠 `ChatSessionBus` 的 `CompletableFuture` 手工挡）；`return null` 有什么风险？（答：有人把 `agentGraph` 注进去用，会在运行期 NPE；更稳的做法是不声明这个 Bean，或者抛「尚未实现」）

**常见错答**：「有 LangGraph4j 依赖就说明用了 LangGraph4j」——依赖、Bean、真正执行的代码是三件事。
