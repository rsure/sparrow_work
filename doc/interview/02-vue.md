# 02 · 前端（Vue3/TS + Electron 桌面运行时）面试题

## 本卷说明

- **使用场景**：一面技术面。面试官照着每题的「题」念，听「口语答案」里必须出现的关键词，再按「追问」往下压一层；候选人 1~3 年前端经验，共享屏幕打开锚点文件边看边答。
- **锚定真实代码**：每题都给了仓库内的文件与行号（当前 HEAD 采集），候选人可当场打开。行号会随代码演进漂移，**以文件与函数名为准**。
- **不考提示词**：本卷只考前端工程能力；提示词相关另有 `doc/interview/05-prompt.md`。
- **编号**：VUE-01 ~ VUE-40，题目按「AI 前端交互 → Vue3/TS 基础 → Electron 桌面运行时」三块排列，同一块内不重复考点。

## 构成与配额

| 块 | 题号 | 题数 |
| --- | --- | --- |
| AI 前端交互（流式渲染、SSE/NDJSON 解析、会话状态、停止/重试、Markdown 渲染） | VUE-01 ~ VUE-18 | 18 |
| Vue3 / TS 基础（响应式、composable、组件通信、类型、请求封装、测试） | VUE-19 ~ VUE-35 | 17 |
| Electron 桌面运行时（后端子进程生命周期、健康探测、受限 IPC、退出清理） | VUE-36 ~ VUE-40 | 5 |

| 维度 | 配额 | 实际 |
| --- | --- | --- |
| 分堆 | 必答 12 / 抽答 20 / 加分 8 | 12 / 20 / 8 |
| 难度 | L3 不超过 8 道 | L3 6 道（L1 6 / L2 28） |
| 题型 | 基础 / 读代码 / 找坑 / 设计 | 5 / 23 / 7 / 5 |

## 分堆规则（面试官怎么用）

- **必答 12 道**：开场到中段的骨架，覆盖流式解析、停止、渲染安全、响应式、请求封装、测试基建、后端探测。全部念完约 35~45 分钟，任一道答不上来要当场追问到能判断「会/不会」为止。
- **抽答 20 道**：按候选人简历与岗位方向挑 6~8 道。做过 AI 应用的优先抽 VUE-02/05/09/11/15，做过后台管理系统或纯 Vue 的优先抽 VUE-20/21/23/28/29。
- **加分 8 道**：区分「熟手」与「有判断力」。答不出不扣分，答出关键取舍（如「防抖会让流式输出饿死」）才给分。
- 同一块内如果候选人已在前一题自然带出某考点，后面那题可跳过，**不要为了念完题目而重复追问**。

## 题目一览

| 题号 | 难度 | 题型 | 分堆 | 锚点 |
| --- | --- | --- | --- | --- |
| VUE-01 | L2 | 读代码 | 必答 | `frontend/src/services/request.ts:192-215` |
| VUE-02 | L2 | 基础 | 抽答 | `frontend/src/services/request.ts:168-206` |
| VUE-03 | L1 | 读代码 | 抽答 | `frontend/src/services/request.ts:174-190` |
| VUE-04 | L2 | 读代码 | 必答 | `frontend/src/services/request.ts:256-291` |
| VUE-05 | L2 | 设计 | 抽答 | `frontend/src/services/request.ts:143`、`frontend/src/composables/useFileScan.ts:83-104` |
| VUE-06 | L2 | 读代码 | 必答 | `frontend/src/stores/chat.ts:204-205`、`:1193-1210` |
| VUE-07 | L3 | 找坑 | 加分 | `frontend/src/stores/chat.ts:1162-1184` |
| VUE-08 | L2 | 读代码 | 必答 | `frontend/src/stores/chat.ts:964-970`、`:1000-1003` |
| VUE-09 | L3 | 设计 | 加分 | `frontend/src/components/MarkdownView.vue:191-218` |
| VUE-10 | L2 | 读代码 | 必答 | `frontend/src/components/MarkdownView.vue:1-14`、`:161-167` |
| VUE-11 | L2 | 读代码 | 抽答 | `frontend/src/components/MarkdownView.vue:28-42`、`:84-102` |
| VUE-12 | L2 | 读代码 | 抽答 | `frontend/src/components/MarkdownView.vue:133-153`、`:224-241` |
| VUE-13 | L3 | 找坑 | 加分 | `frontend/src/views/chat/MessageList.vue:61-66`、`:74-79` |
| VUE-14 | L2 | 读代码 | 必答 | `frontend/src/stores/chat.ts:1131-1160` |
| VUE-15 | L1 | 读代码 | 抽答 | `frontend/src/composables/useFileSegments.ts:33-65` |
| VUE-16 | L1 | 读代码 | 抽答 | `frontend/src/stores/chat.ts:161-190`、`:216-226` |
| VUE-17 | L2 | 设计 | 加分 | `frontend/src/stores/chat.ts:1219-1241` |
| VUE-18 | L2 | 读代码 | 抽答 | `frontend/src/stores/chat.ts:1081-1101` |
| VUE-19 | L2 | 读代码 | 必答 | `frontend/src/composables/useDebouncedRef.ts:12-39` |
| VUE-20 | L2 | 读代码 | 抽答 | `frontend/src/composables/useFileFilter.ts:47-59` |
| VUE-21 | L2 | 找坑 | 抽答 | `frontend/src/composables/useFileFilter.ts:79-102` |
| VUE-22 | L2 | 基础 | 必答 | `frontend/src/stores/chat.ts:967-970`、`:1008-1019` |
| VUE-23 | L2 | 读代码 | 抽答 | `frontend/src/views/chat/MessageList.vue:26-42` |
| VUE-24 | L1 | 基础 | 必答 | `frontend/src/components/MarkdownView.vue:53-69` |
| VUE-25 | L1 | 基础 | 必答 | `frontend/src/services/request.ts:3-30` |
| VUE-26 | L2 | 读代码 | 抽答 | `frontend/src/services/request.ts:40-66` |
| VUE-27 | L2 | 读代码 | 必答 | `frontend/src/services/http.ts:13-31`、`:42-46` |
| VUE-28 | L1 | 基础 | 抽答 | `frontend/src/stores/chat.ts:1-13` |
| VUE-29 | L2 | 读代码 | 抽答 | `frontend/src/components/MarkdownView.vue:268-282`、`:372-378` |
| VUE-30 | L3 | 找坑 | 加分 | `frontend/src/services/http.ts:48-64`、`frontend/src/services/request.ts:40` |
| VUE-31 | L2 | 读代码 | 抽答 | `frontend/vitest.config.ts:20-41` |
| VUE-32 | L3 | 找坑 | 抽答 | `doc/29-前端测试基建.md:199-215` |
| VUE-33 | L2 | 设计 | 加分 | `doc/29-前端测试基建.md:162-183` |
| VUE-34 | L2 | 读代码 | 抽答 | `doc/29-前端测试基建.md:85-101` |
| VUE-35 | L2 | 找坑 | 加分 | `frontend/src/composables/useFileFilter.ts:20-32`、`:84-100` |
| VUE-36 | L2 | 读代码 | 必答 | `electron/src/main/backend.ts:70-90` |
| VUE-37 | L2 | 读代码 | 抽答 | `electron/src/main/backend.ts:300-350` |
| VUE-38 | L3 | 设计 | 抽答 | `electron/src/main/backend.ts:270-289` |
| VUE-39 | L2 | 找坑 | 加分 | `electron/src/main/backend.ts:386-409` |
| VUE-40 | L2 | 读代码 | 抽答 | `electron/src/main/index.ts:108-132`、`:138-201` |

---

### VUE-01｜L2｜读代码｜必答｜锚点 `frontend/src/services/request.ts:192-215`

**题**：这段 `while ((sep = buffer.indexOf('\n\n')) >= 0)` 为什么按空行切帧，还要先做 `\r\n` 归一、末尾再补一帧？

**口语答案**：SSE 规范里一个事件以空行结束，事件内部的多行 `data:` 属于同一条消息，所以只能按 `\n\n` 切；按单个 `\n` 切会把一条消息拆成好几条。不同服务端和代理发的换行可能是 `\r\n`，不统一的话 `\n\n` 根本找不到，整条流会卡在缓冲区里出不来。最后一个事件可能没有以空行收尾，所以循环结束后缓冲区里剩下的内容还要再 dispatch 一次。这里用 `indexOf` 从缓冲区逐帧"切走"，而不是每次 read 都 `split` 一份新数组，长回答时内存和计算都更省。

**关键听到**：**一个事件可以跨多行** / **`\r\n` 与 `\n\n` 的差异必须归一** / **末尾可能没有空行，要兜底补一帧** / **增量切帧而不是整体 split**

**追问**：如果 `\r` 和 `\n` 恰好被切在两个网络分片里，这个 `replace` 会漏掉吗？（答：不会漏——`replace` 每轮都对整个 buffer 做，上一轮残留的 `\r` 会和下一轮开头的 `\n` 拼成 `\r\n` 被替换；代价是每轮都扫一遍整个缓冲区，回答特别长时是 O(n²)，要优化就得记住已扫描位置。）

**常见错答**：「按 `\n` 切就够，反正一行一个事件」——忽略了一个事件可以有多行 `data:`，也忽略了 `\r\n`。

### VUE-02｜L2｜基础｜抽答｜锚点 `frontend/src/services/request.ts:168-206`

**题**：`decoder.decode(value, { stream: true })` 里的 `stream: true` 解决什么问题？不写会怎样？

**口语答案**：fetch 的 chunk 是按字节切，不保证落在 UTF-8 字符边界上，一个汉字的 3 个字节可能被分到两次 read 里。`stream: true` 让 TextDecoder 把结尾不完整的多字节序列留在内部，等下一块数据到了再拼起来，不会吐出替换字符。所以配套的 `buffer` 也必须跨 read 保留，不能每次 read 各自 parse。如果每次 read 都新建 decoder 或者忘了这个参数，中文就会偶发变成乱码方块，而且是概率性的、极难复现。

**关键听到**：**字节流按 chunk 切、不按字符边界切** / **decoder 内部保留残字节** / **buffer 要跨 chunk 累积**

**追问**：那流结束时如果缓冲里只剩半个字符呢？（答：代码在循环后没有再调一次 `decoder.decode()` 冲刷，这半个字符会留在 decoder 里丢掉；严谨写法是循环结束后补一次 `decoder.decode()` 拼进 buffer，再走末尾兜底 dispatch。）

**常见错答**：「浏览器会自动处理编码」——这是手动 `TextDecoder` 解码，边界问题得自己兜。

### VUE-03｜L1｜读代码｜抽答｜锚点 `frontend/src/services/request.ts:174-190`

**题**：`dispatch` 里为什么默认事件名是 `message`、遇到 `:` 开头就跳过、JSON 解析失败还要回调 `{ raw }`？

**口语答案**：SSE 规范规定没有 `event:` 字段时事件名就是 `message`，所以初值写 `'message'`，否则上层按事件名分发时会全部落到 default，事件被静默丢掉。`:` 开头是注释行，服务端常用它做心跳保活、防止中间代理掐掉空闲连接，它没有负载，跳过是对的。`JSON.parse` 失败时不能把整条流打断——后端偶发写出纯文本时按 `{ raw: payload }` 透传，至少内容还能显示出来。

**关键听到**：**默认事件名是 message** / **注释行是心跳、没有负载** / **单帧解析失败不能废掉整条流**

**追问**：`data:` 后面为什么用 `trimStart()` 而不是 `trim()`？（答：规范只允许去掉冒号后的一个前导空格，多余的前导空格和末尾空格都属于内容；`trim()` 会把有意义的末尾空白也吃掉。）

**常见错答**：「解析失败就 throw，让上层重试」——一条脏帧会让已经渲染的半条回答全部作废。

### VUE-04｜L2｜读代码｜必答｜锚点 `frontend/src/services/request.ts:256-291`

**题**：NDJSON 读取器为什么按 `\n` 切行、收到 `complete` 就主动 `cancel()`，而不是等连接自然关闭？

**口语答案**：NDJSON 的约定是一行一个完整 JSON 对象，所以按换行切；这和 SSE 的「空行分隔、事件可多行」是两套完全不同的协议。后端在最后一条消息里带 `complete: true`，说明数据已经齐了，再等 TCP 连接关闭没有意义；主动 `reader.cancel()` 能立刻释放底层 body 和连接，避免某些代理下连接半挂着、reader 一直占着不放手。末尾也会补一行，因为最后一条消息可能没有换行符。

**关键听到**：**按行解析、一行一个对象** / **`complete` 是协议层的结束信号** / **主动 cancel 释放 body**

**追问**：`cancel()` 之后 `finally` 里的 `releaseLock()` 还需要吗？（答：需要。cancel 只是取消流，锁还在 reader 身上；不 releaseLock，之后想再读 `response.body` 会报 body 已 locked。）

**常见错答**：「`complete` 只是给界面看的标记」——它同时是读取循环的退出条件。

### VUE-05｜L2｜设计｜抽答｜锚点 `frontend/src/services/request.ts:143`、`frontend/src/composables/useFileScan.ts:83-104`

**题**：扫描页用原生 `EventSource`，对话用 `fetch` 加手写 SSE 解析，为什么不统一成一种？

**口语答案**：`EventSource` 只能发 GET、不能带自定义 header、也不能带请求体，浏览器还会自动重连；扫描的文件推送正好是「GET + 长期订阅 + 断了想自动重连」，用它最省事，代码就是几行 `addEventListener`。对话是 POST、要带 JSON body、还要能被 `AbortController` 取消，`EventSource` 做不到，只能 fetch 拿 body 流自己解析。代价是两套代码、两种错误处理，所以 `request.ts` 那套解析才要写全：切帧、解码、兜底都得自己兜。

**关键听到**：**EventSource 只能 GET、无 body、无自定义 header** / **对话需要 POST + AbortController** / **自动重连是特性也是坑**

**追问**：`EventSource` 的自动重连在什么场景是坑？（答：任务已经结束或后端返回 204 时它仍会按默认间隔重连，造成无意义请求；所以本项目在收到 `end`、或在 `onerror` 里都主动 `close()`。）

**常见错答**：「EventSource 也支持 POST」——不支持，这是它和 fetch 流最直接的分界。

### VUE-06｜L2｜读代码｜必答｜锚点 `frontend/src/stores/chat.ts:204-205`、`:1193-1210`

**题**：点「终止」为什么先调 `stop_chat`、再等 3 秒才 `abort`，而不是直接断连接？

**口语答案**：直接 abort 只是前端不读了，后端那一轮 Agent 还在跑，工具还在写文件、还在烧 token，换个页面回来还能看到它继续。先 `POST /chat/stop` 是让后端自己收尾并推一条 `stopped` 事件，前端才能拿到「已终止」的半截回答。3 秒是兜底：后端卡在某个同步工具里不响应时，前端不能无限等，超时就 abort 掉连接，至少让界面恢复可输入。`stopRequested` 同时用来压制 catch 里的「对话失败」提示，避免用户点了终止还挨一次报错。

**关键听到**：**前端断开 ≠ 后端停止** / **先优雅停止再兜底强断** / **3 秒是超时兜底不是延时**

**追问**：`this.abortController` 为什么在 finally 里置 null？（答：防止下一轮误用上一轮已经 abort 的 controller；也让 `stop()` 里的 `abortController?.abort()` 只可能作用在当前这一轮。）

**常见错答**：「终止就是不再渲染」——后端进程照跑，时间和 token 照烧。

### VUE-07｜L3｜找坑｜加分｜锚点 `frontend/src/stores/chat.ts:1162-1184`

**题**：这段 `catch` / `finally` 里哪些状态必须复位？漏掉一个会出什么问题？

**口语答案**：`bubble.streaming`、`statusText`、`sending`、`stopRequested`、`abortController`、`steerQueued` 都必须在 finally 里复位，否则下一轮 `send()` 会被 `this.sending` 直接挡掉，发送按钮永远转圈。`catch` 里先判 `this.stopRequested`：用户主动终止导致的 AbortError 不是故障，不能弹「对话失败」。还有一处细节是先判 `if (!bubble.content)` 才写错误文案，因为流到一半才失败时不该覆盖已经显示的内容。`loadSessions` 和 `refreshUsage` 用 `void` 发出去，不阻塞本轮收尾。

**关键听到**：**finally 统一兜底复位** / **主动终止不算错误** / **不覆盖已有内容** / **收尾刷新不阻塞**

**追问**：finally 里重置 `stopRequested`，会不会把上一轮的终止状态带进下一轮？（答：不会，`stop()` 只对当前在跑的轮次有效；重置于收尾时执行，下一轮 `send()` 开头本来也会再置一次 false。）

**常见错答**：「catch 里统一 `showToast(error)`」——用户点终止也会被弹一次，看起来像操作失败。

### VUE-08｜L2｜读代码｜必答｜锚点 `frontend/src/stores/chat.ts:964-970`、`:1000-1003`

**题**：为什么要先 push 一条 content 为空、`streaming: true` 的助手气泡，再取 `messages[messages.length - 1]`？

**口语答案**：先占位是为了让界面立刻出现「正在回答」的光标，用户知道请求已经发出去了，而不是等第一个 token 才看到反应。取数组最后一个元素而不是复用 push 时那个对象，是因为 Vue 的响应式是读时包装：push 进去的是原始对象，直接改它不触发更新，必须通过下标拿到的代理对象去改。后面 `onToken` 就是往这个代理上累加 `content`，所以流式内容会一段段长出来。

**关键听到**：**先占位给即时反馈** / **必须改代理对象** / **`content += chunk` 增量追加**

**追问**：下一行的 `bubble.tools as UIToolCall[]` 为什么也要单独取一次？（答：`tools` 在类型上是可选的，这里刚 push 时给了 `[]`，取出来给 `onToolStart` / `onToolEnd` 这些回调闭包捕获，后面就不用每处都判空；同一个气泡的工具轨迹都往这个数组里塞。）

**常见错答**：「直接改 push 的那个对象就行」——页面一动不动，这是流式渲染最经典的坑。

### VUE-09｜L3｜设计｜加分｜锚点 `frontend/src/components/MarkdownView.vue:191-218`

**题**：流式输出时每 60ms 才重渲染一次，为什么不是每个 token 都渲染，也不是做防抖？

**口语答案**：每个 token 都跑一遍 markdown-it + DOMPurify + highlight.js，是纯 CPU 的同步开销，长回答会明显掉帧。也不能做防抖（等输出停下来再渲染）：模型持续输出时防抖永远不触发，界面会一直空着，用户以为卡死。60ms 是节流：窗口内来的 token 合并，到点用最新的 content 渲染一次，约 16fps，肉眼几乎看不出延迟，而解析次数被压到很小。代价是首个 token 最多晚 60ms 出现，这就是「平滑度 vs 首字延迟」的取舍。

**关键听到**：**解析+净化是同步 CPU 开销** / **防抖会让持续输出饿死** / **节流合并窗口内变更** / **首字延迟 vs 平滑度的取舍**

**追问**：为什么是 `if (pending !== null) return` 而不是重置定时器？（答：重置会变成「最后一次变化后 60ms 才渲染」，持续输出时不断后移，又回到防抖的饥饿问题；现在是固定窗口节流。）

**常见错答**：「换成 `requestAnimationFrame` 就一定更流畅」——解析是长任务，一帧内做不完，跟着屏幕刷新反而更容易掉帧；固定 60ms 更可控。

### VUE-10｜L2｜读代码｜必答｜锚点 `frontend/src/components/MarkdownView.vue:1-14`、`:161-167`

**题**：为什么说 `MarkdownView` 是「必须唯一」的渲染入口？`html: true` 开着不怕 XSS 吗？

**口语答案**：后端文本是 LLM 输出，属于不可信内容，里面完全可以夹 `<img onerror=...>`；一旦某处直接 `v-html` 原始文本，脚本就能在 Electron 渲染进程里跑，能读本地路径、能发请求。`markdown-it` 开 `html: true` 是为了让 `<br>`、`<details>` 这类结构能用，安全性交给后一步 `DOMPurify.sanitize`：它按白名单删掉 `script`/`iframe`、剥掉 `on*` 事件和 `javascript:` 协议。所以规矩是「任何 HTML 都要过这两步」，组件外部不许自己拼 HTML 再 `v-html`。

**关键听到**：**LLM 输出不可信** / **markdown-it 出 HTML → DOMPurify 净化 → v-html 唯一链路** / **DOMPurify 按白名单净化**

**追问**：`sanitize(raw, { ADD_ATTR: ['data-lang'] })` 为什么只额外放行这一个属性？（答：默认白名单已经放行 `class`（高亮和布局都靠它），而代码块的语言标签写在 `data-lang` 上、默认会被剥掉，所以显式加；白名单越小，攻击面越小。）

**常见错答**：「DOMPurify 会把 Markdown 样式弄坏，所以只在有风险时用」——净化是默认路径，跳过它才是漏洞。

### VUE-11｜L2｜读代码｜抽答｜锚点 `frontend/src/components/MarkdownView.vue:28-42`、`:84-102`

**题**：为什么只引 `highlight.js/lib/core` 再逐个注册语言，还要 `registerAliases`？

**口语答案**：全量 `highlight.js` 会把主包撑到 900kB 以上，而桌面端只在聊天里渲染代码块，没必要把所有语言都打进去。core 只有调度没有语法，逐个 `registerLanguage` 才会真正带上对应的语言包。不注册的语言 `hljs.getLanguage` 返回假，代码走 `highlightAuto` 或纯文本，不会报错。`registerAliases` 解决的是标记名不一致：用户写 ` ```vue `、` ```ts `、` ```sh `，注册的是 xml / typescript / bash，不登记别名就会被当成未知语言。

**关键听到**：**全量包 900kB+** / **core 只是调度器** / **别名要单独注册** / **未注册语言要能降级不报错**

**追问**：`highlightAuto` 在长代码上有什么风险？（答：它要试遍已注册语言，成本远高于指定语言；所以只在语言未知时用，而且这里已经通过只注册十来种语言把候选集压小了。）

**常见错答**：「按需引入只影响首屏体积」——注册表小了，自动识别的耗电也一起变小，是双收益。

### VUE-12｜L2｜读代码｜抽答｜锚点 `frontend/src/components/MarkdownView.vue:133-153`、`:224-241`

**题**：为什么要重写 `md.renderer.rules.fence`，复制按钮又为什么用事件委托挂在根节点上？

**口语答案**：默认 fence 只吐 `<pre><code>`，既拿不到语言名、也没地方放复制按钮；重写之后才能拼出「语言标签 + 按钮 + 高亮后的 code」这套结构，语言名从 `token.info` 取，` ```ts title=x ` 这种只取第一段。复制按钮是 HTML 字符串生成的，不是 Vue 模板，绑不上 `@click`，所以用事件委托：根节点挂一个 click，用 `closest('.md-code__copy')` 判断命中的是不是按钮。按钮里不内联代码文本（超长内容塞进属性会爆），点击时从 DOM 读 `code.textContent`。

**关键听到**：**默认 fence 不够用** / **语言标签走 data-lang** / **HTML 字符串拿不到 Vue 事件，用事件委托** / **代码不内联进属性**

**追问**：为什么语言名要过一遍 `escapeAttr`？（答：语言标记来自用户/模型写的 Markdown，直接拼进 `data-lang="..."` 可能用引号闭合属性注入 HTML；这里先转义实体，再交给 DOMPurify，是双保险。）

**常见错答**：「用 inline `onclick` 更省事」——DOMPurify 默认就剥掉 `on*` 属性，写进去也不会执行。

### VUE-13｜L3｜找坑｜加分｜锚点 `frontend/src/views/chat/MessageList.vue:61-66`、`:74-79`

**题**：`MessageList` 直接 `v-for` 全量渲染所有消息，长会话会有什么问题？现在靠什么撑着？

**口语答案**：所有历史消息一直留在 DOM 里，每条助手消息里又有 markdown 生成的几十个节点和 highlight.js 的 span，轮次一多节点数线性上涨。而流式输出每来一个 token 都会触发一次「读 `scrollHeight` 再写 `scrollTop`」，读 `scrollHeight` 会强制同步布局，节点越多越贵，表现就是越长越卡、滚动发涩。现在靠「单次会话不长 + 渲染已经节流」撑着，既没有虚拟列表也没有分片加载。真要做，方向是虚拟滚动只渲染视口附近，或者把旧消息折叠/分页。

**关键听到**：**消息全量常驻 DOM** / **节点数随轮次线性增长** / **读 scrollHeight 强制同步布局** / **没有虚拟列表是已知缺口**

**追问**：为什么「读 `scrollHeight`」特别贵？（答：它需要最新的布局结果，而前面刚改过 DOM，浏览器必须先同步 reflow 才能返回准确值；放在 `nextTick` 里只保证 DOM 更新完，并不减少每次测量的成本。）

**常见错答**：「加个 `contain: layout` 或 `will-change` 就解决了」——那只减少重绘范围，节点数和布局成本还在。

### VUE-14｜L2｜读代码｜必答｜锚点 `frontend/src/stores/chat.ts:1131-1160`

**题**：AI 要改文件时，为什么用「后端暂停 + 前端弹窗 + `chat_resume` 续跑」，而不是前端弹完确认再发新请求？

**口语答案**：工具调用是后端 Agent 循环里的一步，前端没法在中间插进去；所以后端在真正执行前发 `confirm_required` 并结束本次流，把 `interrupt_id` 交给前端。前端弹窗拿到用户决定后调 `chat_resume`，带上 `session_id`、`interrupt_id` 和 `approved/remember`，后端从断点继续，上下文和工具状态都还在。一轮里可能连续多次确认，比如先覆盖 A 再改 B，所以用 `pendingAsks` 队列加 while 循环，每次恢复后还可能再推一条新的确认。

**关键听到**：**confirm_required 结束本次流** / **interrupt_id 是断点凭据** / **chat_resume 带着决定续跑** / **多次确认要队列 + 循环**

**追问**：为什么弹窗期间把 `bubble.streaming` 置 false、同意后再置 true？（答：「正在生成」是假的，光标不该继续闪；恢复后重新打开，用户才知道模型又跑起来了。）

**常见错答**：「前端弹完确认就重新 `send` 一条」——那会变成新一轮提问，后端已经准备好的工具上下文丢了。

### VUE-15｜L1｜读代码｜抽答｜锚点 `frontend/src/composables/useFileSegments.ts:33-65`

**题**：`splitFileSegments` 为什么把候选按字符串长度倒序排，再在正文里找「最靠前」的命中？

**口语答案**：同一个文件在正文里可能以完整路径出现、也可能只出现文件名；如果先匹配 `a.md`，`d:/docs/a.md` 就只剩前半截文字加一个胶囊，路径信息丢了。所以先按长度倒序，长串优先。同时每轮还要在所有候选里取 `index` 最小的那个，保证片段顺序和正文顺序一致，不能因为长串在后面就先切后面。找不到命中就把剩余文本整段收尾，循环结束。

**关键听到**：**长串优先避免半截匹配** / **最靠前命中保证正文顺序** / **剩余文本收尾**

**追问**：如果某个文件的 `name` 是空字符串会怎样？（答：`indexOf('')` 恒为 0，切出来的长度是 0，`rest` 不会变短，就成了死循环；这里隐含依赖后端给的 name/path 非空，稳妥做法是先过滤掉空 key。）

**常见错答**：「用正则把所有路径替换成胶囊」——Windows 反斜杠和特殊字符转义容易漏，而且替换后就绑不上点击事件了。

### VUE-16｜L1｜读代码｜抽答｜锚点 `frontend/src/stores/chat.ts:161-190`、`:216-226`

**题**：确认弹窗的标题和参数名为什么要用 `CONFIRM_TITLE` / `CONFIRM_ARG_LABEL` 两张映射表？

**口语答案**：后端只给工具名和入参，比如 `write_file`、`path`、`content`，直接显示给用户就是英文技术词，用户根本不知道自己在同意什么。映射表把工具名翻成「确认覆盖文件」这种动作描述，把参数名翻成「路径 / 写入内容」，用户才能判断风险。后端没给标题时用映射兜底，遇到未知工具名就退回原样显示，新增工具也不会崩。参数值还有 200 字符截断，避免一段巨大 content 把弹窗撑爆。

**关键听到**：**把技术词翻译成用户能判断的动作** / **映射 + 兜底，不硬编码全量文案** / **超长参数要截断**

**追问**：为什么映射表里还专门有 `replan`（确认新的执行计划）？（答：它是「子任务失败后模型想改计划」的确认，不是文件写入；如果不单独给文案，用户会以为又要动文件，判断依据就错了。）

**常见错答**：「把入参 JSON 直接打给用户看」——面对一屏参数点「同意」，等于没确认。

### VUE-17｜L2｜设计｜加分｜锚点 `frontend/src/stores/chat.ts:1219-1241`

**题**：「执行中插话」为什么界面显示「排队中」而不是「已发送」？

**口语答案**：后端不会立刻打断正在跑的工具（同步工具没法安全中断），而是等当前工具结束、把这句话拼进工具结果，模型下一步才看得到。所以前端如实显示「已插话，当前工具结束后生效（排队 N 条）」，`steerQueued` 用后端返回的 `pending` 校正，收到 `onSteerInjected` 才减一。这样用户不会以为模型马上改主意；如果显示「已发送」，用户会盯着没变化的输出以为坏了。

**关键听到**：**插话不打断当前工具** / **在工具边界注入上下文** / **排队数是后端权威值** / **如实反馈避免误判**

**追问**：`steer()` 里为什么先判 `if (!sid)`？（答：会话 id 要等首轮流里的 `session_ready` 或 `done` 才有；没有 id 就没有落点，只能提示「会话还没建立」。）

**常见错答**：「插话就是 push 进下一轮」——那已经不是插话，是本轮结束后的新提问。

### VUE-18｜L2｜读代码｜抽答｜锚点 `frontend/src/stores/chat.ts:1081-1101`

**题**：`onDone` 里为什么用 `data.answer` 覆盖前端已经拼好的 `bubble.content`？

**口语答案**：前端拼的是流式增量，可能因为网络问题丢帧，也可能用户中途重连；后端落库的那份才是完整、权威的回答。用 `done.answer` 覆盖一次，能同时修好「丢帧」和「刷新后回放」两种场景。同理 `files`、`usage`、`model`、`elapsed`、`subtasks` 都以后端返回为准，前端只负责过程展示。store 自己也明确不落库——消息由后端 SQLite 持久化，避免两份数据打架。

**关键听到**：**后端结果是权威值** / **流式增量可能丢帧** / **覆盖能兼容刷新回放** / **前端不落库，避免双份数据**

**追问**：那为什么流式过程中还要拼 `content`？（答：为了实时性，等 done 才有内容就不叫流式了；覆盖发生在最后一步，用户几乎感知不到。）

**常见错答**：「前端拼的已经是最终结果，不用覆盖」——一次丢帧就留下半句话，还和后端库里的不一致。

### VUE-19｜L2｜读代码｜必答｜锚点 `frontend/src/composables/useDebouncedRef.ts:12-39`

**题**：`useDebouncedRef` 为什么用 `customRef` 手写，而不是 `ref` 加 `watch` 再延迟赋值？

**口语答案**：`customRef` 把 get/set 完全交给自己控：get 里 `track()` 建依赖、返回「已生效的旧值」；set 里不立刻改，而是先清掉上一个定时器、等 delay 到点再 `value = newValue` 加 `trigger()`。这样封装出来就是一个普通 ref，读写语法不变，调用方不需要知道里面做了防抖。用 `ref + watch` 也能实现，但会多一层「谁在监听谁」、清理容易漏，而且 watch 里的赋值又可能触发循环。`onScopeDispose` 保证组件卸载时清掉未到期的定时器，否则回调会在销毁后触发更新。

**关键听到**：**customRef 自己控制 track / trigger** / **延迟的是值生效，不是回调执行** / **连续写入只留最后一次** / **onScopeDispose 清定时器**

**追问**：为什么测试里必须把它放进 `effectScope()`？（答：`onScopeDispose` 只有在活跃的 effect scope 里才注册得上，裸调用会告警且清理不生效，用例之间会互相污染。）

**常见错答**：「防抖就是延迟执行回调」——这里延迟的是「值生效」，窗口期内读到的还是旧值，输入框回显会卡。

### VUE-20｜L2｜读代码｜抽答｜锚点 `frontend/src/composables/useFileFilter.ts:47-59`

**题**：输入框要「立刻回显」、过滤要「防抖后生效」，这两个矛盾需求怎么用一个可写 `computed` 桥接？

**口语答案**：`rawKeyword` 是真正的输入值，set 时立刻更新，所以输入框不卡；`delayKeyWord` 用 `useDebouncedRef`，200ms 后才生效，`filtered` 只读它。`keyword` 这个 computed 的 get 返回 `rawKeyword`，负责回显；set 同时写两个，负责桥接，模板里 `v-model="keyword"` 一行就够。这样「即时」和「防抖」各归各的变量，不需要在模板里写两套绑定。

**关键听到**：**可写 computed 同时有 get/set** / **回显走原始值、过滤走防抖值** / **200ms 内不重算列表**

**追问**：`reset()` 里为什么写 `keyword.value = ''` 而不是 `rawKeyword.value = ''`？（答：走 setter 才能同时清掉防抖值，否则 200ms 后旧关键词会再冒出来，列表闪一下。）

**常见错答**：「`v-model` 直接绑到防抖 ref 上」——输入框会卡顿、乃至回退，因为读到的一直是旧值。

### VUE-21｜L2｜找坑｜抽答｜锚点 `frontend/src/composables/useFileFilter.ts:79-102`

**题**：`visible` 里为什么一定要 `[...filtered.value].sort(...)`？`assertFilteredUnmutated` 又在防什么？

**口语答案**：`Array.prototype.sort` 是原地排序，直接排 `filtered.value` 会改掉 computed 缓存的那个数组；而 `filtered` 是上游 `source.filter()` 的结果，被改了之后，在下次关键词变化重算之前，`filtered` 的顺序就错了，`totalSize` 这类依赖它的东西也会跟着错。所以先浅拷贝再排。开发期断言拿排序前的路径快照和排序后的 `filtered` 对比，一旦有人改回原地排序，DEV 下立刻抛错，而不是等用户看到列表错乱。生产构建里 `import.meta.env.DEV` 为 false，快照不生成、断言被 tree-shake 掉，运行时零成本。

**关键听到**：**sort 原地排序会污染上游缓存** / **先复制再排** / **开发期断言抓回归** / **DEV 分支生产被裁剪**

**追问**：为什么用「路径快照」而不是比较数组引用？（答：引用比较只能发现「换了个数组」，发现不了「同一个数组内容被重排」；按 path 逐项比才能抓到顺序变化。）

**常见错答**：「computed 是只读的，sort 改不了它」——只读的是 `.value` 的赋值，数组内容照样能改。

### VUE-22｜L2｜基础｜必答｜锚点 `frontend/src/stores/chat.ts:967-970`、`:1008-1019`

**题**：为什么改 push 进数组的那个原始对象不触发更新，而 `tools[i] = { ...tools[i], output }` 可以？

**口语答案**：Vue3 的响应式是「读时包装」：`ref`/`reactive` 在 get 时把对象包成 Proxy 返回，push 进去的原始对象本身没被改写，直接改它的属性不经过 Proxy，自然不触发 `trigger`。从 `messages[i]` 或 `tools[i]` 读出来的才是代理，改代理才会被追踪。所以回填工具结果时用「下标替换成新对象」：既走了数组的响应式写入，也不依赖旧对象是不是代理。这也是 `findLastToolIndex` 返回下标而不是对象的原因。

**关键听到**：**读时包装** / **只有经过 Proxy 的写才被拦截** / **下标替换元素触发数组更新** / **索引定位避免持有原始对象**

**追问**：那为什么不统一用 `reactive` 再直接改属性？（答：元素替换更直观，也不会因为某个元素被替换成普通对象而丢掉响应性；两种写法混用才是真正的坑。）

**常见错答**：「Vue3 用了 Proxy，所以改原对象也会更新」——只有经过代理的写才会被拦截。

### VUE-23｜L2｜读代码｜抽答｜锚点 `frontend/src/views/chat/MessageList.vue:26-42`

**题**：`scrollToBottom` 里为什么要 `nextTick`？watch 的三个信号分别覆盖什么场景？

**口语答案**：改完 `store.messages` 之后 DOM 还没更新，此刻读 `scrollHeight` 拿到的是旧高度，滚不到底，所以要把「读 DOM」放进 `nextTick` 回调。三个信号分别是：条数变化（新消息入列）、最后一条 content 长度变化（流式追加）、`statusText` 变化（阶段提示行出现或消失）；后两者都会改变容器高度，只监听条数就会漏掉流式下半程。用「条数 + 最后一条长度」而不是深监听整个数组，是成本最低又能覆盖追加的写法。

**关键听到**：**DOM 更新后才有正确高度** / **条数 / 最后一条长度 / 状态行三个信号** / **只监条数会漏流式追加**

**追问**：为什么 watch 的 source 写成 `() => [a, b, c]`？（答：getter 里把三个值都读一遍，Vue 就能同时追踪它们；返回的是新数组，任一元素变化都会触发回调。）

**常见错答**：「用 `scrollIntoView` 就不用算高度」——效果类似，但每 token 调一次的代价一样，`smooth` 动画在持续输出时还会被不断打断。

### VUE-24｜L1｜基础｜必答｜锚点 `frontend/src/components/MarkdownView.vue:53-69`

**题**：`withDefaults(defineProps<{...}>(), {...})` 和 `defineEmits<{...}>()` 各自解决什么？

**口语答案**：`defineProps` 用类型声明 props，`withDefaults` 给可选 props 补默认值——`files` 默认 `() => []`，数组默认值必须是工厂函数，否则所有实例共享同一个数组；`streaming` 默认 false。`defineEmits` 用调用签名声明事件名和参数类型，父组件写错事件名或参数类型，`vue-tsc` 直接报错。这两个都是编译宏，不需要 import，`vue-tsc` 能静态检查。

**关键听到**：**类型声明式 props** / **数组/对象默认值必须是工厂函数** / **defineEmits 用调用签名约束事件** / **两者都是编译宏**

**追问**：props 能不能在子组件里直接改？（答：不能，单向数据流。子组件只能 emit 让父级改，MarkdownView 点胶囊就是 `emit('preview', file)`，由 MessageList 写进 store。）

**常见错答**：「`defineProps` 里直接写默认值就行」——类型声明形式不支持，必须 `withDefaults`。

### VUE-25｜L1｜基础｜必答｜锚点 `frontend/src/services/request.ts:3-30`

**题**：`ApiResponse<T>` 和 `ApiError` 的类型设计各解决什么问题？

**口语答案**：`ApiResponse<T>` 把后端统一外壳 `{ code, message, data }` 建模成泛型，`data: T | null` 让「失败时没有数据」在类型上就成立。`ApiError extends Error` 把「网络连不上、HTTP 非 2xx、业务码非 0」三种失败统一成一种异常，`status` 和 `code` 都是可选的：连不上时两个都没有，HTTP 失败只有 status，业务失败只有 code，用「哪个字段有值」就能区分错误来源。调用方只需要 `catch (e)` 一次，再按字段决定提示。

**关键听到**：**泛型表达外壳** / **`T | null` 表达失败无数据** / **三种失败统一成一种异常** / **可选字段用来区分错误来源**

**追问**：为什么 `this.name = 'ApiError'` 要手动赋值？（答：继承内置 Error 时 `name` 默认还是 `'Error'`，手动赋值后日志和序列化里才能区分；`instanceof ApiError` 在现代运行时是可靠的。）

**常见错答**：「`data` 直接用 `T`，失败时返回 null 也行」——类型没表达出「可能为 null」，调用方每处都得猜。

### VUE-26｜L2｜读代码｜抽答｜锚点 `frontend/src/services/request.ts:40-66`

**题**：`request()` 三段失败处理分别对应什么情况？为什么 HTTP 非 2xx 时不再解析响应体？

**口语答案**：`fetch` 自己 reject 说明请求根本没发出去，后端没起或端口不通，此时既没有 status 也没有 code。`!response.ok` 是后端返回了 4xx/5xx，响应体不保证是统一外壳，可能是网关的 HTML 错误页，硬 `json()` 会再抛一次、把真实状态码盖掉。HTTP 成功后再看 `body.code`，非 0 是业务失败，带上后端 message 一起抛。三层分开，界面才能根据 `status` / `code` 是否有值给出不同提示。

**关键听到**：**fetch reject = 请求没发出去** / **非 2xx 响应体形状不可信** / **业务码非 0 是第三种失败** / **按字段区分错误来源**

**追问**：headers 为什么写成 `{ Accept: ..., ...(init.headers ?? {}) }` 而不是反过来？（答：调用方传入的 headers 优先级更高，放后面才能覆盖默认值；反过来调用方就改不了 Accept。）

**常见错答**：「`fetch` 遇到 4xx 会 reject，所以不用判 ok」——它只在网络层失败时 reject。

### VUE-27｜L2｜读代码｜必答｜锚点 `frontend/src/services/http.ts:13-31`、`:42-46`

**题**：`resolveApiBaseUrl` 的四级优先级为什么是这个顺序？`file://` 分支和非 `file://` 分支各在解决什么？

**口语答案**：最高优先级给构建期的 `VITE_API_BASE_URL`，用来连非本机后端；其次是 `window.desktop.apiPort`，因为主进程可能用 `APP_PORT` 覆盖端口，前端必须用真实端口；再次是 `file://` 打包态直连 `http://127.0.0.1:8000`（`frontend/src/config/index.ts:4` 的 `API_PORT`），因为打包后没有同源代理；浏览器开发态返回空串，走相对路径 `/api` 交给 vite 代理。这四级正好覆盖「构建期指定 / 桌面动态端口 / 桌面默认端口 / 浏览器代理」四种形态。

**关键听到**：**显式配置优先** / **Electron 注入端口必须用上** / **`file://` 下没有同源代理，只能绝对地址** / **浏览器态走相对路径 + vite 代理**

**追问**：为什么 `API_BASE_URL` 是模块加载时算一次，而不是每次 `buildUrl` 再算？（答：省重复计算；代价是 `window.desktop.apiPort` 必须在页面脚本执行前由 preload 注入好，之后再改它不会生效。）

**常见错答**：「Electron 里也能用相对路径」——`file://` 下相对路径指向本地文件系统，请求不到后端。

### VUE-28｜L1｜基础｜抽答｜锚点 `frontend/src/stores/chat.ts:1-13`

**题**：为什么把对话状态从页面组件抽到 Pinia store，而不是继续 props/emit？

**口语答案**：三栏布局下同一份「对话内容」被左栏（会话列表）、中栏（消息流）、右栏（token、工具轨迹）同时需要；留在页面组件里就得层层传递，而且切换路由组件销毁后状态全丢。放进 Pinia 后三处读同一份状态，页面组件只负责渲染和触发动作。store 自己也划了边界：不落库（消息由后端 SQLite 持久化）、不拼请求（SSE 协议在 `services/chat.ts`），只做当前视图的状态与动作。

**关键听到**：**三栏共享同一份状态** / **路由切换不能丢** / **store 只做视图状态** / **持久化与请求都在别处**

**追问**：store 里为什么还有 `loadSessions()` / `refreshUsage()` 这种「重新拉一遍」？（答：写操作后端已经落库，前端不自己维护派生数量；重拉一次最省事，也最不容易和后端不一致。）

**常见错答**：「Pinia 就是个大号全局 `ref`」——它的价值在约定和边界，多组件共享时可维护性完全不同。

### VUE-29｜L2｜读代码｜抽答｜锚点 `frontend/src/components/MarkdownView.vue:268-282`、`:372-378`

**题**：`<style scoped>` 里为什么给 `v-html` 生成的节点写样式都要 `:deep()`？

**口语答案**：scoped 的原理是给编译出的元素加 `data-v-xxx` 属性，选择器里也带上它；但 `v-html` 插进来的 DOM 是运行时生成的，没有这个属性，`.markdown-view p { }` 这类选择器匹配不到。`:deep(p)` 编译成 `.markdown-view[data-v-xxx] p`，只要求容器带标记、内部节点不带，就能穿透进去。所以在 `v-html` 场景下 `:deep` 不是可选优化，是让样式生效的必要条件。

**关键听到**：**scoped 靠属性选择器** / **v-html 节点没有 data-v 属性** / **`:deep` 编译后只约束容器**

**追问**：为什么高亮配色没有引 highlight.js 的 css 文件？（答：项目用主题 CSS 变量自己写了 `.hljs-*` 几类颜色，少两套主题样式文件，也能跟着深浅色主题一起换。）

**常见错答**：「把 scoped 去掉就能生效」——那会把样式污染到全局其它组件。

### VUE-30｜L3｜找坑｜加分｜锚点 `frontend/src/services/http.ts:48-64`、`frontend/src/services/request.ts:40`

**题**：`request.ts` 的统一外壳和 `http.ts` 的 `fetchRawJson` 为什么并存？这是好设计吗？

**口语答案**：历史原因：多数 `/api/*` 返回 `{ code, message, data }`，用 `request` / `get` / `post` 能统一处理业务码和错误；但 Agent 运行时那批接口（`/chat/*`、`/trace/*`、`/commands`）每次数据形状都不一样，硬套外壳反而多一层，所以有了 `fetchRawJson` 直接返回裸 JSON。并存的代价很明显：错误处理有两套（`ApiError` 和裸 `Error`），调用方要先判断接口属于哪一类，新人容易用错。注释里也如实写了「项目里有两类接口风格」，算是有意识地留了这个包袱。

**关键听到**：**统一外壳 vs 裸 JSON 是两类接口** / **Agent 接口形状不定，套壳多余** / **两套错误处理是真实成本** / **能说清这是历史包袱而不是优点**

**追问**：如果要收敛，你会怎么改？（答：让裸 JSON 也抛同一种 `ApiError`（只是不解析外壳），或者像 `services/chat.ts` 那样在服务层各自封装，页面组件不直接碰 fetch；一步到位换 axios 也行，但调用方签名要保持不变。）

**常见错答**：「统一都套外壳最规范」——流式和一次性响应体有些套不上，硬套会多一层且无收益。

### VUE-31｜L2｜读代码｜抽答｜锚点 `frontend/vitest.config.ts:20-41`

**题**：`vitest.config.ts` 里 `environment: 'jsdom'`、`include: ['tests/**/*.spec.ts']`、`globals: false` 为什么这么设？

**口语答案**：`jsdom` 是必须的：组件要 `mount`、DOMPurify 要在真实 DOM 上做净化，纯 Node 环境跑不了。`include` 只认 `tests/` 下的 `*.spec.ts`，避免把 `src/` 里同名文件误当测试跑。`globals: false` 不注入全局 `describe/it/expect`，每个文件显式 import——多一行，换来「这个符号从哪来」一眼可见，和项目要求每条 import 说明用途是同向的。另外 `plugins: [vue()]` 和别名 `@` 必须与 `vite.config.ts` 一致，否则测的不是同一份编译产物。

**关键听到**：**jsdom 是 mount 与 DOMPurify 的前提** / **include 限定测试目录** / **globals: false 显式 import** / **配置必须与 vite 对齐**

**追问**：为什么测试配置不写进 `vite.config.ts`？（答：vite 管开发服务器和打包，测试还多出环境、setup、文件范围、覆盖率，混在一起读的人分不清哪条配置给谁用。）

**常见错答**：「设个覆盖率阈值越高越安全」——一挂阈值，随便改一行页面就整体红，挡板变成噪音。

### VUE-32｜L3｜找坑｜抽答｜锚点 `doc/29-前端测试基建.md:199-215`

**题**：写 composable 和组件测试时，`effectScope()`、stub 掉 `van-*`、不依赖 `wrapper.vm` 这三条各在防什么？

**口语答案**：`useFileFilter`、`useDebouncedRef` 内部用 `onScopeDispose` 注册清理，必须在活跃的 effect scope 里调用才会注册；裸调用会告警，定时器也不会被清掉，用例之间互相污染。`van-*` 是 `main.ts` 里全局注册的，测试环境不存在，不 stub 会得到「Failed to resolve component」甚至挂载失败；要触发事件时还得用渲染函数写替身，因为项目用的是运行时版 Vue，内联 template 编译不了。`<script setup>` 内部状态默认不对外暴露，断言要从渲染结果、`emitted()`、被 mock 的函数调用去看，否则重构一下组件内部测试就全红，但行为没变。

**关键听到**：**composable 要有活跃 effect scope** / **Vant 是全局注册，测试里必须 stub** / **运行时版 Vue 不能编译内联 template** / **断言行为而不是内部状态**

**追问**：假定时器为什么必须成对使用？（答：`vi.useFakeTimers()` 之后不 `useRealTimers()`，同文件后续用例里所有时间相关逻辑都会失灵，表现为「莫名其妙不触发」。）

**常见错答**：「`mount` 没报错就算通过」——组件测试要断言渲染结果或交互结果，挂载成功不等于行为正确。

### VUE-33｜L2｜设计｜加分｜锚点 `doc/29-前端测试基建.md:162-183`

**题**：总行覆盖率只有 13.41%，为什么说「这是起点不是目标」？

**口语答案**：策略是先测「改错了不报错、只会安静出错」的地方：请求封装（四种调用方式加流式解析）、防抖/过滤/切片这些纯逻辑、Markdown 渲染链的 XSS、文件胶囊的交互分支。这几块单文件覆盖率都在 95% 以上，意义是「该测的都测了」。总覆盖被大量 `views/`、`stores/` 拉低是刻意的非目标——页面组件依赖 store 和接口，要整体 mock 才能测，属于增量工作。所以不设 thresholds，避免用总数字挡住合理改动。

**关键听到**：**优先测「安静出错」的地方** / **单文件 95%+ 才有意义** / **页面组件是刻意的非目标** / **不设阈值避免误伤**

**追问**：那 `views/` 以后怎么补？（答：用 `vi.mock` 把 store 和接口整体替换掉，断言「给定状态渲染出什么、点了触发什么」，而不是去碰组件内部实现细节。）

**常见错答**：「总覆盖率低就是测试没写对」——先看分母是谁，页面和纯逻辑的测试成本差一个量级。

### VUE-34｜L2｜读代码｜抽答｜锚点 `doc/29-前端测试基建.md:85-101`

**题**：`tests/setup.ts` 为什么必须补 `TextDecoder`、`matchMedia`、`ResizeObserver` 这些？不补会怎样？

**口语答案**：jsdom 只实现了 DOM 规范的一部分，缺的 API 不会明确报错，而是让被测代码在某一刻抛 `TypeError`，排查成本极高。没有 `TextDecoder`，`stream()` 里 `new TextDecoder()` 直接崩；没有 `matchMedia`，Vant 组件挂载时 `is not a function`；没有 `ResizeObserver`，`new ResizeObserver is not a constructor`；没有 `scrollIntoView`，Popover 定位报错。所以一次性补齐，并且「已存在则不覆盖」，避免盖掉真实实现。

**关键听到**：**jsdom 只实现了一部分 DOM 规范** / **缺 API 报的是 TypeError，不是明确提示** / **一次性补齐 + 已存在不覆盖** / **同时写 globalThis 与 window**

**追问**：为什么补的 API 要同时写到 `globalThis` 和 `window`？（答：jsdom 下两者不是同一个对象，只写一个会出现「测试里能看到、组件里看不到」的诡异现象。）

**常见错答**：「缺什么就在那个用例里临时补」——漏一个用例就红一次，应该在 setup 里统一兜住。

### VUE-35｜L2｜找坑｜加分｜锚点 `frontend/src/composables/useFileFilter.ts:20-32`、`:84-100`

**题**：`assertFilteredUnmutated` 加 `import.meta.env.DEV ? ... : null` 这套开发期断言，生产环境会发生什么？

**口语答案**：`import.meta.env.DEV` 在构建时被静态替换成字面量 `false`，`filteredSnapshotPaths` 的 `map` 和断言调用会整体被 DCE（dead code elimination）删掉，所以生产运行零成本。它防的是「有人把 sort 改回原地」这类回归——这种错不会抛异常，只会让列表顺序悄悄变错。断言只在 DEV 生效也意味着测试环境里它是真在跑的（vitest 下 `DEV` 为 true），只是正常情况走不到 `throw` 分支。

**关键听到**：**DEV 是构建期静态替换** / **死代码消除后生产零成本** / **防的是「安静出错」而不是崩溃** / **测试环境里断言是生效的**

**追问**：为什么不干脆在生产也留着断言？（答：每次排序都多一次 O(n) 的 `map` 加 `every`，长列表滚动排序时是实打实的开销；而且它防的是开发期改错，线上数据不会因此变对。）

**常见错答**：「`import.meta.env` 是运行时读环境变量」——它是构建期替换，浏览器里没有进程环境可读。

### VUE-36｜L2｜读代码｜必答｜锚点 `electron/src/main/backend.ts:70-90`

**题**：`waitForHealth` 为什么用绝对截止时间、500ms 轮询，还要判 `body.code === 0`？用 HEAD 不行吗？

**口语答案**：绝对 deadline 是为了不让每次循环重置等待时长，总等待时间才可控；500ms 间隔是「起来得快就早返回、起得慢也不打满 CPU」的折中。只看 `response.ok` 不够：进程可能已经在监听端口、但初始化还没完成，只有业务码 0 才代表真正就绪，否则会把半启动状态当成功。用 GET 而不是 HEAD，是因为 Spring MVC 和 uvicorn 对 HEAD 的处理不一致，显式 GET 最稳；每次探测带 `AbortSignal.timeout(1500)`，防止单次请求卡死。

**关键听到**：**绝对截止时间** / **轮询间隔权衡** / **业务码 0 才算就绪** / **HEAD 跨框架不可靠** / **单次探测也要超时**

**追问**：探测超时会怎样？（答：返回 false，`startBackend` 只打 warn 不抛错，窗口照样建，由前端页面提示「无法连接后端」——「能开窗」和「后端可用」是解耦的两件事。）

**常见错答**：「探测一次不通就算启动失败」——JVM 启动要几秒到十几秒，必须轮询。

### VUE-37｜L2｜读代码｜抽答｜锚点 `electron/src/main/backend.ts:300-350`

**题**：`startBackend` 为什么第一步先探活 800ms 而不是直接 spawn？后面的四路分支怎么选？

**口语答案**：开发态 `dev.mjs` 可能已经起过后端，Electron 再起一个就端口冲突；先探活，能复用就返回 `owned: false`，退出时也不会去杀别人的进程。四路分支由 `target`（java/python）和 `isPackaged` 组合：打包态 Java 跑 jar，找不到 jar 就报错提示先 `build:backend:java`；开发态即使有 jar 也优先 Maven，保证改代码立即生效；Python 打包态跑 exe，开发态跑源码。`owned` 这个标志把「进程是谁拉起的」和「退出时要不要负责关掉」绑在一起，避免误杀。

**关键听到**：**先探活复用，避免端口冲突** / **`owned` 决定退出时是否清理** / **打包态与开发态是两套启动方式** / **开发态优先 Maven 保证改完即生效**

**追问**：`child` 为 null 时为什么直接返回 `owned: false`？（答：没创建出进程就没有可管理的生命周期，不再等健康检查超时，让前端尽快提示连接失败。）

**常见错答**：「打包态和开发态用同一条命令」——jar/exe 与 mvn/uvicorn 完全是两套。

### VUE-38｜L3｜设计｜抽答｜锚点 `electron/src/main/backend.ts:270-289`

**题**：`guardEnv` 注入 `APP_PARENT_GUARD=1`、再每 5 秒往子进程 stdin 写一个字节，这套「保活 + 自毁」怎么工作？

**口语答案**：Electron 主进程被强杀（任务管理器、崩溃）时，子进程不会自动跟着死，会留下占端口的僵尸后端。所以启动时注入 `APP_PARENT_GUARD`，后端读这个标记后监听 stdin：主进程活着就每 5 秒写一个字节；主进程一死，管道关闭，后端读到 EOF 就自己退出。心跳定时器要 `unref()`，否则它会让 Node 事件循环一直有活干、影响退出。每次写之前判 `stdin` 是否存在且未 `destroyed`，防止对端已关闭时 `write` 抛 EPIPE。

**关键听到**：**父进程被强杀时子进程不会自动死** / **用 stdin 管道感知父进程存活** / **`unref()` 不拖住事件循环** / **写前判空防 EPIPE**

**追问**：为什么用「写字节」而不是 HTTP 心跳？（答：这条通道不占端口、不依赖后端 HTTP 已经就绪，后端只要能读 stdin 就行；启动阶段 HTTP 还没监听时，HTTP 心跳反而会误判。）

**常见错答**：「`will-quit` 里 kill 就够了」——它只在正常退出时触发，崩溃和强杀都不走这条路径。

### VUE-39｜L2｜找坑｜加分｜锚点 `electron/src/main/backend.ts:386-409`

**题**：Windows 下为什么用 `taskkill /pid /f /t`，POSIX 下只用 `child.kill('SIGTERM')`？`ownedBackend` 在防什么？

**口语答案**：Windows 下 spawn 出来的可能只是个壳，Maven → Java 是父子进程，只杀父进程的话真正监听端口的 Java 还活着，端口一直被占，下次启动就探活到旧进程。`/t` 连子进程树一起结束、`/f` 强制，才能清干净。POSIX 下信号和进程组语义健全，`SIGTERM` 让子进程有机会自己收尾，更温和也更正确。`ownedBackend` 保证只有「自己拉起的」才杀：复用外部服务时直接 return，不误杀开发者手起的后端。

**关键听到**：**Windows 只杀直接子进程留孙子进程** / **`/t` 杀进程树、`/f` 强制** / **POSIX 用 SIGTERM 更温和** / **`owned` 防误杀别人的进程**

**追问**：`/f` 强制结束有什么代价？（答：跳过优雅退出，后端可能来不及 flush 日志、关数据库连接；但 Windows 上本来就没有可靠的 SIGTERM，退出流程里只能强制。）

**常见错答**：「`child.kill()` 在 Windows 上也能杀干净」——它只作用于直接子进程。

### VUE-40｜L2｜读代码｜抽答｜锚点 `electron/src/main/index.ts:108-132`、`:138-201`

**题**：`bootstrap` 为什么「先起或复用后端、再建窗」？退出清理又为什么放在 `will-quit`？

**口语答案**：窗口一建出来，渲染进程就会立刻请求 `/api/health` 之类接口，后端没就绪的话首屏全是「无法连接」；所以顺序是单实例锁 → `startBackend`（内部含健康检查等待）→ `createWindow`。自动更新放在建窗之后，因为更新对话框需要父窗口，状态广播也需要窗口已经存在。退出时 `window-all-closed` 负责关应用（macOS 除外），`will-quit` 调 `stopBackend` 关掉本次拉起的后端——两步分工明确：一个管窗口生命周期，一个管进程生命周期。

**关键听到**：**后端就绪先于建窗，否则首屏全是连接失败** / **单实例锁避免端口冲突** / **自动更新依赖窗口存在** / **`will-quit` 才是真正的退出时机**

**追问**：为什么只开三个 `ipcMain.handle`（选文件夹、定位文件、打开路径），不给一个通用执行通道？（答：渲染进程要渲染 LLM 输出，是不可信内容；通道越少攻击面越小，这三个都改不了系统状态、也不执行任意命令，没有通用 `exec` 通道。）

**常见错答**：「`app.quit()` 会等所有子进程退出」——不会，Node 的子进程生命周期要自己管。

---

## 复核提示

- 行号采集自当前 HEAD；`frontend/src/components/MarkdownView.vue`、`frontend/src/stores/chat.ts` 改动频繁，改动后请以函数名为准重新定位。
- VUE-02 的「末尾未 flush 的半个字符会丢」是对现有代码的推断（循环后没有补 `decoder.decode()`），建议人工确认是否为有意取舍。
- VUE-35 的生产裁剪依赖构建器对 `import.meta.env.DEV` 分支做 DCE，建议对照实际打包产物确认一次。
