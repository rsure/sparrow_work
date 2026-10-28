/**
 * 对话接口层：对应后端 app/controllers/chat_controller.py 的 /api/chat/* 全部端点。
 *
 * 覆盖四块能力：
 *   1. 流式对话：chat_stream（普通提问 / `\doc` 知识库检索，靠 mode 区分）
 *   2. 人工确认：chat_resume（AI 要动文件/删索引时，后端暂停，前端弹窗后把决定交回去）
 *   3. 终止：stop_chat（页面上点「终止」，后端主动掐断正在跑的流）
 *   4. 对话记录：list_chat_sessions / get_chat_messages / delete_chat_session（读 SQLite 里的历史）
 *
 * 事件协议见后端 GET /api/chat/events。
 */
import { sse } from './request' // SSE 流式请求封装：按事件帧读取并逐帧回调，对应后端 text/event-stream
import { buildUrl } from './http' // 拼后端完整 URL：清会话、终止、历史查询这些接口不走统一外壳，需要自己发 fetch

/** 一轮对话消息（多轮上下文中的一条，仅前端渲染用；后端上下文由 session_id 维护） */
export interface ChatMessage {
  /** 说话人：user=用户提问，assistant=模型回答 */
  role: 'user' | 'assistant'
  /** 该条消息的完整文本内容（非流式，是已经定稿的整段话） */
  content: string
}

/**
 * 对话模式：
 *   agent = 交给带工具的 Agent 自行决定怎么查；
 *   doc   = message 是一条 `\doc` 知识库指令，由后端解析并直接执行
 *           （检索问答 / 列出文档 / 删除 / 导入 / 帮助）
 */
export type ChatMode = 'agent' | 'doc'

/** 发起对话请求体，对应后端 POST /chat/stream 的 ChatRequest */
export interface ChatRequest {
  /** 本次要提问的内容；mode=doc 时这里就是用户敲的完整 `\doc ...` 指令（含前缀） */
  message: string
  /** 会话 ID；首轮传 null/省略，由后端生成并随 done 事件返回，后续轮带上它即可延续上下文 */
  session_id?: string | null
  /** 对话模式，缺省 agent。doc 对应页面上的 `\doc` 指令 */
  mode?: ChatMode
  /** 仅 mode=doc 的检索问答生效：检索返回的片段条数上限（后端限制 1~20，缺省 5） */
  doc_top_k?: number
  /** LangGraph 递归步数上限（模型、工具各算一步），后端限制 1~50，缺省 25 */
  max_iterations?: number
  /** 为 true 时后端写详细日志并在 error 事件里附带异常类型；默认 false */
  debug?: boolean
}

/** thinking 事件：思考中/阶段提示 */
export interface ThinkingEvent {
  /** 阶段标识：analyzing=正在理解问题，session_ready=会话就绪，responding=正在组织回答，searching=正在检索知识库 */
  stage: string
  /** 该阶段的模拟耗时（秒），仅 analyzing/responding 阶段有 */
  delay?: number
  /** 会话 id，仅 session_ready 阶段有 */
  session_id?: string
  /** 当前会话的历史消息条数，仅 session_ready 阶段有 */
  history_len?: number
  /** 该阶段现成的展示文案（如"正在《需求方案.md》中检索：有哪些风险"）；有它就直接显示，不用查 stage 表 */
  text?: string
}

/** tool_start 事件：工具开始执行 */
export interface ToolStartEvent {
  /** 工具名，如 list_dir / read_file / rag_search / write_file */
  name: string
  /** 工具入参（结构由各工具自定义） */
  input?: unknown
}

/** tool_end 事件：工具执行结束（已按 EXT-5 做过输出治理） */
export interface ToolEndEvent {
  /** 工具名，与对应的 tool_start 同名 */
  name: string
  /** 工具返回的文本，后端约定 "OK: ..." 为成功、"FAIL: ..." 为失败；超长时已截断 */
  output: string
  /** 截断前的原始字符数；未截断时等于 output 的长度 */
  total_chars: number
  /** 是否发生了截断（EXT-5）；true 时 UI 可给「查看完整输出」入口 */
  truncated: boolean
  /** 续读标记（如 tool-out-3f2a…）；未截断或未落盘时为 null */
  continuation_ref: string | null
}

/**
 * stopped 事件：用户点了「终止」（POST /chat/stop），后端主动掐断了本轮。
 * 与 done 的区别只是"这轮没跑完"，前端一样要拿 answer 校正气泡内容并收掉光标。
 */
export interface StoppedEvent {
  /** 本轮使用的会话 id */
  session_id: string
  /** 被终止前已经生成出来的那部分回答（可能为空串） */
  answer: string
  /** 结束原因，目前恒为 'user_stop'（表示是用户点终止造成的） */
  reason: string
}

/** 子任务（plan 事件里的元素） */
export interface SubTaskInfo {
  /** 序号，从 1 开始 */
  id: number
  /** 一句话标题 */
  title: string
  /** 给执行用的目标说明 */
  description: string
  /** 预计要写入的文件（冲突检测的依据，也用于界面提示） */
  files: string[]
  /** 依赖的子任务 id */
  depends_on: number[]
}

/** 子任务状态：pending=待执行 / running=执行中 / success=完成 / failed=失败 / verify_failed=校验未通过 */
export type SubTaskStatus = 'pending' | 'running' | 'success' | 'failed' | 'verify_failed'

/** plan 事件：复杂任务拆分结果（TASK） */
export interface PlanEvent {
  /** 判定理由（为什么这么拆） */
  reason: string
  /** 子任务列表 */
  subtasks: SubTaskInfo[]
}

/** TASK Phase 2：计划被重新规划时的通知（失败后模型给出新列表） */
export interface PlanUpdateEvent {
  /** 为什么要重排（模型给的一句话，可能为空） */
  reason: string
  /** 新的子任务列表；`pending=true` 时是"待确认"的草稿 */
  subtasks: SubTaskInfo[]
  /** true=还在等用户确认；false=已确认并生效 */
  pending: boolean
}

/** task_start 事件：某个子任务开始执行 */
export interface TaskStartEvent {
  /** 子任务 id */
  id: number
  /** 子任务标题 */
  title: string
  /** 第几个（1 起） */
  index: number
  /** 总共几个 */
  total: number
}

/** task_end 事件：某个子任务结束 */
export interface TaskEndEvent {
  /** 子任务 id */
  id: number
  /** 子任务标题 */
  title: string
  /** 结束状态 */
  status: SubTaskStatus
  /** 结果摘要 */
  summary: string
}

/** done 事件里的子任务结果（比 plan 多了 status/summary，用于历史回放） */
export interface SubTaskResult extends SubTaskInfo {
  /** 最终状态 */
  status: SubTaskStatus
  /** 结果摘要 */
  summary: string
}

/** done 事件：本轮正常结束，携带最终答案与统计（OPS-6 契约：字段一次定全） */
export interface DoneEvent {
  /** 本轮使用的会话 id，前端必须存下来用于下一轮 */
  session_id: string
  /** 完整回答文本，可用于校正流式拼接的结果 */
  answer: string
  /** 后端处理总耗时（秒） */
  elapsed: number
  /** 本轮的工具调用记录 */
  tool_calls: Array<{ name: string; input?: unknown; output?: string }>
  /** 结束时会话的历史消息条数 */
  history_len: number
  /** 本轮回答里提到的文件清单（由后端解析路径标记后生成），可能为空数组 */
  files?: ChatFileRef[]
  /** TASK：任务模式下各子任务的结果；单 agent 路径为 null */
  subtasks?: SubTaskResult[] | null
  /** 本轮真实 token 用量（来自 provider 的 usage_metadata，不是估算）；取不到时为 null */
  usage?: TokenUsage | null
  /** 本轮用户插话被接受的次数（ARCH-6；M2 占位恒为 0） */
  steer_count?: number
  /** 本轮使用的模型标识，形如 "deepseek/deepseek-chat"；历史轮次据此回放当时所用模型 */
  model?: string
}

/** 单轮 token 用量（口径：API 返回的真实值） */
export interface TokenUsage {
  /** 输入（提示词）token 数 */
  input_tokens: number
  /** 输出（生成）token 数 */
  output_tokens: number
  /** 合计 token 数 */
  total_tokens: number
  /** 本轮折算费用（元）；未知单价时为 0，缺省表示后端没算 */
  cost?: number
}

/**
 * steer_accepted 事件：执行中插话已被后端接收（ARCH-6 协议）。
 *
 * 注意：当前后端**不再通过 SSE 发这个事件**——插话是另一次 HTTP 请求，
 * 受理结果直接放在 `POST /chat/{session_id}/steer` 的响应体（见 SteerQueuedResult）。
 * 这个类型与回调保留下来，是为了协议演进时前端不用改结构。
 */
export interface SteerAcceptedEvent {
  /** 所属会话 id */
  session_id: string
  /** 本次插话的唯一 id（后续 steer_injected 用它配对） */
  steer_id: string
  /** 插话内容原文 */
  content: string
  /** 是否已入队（受后端开关与排队上限影响） */
  queued?: boolean
}

/** steer_injected 事件：插话内容真正进入模型上下文（ARCH-6 协议） */
export interface SteerInjectedEvent {
  /** 所属会话 id */
  session_id: string
  /** 对应的插话 id */
  steer_id: string
}

/** budget_exceeded 事件：单任务超出预算，需用户选择继续/停止（UX-9） */
export interface BudgetExceededEvent {
  /** 所属会话 id */
  session_id: string
  /** 中断 id：选择继续/停止后，用它调 /chat/resume 恢复执行 */
  interrupt_id: string
  /** 超限维度：tokens=token 数 / cost=费用 / duration=时长 */
  dimension: 'tokens' | 'cost' | 'duration'
  /** 当前累计值（单位随 dimension 变化） */
  current: number
  /** 阈值 */
  limit: number
  /** 后端拼好的一句说明（已含单位），前端可直接展示 */
  message?: string
}

/**
 * confirm_required 事件：Agent 准备执行有风险的操作（覆盖文件、修改文件、删除知识库记录），
 * 后端已暂停在该工具调用处（LangGraph interrupt），等待用户同意或拒绝。
 * 发出该事件后本次 SSE 流会直接结束（不会再发 done），前端需调用 chat_resume 让后端继续。
 */
export interface ConfirmRequiredEvent {
  /** 所属会话 id，chat_resume 时原样回传 */
  session_id: string
  /** 本次中断的唯一 id（LangGraph Interrupt.id），chat_resume 时原样回传，后端据此定位要恢复的那一处 */
  interrupt_id: string
  /** 触发确认的工具名，如 write_file / edit_file / delete_index */
  tool: string
  /** 该工具本次调用的入参，用于在弹窗里展示「要改哪个文件、改成什么」 */
  args?: Record<string, unknown>
  /** 弹窗标题，如「覆盖文件」；后端未提供时前端按工具名兜底 */
  title?: string
  /** 弹窗正文：后端整理好的影响范围说明（如将删除的文档列表）；未提供时前端用 args 拼 */
  message?: string
  /** 是否提供「记住本工作区授权」勾选（仅 permission.mode=workspace 且已配置工作区时为 true） */
  can_remember?: boolean
}

/** 恢复执行请求体，对应后端 POST /chat/resume：把用户对 confirm_required 的决定告诉后端 */
export interface ChatResumeRequest {
  /** 会话 id，取自 confirm_required 事件 */
  session_id: string
  /** 中断 id，取自 confirm_required 事件 */
  interrupt_id: string
  /** 用户决定：true=同意执行该操作，false=拒绝（工具会返回 FAIL，模型据此回复用户） */
  approved: boolean
  /**
   * 是否「记住本工作区授权」（仅 workspace 模式有效）。
   * 勾选后后端把 (工作区, 工具) 写入 approvals，同工作区同类操作以后不再询问。
   */
  remember?: boolean
  /** LangGraph 递归步数上限，含义同 ChatRequest.max_iterations；缺省由后端决定 */
  max_iterations?: number
}

/**
 * 对话事件回调集合：按需实现其中几个即可，未实现的事件会被忽略。
 * 事件协议见后端 GET /chat/events 与 chat_controller.py 模块 docstring。
 */
export interface ChatStreamHandlers {
  /** 思考中/阶段提示：可用于显示「正在理解你的问题…」这类过渡文案 */
  onThinking?: (data: ThinkingEvent) => void
  /** LLM 逐字输出：把 text 直接拼到气泡末尾 */
  onToken?: (text: string) => void
  /** 工具开始执行：可显示「正在扫描文件…」 */
  onToolStart?: (data: ToolStartEvent) => void
  /** 工具执行结束：可展示工具结果 */
  onToolEnd?: (data: ToolEndEvent) => void
  /** 本轮正常结束：务必在这里保存 session_id 供下一轮使用 */
  onDone?: (data: DoneEvent) => void
  /** 后端暂停等待用户确认：记下事件，等流结束后弹窗询问，再调用 chat_resume 继续 */
  onConfirmRequired?: (data: ConfirmRequiredEvent) => void
  /** 本轮被用户终止：用 answer 校正气泡内容，并提示「已终止」 */
  onStopped?: (data: StoppedEvent) => void
  /** 执行中插话已被接受（当前后端把回执放在 POST 响应体，SSE 不会发这个事件） */
  onSteerAccepted?: (data: SteerAcceptedEvent) => void
  /** 插话已注入模型上下文（在某个工具结束之后发出；可用于把"排队中"改成"已送达"） */
  onSteerInjected?: (data: SteerInjectedEvent) => void
  /** 单任务超出预算（UX-9）：记下来，等流结束后弹「继续 / 停止」，再用 chat_resume 恢复 */
  onBudgetExceeded?: (data: BudgetExceededEvent) => void
  /** TASK：收到任务拆分结果（只有复杂任务才发；简单任务不会触发） */
  onPlan?: (data: PlanEvent) => void
  /** TASK Phase 2：计划被重新规划（失败后模型给出新列表，可能还在等确认） */
  onPlanUpdate?: (data: PlanUpdateEvent) => void
  /** TASK：某个子任务开始 */
  onTaskStart?: (data: TaskStartEvent) => void
  /** TASK：某个子任务结束 */
  onTaskEnd?: (data: TaskEndEvent) => void
  /** 后端上报的业务异常（HTTP 已是 200，错误通过 error 事件下发） */
  onError?: (message: string) => void
}

/**
 * 把一个 SSE 事件帧分发到对应回调；chat_stream 与 chat_resume 的事件协议完全相同，共用这一份。
 *
 * @param handlers 各类事件的回调（都可选）
 * @param event SSE 事件名
 * @param data 该事件的 JSON 数据
 */
function dispatchChatEvent(
  handlers: ChatStreamHandlers,
  event: string,
  data: Record<string, unknown>,
): void {
  switch (event) {
    case 'thinking':
      handlers.onThinking?.(data as unknown as ThinkingEvent)
      break
    case 'token':
      handlers.onToken?.(String(data.text ?? ''))
      break
    case 'tool_start':
      handlers.onToolStart?.(data as unknown as ToolStartEvent)
      break
    case 'tool_end':
      handlers.onToolEnd?.(data as unknown as ToolEndEvent)
      break
    case 'confirm_required':
      handlers.onConfirmRequired?.(data as unknown as ConfirmRequiredEvent)
      break
    case 'stopped':
      handlers.onStopped?.(data as unknown as StoppedEvent)
      break
    case 'steer_accepted':
      handlers.onSteerAccepted?.(data as unknown as SteerAcceptedEvent)
      break
    case 'steer_injected':
      handlers.onSteerInjected?.(data as unknown as SteerInjectedEvent)
      break
    case 'budget_exceeded':
      handlers.onBudgetExceeded?.(data as unknown as BudgetExceededEvent)
      break
    case 'plan':
      handlers.onPlan?.(data as unknown as PlanEvent)
      break
    case 'plan_update':
      // TASK Phase 2：失败后模型给出新计划（pending=true 时界面要等用户确认）
      handlers.onPlanUpdate?.(data as unknown as PlanUpdateEvent)
      break
    case 'task_start':
      handlers.onTaskStart?.(data as unknown as TaskStartEvent)
      break
    case 'task_end':
      handlers.onTaskEnd?.(data as unknown as TaskEndEvent)
      break
    case 'done':
      handlers.onDone?.(data as unknown as DoneEvent)
      break
    case 'error':
      handlers.onError?.(String(data.message ?? '未知错误'))
      break
    default:
      // 后端新增事件时前端不报错，便于双端分别升级
      break
  }
}

/**
 * 以 POST + JSON 请求体发起一个对话类 SSE 请求，并把事件分发给 handlers。
 *
 * @param path 接口路径：/chat/stream 或 /chat/resume
 * @param body 请求体（会被 JSON 序列化）
 * @param handlers 各类事件的回调
 * @param init 额外 fetch 配置，常用于传 signal 以便中途取消
 */
function postChatSse(
  path: string,
  body: ChatRequest | ChatResumeRequest,
  handlers: ChatStreamHandlers,
  init: RequestInit,
): Promise<void> {
  return sse(path, (event, data) => dispatchChatEvent(handlers, event, data), {
    ...init,
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
    body: JSON.stringify(body),
  })
}

/**
 * 调用后端 Agent 对话流式接口（SSE）：把事件帧分发到对应回调。
 *
 * 与旧 NDJSON 版的差别：
 * - 传输格式从「每行一个 JSON」换成 SSE 事件帧，事件名区分 token / 工具 / 收尾；
 * - 多轮上下文不再由前端传 history，而是后端按 session_id 在内存里维护，
 *   所以首轮拿到 done.session_id 后要存下来，后续轮回传。
 *
 * 注意：若收到 confirm_required，本次流会在没有 done 的情况下结束，需要调用 chat_resume 继续。
 *
 * @param req 提问内容 + 可选会话 id 与模型参数
 * @param handlers 各类事件的回调（都可选）
 * @param init 额外 fetch 配置，常用于传 signal 以便中途取消
 */
export function chat_stream(
  req: ChatRequest,
  handlers: ChatStreamHandlers,
  init: RequestInit = {},
): Promise<void> {
  return postChatSse('/chat/stream', req, handlers, init)
}

/**
 * 把用户对 confirm_required 的决定（同意 / 拒绝）提交给后端，后端从暂停处继续执行，
 * 返回的 SSE 事件与 chat_stream 完全相同（可能再次出现 confirm_required，需要循环处理）。
 *
 * @param req 会话 id + 中断 id + 用户决定
 * @param handlers 各类事件的回调（都可选）
 * @param init 额外 fetch 配置，常用于传 signal 以便中途取消
 */
export function chat_resume(
  req: ChatResumeRequest,
  handlers: ChatStreamHandlers,
  init: RequestInit = {},
): Promise<void> {
  return postChatSse('/chat/resume', req, handlers, init)
}

/** 查询会话状态的返回体，对应 GET /chat/sessions/{id} */
export interface SessionInfo {
  /** 会话是否还在后端内存里（超过 1 小时空闲会被清理） */
  exists: boolean
  /** 会话 id */
  session_id: string
  /** 历史消息条数，仅 exists=true 时有 */
  messages?: number
  /** 创建时间（Unix 秒），仅 exists=true 时有 */
  created_at?: number
  /** 最近活跃时间（Unix 秒），仅 exists=true 时有 */
  last_active?: number
  /** 当前是否有正在执行的对话流（页面据此判断「终止」是否还有意义） */
  running?: boolean
}

/**
 * 直接发一个返回裸 JSON 的对话接口请求（不走 { code, message, data } 统一外壳）。
 *
 * /chat/* 下的辅助端点（清上下文、终止、历史查询）后端都直接返回裸 JSON，
 * 所以这里自己发 fetch，而不用 services/request 里的 get/del。
 *
 * @param path 接口路径（不含 /api 前缀），如 '/chat/sessions'
 * @param init 额外的 fetch 配置，method 由调用方指定
 * @returns 后端返回的裸 JSON
 */
async function chatJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(buildUrl(path), init)
  if (!res.ok) throw new Error(`请求失败：HTTP ${res.status}`)
  return (await res.json()) as T
}

/**
 * 清空一个会话的后端上下文：用于「新建对话」，让下一轮从零上下文开始。
 *
 * 注意：这个接口**不会**删除 SQLite 里的对话记录——用户只是要开一段新对话，
 * 之前聊过的内容还应该在「最近会话」列表里看得到。永久删除记录用 delete_chat_session。
 *
 * @param sessionId 要清空上下文的会话 id
 */
export async function clear_chat_session(sessionId: string): Promise<void> {
  await chatJson(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/**
 * 终止某个会话正在执行的对话：后端会真的中断 Agent 的搜索/生成，
 * 那条流随即推一条 stopped 事件（带已生成的部分回答）后结束。
 *
 * @param sessionId 会话 id，取自 thinking(session_ready) 或 done 事件
 * @returns stopped=true 表示确实叫停了一条流；false 表示该会话当前没有在跑的流（例如刚好自己跑完了）
 */
export function stop_chat(sessionId: string): Promise<{ stopped: boolean; session_id: string }> {
  return chatJson('/chat/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
}

/**
 * 执行中插话的受理结果，对应 POST /chat/{session_id}/steer 的响应体（ARCH-6）。
 *
 * 为什么不用 SSE 回执：插话是用户在执行期间**另外发起的一次请求**，
 * 走普通 JSON 最直接——前端拿到 200 就能立刻把气泡标成"排队中"，
 * 不必等那条主流的下一帧。
 */
export interface SteerQueuedResult {
  /** 所属会话 id */
  session_id: string
  /** 本次插话的唯一 id（后续 steer_injected 事件用它配对） */
  steer_id: string
  /** 后端存下的正文（首尾空白已被去掉） */
  content: string
  /** 是否已入队：成功受理恒为 true（失败会以异常抛出，不会出现 false） */
  queued: boolean
  /** 这个会话当前一共几条插话在排队（含刚提交的这条） */
  pending: number
}

/** 取消工具的结果，对应 POST /chat/{session_id}/tool-cancel 的响应体 */
export interface ToolCancelResult {
  /** 所属会话 id */
  session_id: string
  /** 是否登记成功（工具已经开始跑时后端返回 409 并以异常抛出） */
  cancelled: boolean
  /** 被取消的工具名；登记时没指定工具，后端回 "(下一个工具)" */
  tool: string
}

/**
 * POST 一个返回裸 JSON 的对话辅助端点，并把后端的 detail 文案变成异常信息。
 *
 * 为什么不复用 chatJson：那里遇到 4xx 只能拼出「请求失败：HTTP 400」，
 * 而插话/取消这两个接口的失败原因（开关关了、没有活跃流、工具已在执行）
 * 都是要**直接给用户看**的，必须把 detail 透出来。
 *
 * @param path 接口路径（不含 /api 前缀）
 * @param body 请求体
 * @returns 后端返回的裸 JSON
 */
async function postChatAction<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  // 失败时后端也返回 JSON（{detail}）；解析失败就退回状态码，避免把解析异常盖在真实原因上
  const payload = (await res.json().catch(() => null)) as (T & { detail?: string }) | null
  if (!res.ok) throw new Error(payload?.detail || `请求失败：HTTP ${res.status}`)
  return payload as T
}

/**
 * 执行中插话（ARCH-6 第 1 档）：把一句追加指令送进正在跑的那一轮。
 *
 * 后端不会立刻打断当前工具，而是在**下一个工具结束时**把这句话拼进工具结果，
 * 模型下一步就能看到；如果这一轮在工具边界之前就结束了，插话会被丢弃（不会串到下一轮）。
 *
 * @param sessionId 会话 id；必须与正在跑的那条流一致，否则后端 409
 * @param content 插话正文（后端上限 2000 字，最多排队 5 条）
 * @returns 受理结果（含排队条数），失败抛 Error（message 是后端给的中文原因）
 */
export function steer_chat(sessionId: string, content: string): Promise<SteerQueuedResult> {
  return postChatAction(`/chat/${encodeURIComponent(sessionId)}/steer`, { content })
}

/**
 * 取消一个「还没开始执行」的工具（ARCH-6 第 2 档）。
 *
 * 已经开始的同步工具无法安全中断，后端会返回 409 并提示改用「终止」——
 * 这与界面上"能点"不是一回事：前端要如实把这条提示弹给用户。
 *
 * @param sessionId 会话 id
 * @param tool 要取消的工具名；传空串表示"下一个要跑的工具，不管是什么"
 * @returns 登记结果
 */
export function cancel_tool(sessionId: string, tool = ''): Promise<ToolCancelResult> {
  return postChatAction(`/chat/${encodeURIComponent(sessionId)}/tool-cancel`, { tool })
}

/** 「最近会话」列表里的一项，对应后端 GET /chat/sessions 返回的 sessions 元素 */
export interface ChatSessionInfo {
  /** 会话 id：点开旧会话时把它当作 session_id 回传给 /chat/stream，就能接着聊 */
  session_id: string
  /** 会话标题：取该会话第一条用户提问的前 30 字 */
  title: string
  /** 该会话最近一次用的模式：agent=工具对话，doc=`\doc` 知识库指令 */
  mode: ChatMode
  /** 已落库的消息条数（用户 + 助手各算一条） */
  message_count: number
  /** 创建时间（UTC 的 ISO 字符串，展示前需转本地时区） */
  created_at: string | null
  /** 最近一次写入消息的时间（UTC 的 ISO 字符串，列表按它倒序） */
  updated_at: string | null
  /** 最后一条消息的一行预览（超过 60 字会被截断） */
  preview: string
  /** 是否置顶（UX-4）：置顶的会话永远排在列表最前，且不受"最近活跃"影响 */
  pinned: boolean
  /** 是否已归档（UX-4）：归档的会话只在「归档」视图里出现，默认列表看不到 */
  archived: boolean
}

/** 落库的一条历史消息，对应后端 GET /chat/history/sessions/{id} 返回的 messages 元素 */
export interface StoredChatMessage {
  /** 消息主键（自增），同一会话内越大越新 */
  id: number
  /** 说话人：user / assistant */
  role: 'user' | 'assistant'
  /** 消息正文 */
  content: string
  /** 这条消息属于哪种对话模式 */
  mode: ChatMode
  /** 助手调用过的工具轨迹（结构由各工具自定义）；用户提问恒为 null */
  tool_calls: Array<{ name: string; input?: unknown; output?: string; confirm?: string }> | null
  /** 这一轮是怎么结束的：done=答完，stopped=用户终止，error=出错，pending_confirm=停在等确认 */
  finish_reason: 'done' | 'stopped' | 'error' | 'pending_confirm'
  /** 本轮耗时（秒）；用户提问恒为 null */
  elapsed: number | null
  /** 入库时间（UTC 的 ISO 字符串） */
  created_at: string | null
}

/**
 * 拉取会话列表（数据来自后端 SQLite，重启后端也不会丢）。
 *
 * 这里不传 limit：条数上限与默认值只由后端 `PageLimits` / `limits.py` 决定，
 * 前端硬编码 20 只会制造「请求 20 条、后端默认其实是别的数」这类对不上的情况。
 *
 * @param query 搜索关键词（命中标题或消息正文）；空表示不过滤
 * @param archived 取哪一箱：false=正常列表（默认），true=归档箱
 * @returns 按「置顶优先 + 最近活跃时间倒序」排好的会话列表
 */
export async function list_chat_sessions(
  query = '',
  archived = false,
): Promise<ChatSessionInfo[]> {
  // 关键词要编码：用户可能输入空格、#、& 等会破坏 query string 的字符
  const keyword = query.trim() ? `q=${encodeURIComponent(query.trim())}` : ''
  const box = archived ? 'archived=true' : ''
  // 只拼真正的参数；都没传时连问号都不带，避免发出 `/chat/sessions?` 这种空查询
  const search = [keyword, box].filter(Boolean).join('&')
  const data = await chatJson<{ sessions: ChatSessionInfo[] }>(
    `/chat/sessions${search ? `?${search}` : ''}`,
  )
  return data.sessions
}

/** 会话可改的三个字段：都省略表示"不改这一项" */
export interface ChatSessionPatch {
  /** 新标题；省略或空串表示不改名 */
  title?: string
  /** 是否置顶；省略表示保持原状 */
  pinned?: boolean
  /** 是否归档；省略表示保持原状 */
  archived?: boolean
}

/** 改会话标记后的返回体，对应 PATCH /chat/history/sessions/{id} */
export interface ChatSessionPatchResult {
  /** 标题是否真的被改了（只改标记时为 false） */
  renamed: boolean
  /** 会话 id */
  session_id: string
  /** 落库后的标题 */
  title: string
  /** 落库后的置顶状态 */
  pinned: boolean
  /** 落库后的归档状态 */
  archived: boolean
}

/**
 * 改会话的标题与两个标记（UX-4）。
 *
 * 为什么统一成一个接口：置顶/归档/改名都是"改 chat_session 这一行"，
 * 分三个接口只会让前端多写两套错误处理，后端多写两个几乎一样的 handler。
 *
 * @param sessionId 会话 id
 * @param patch 要改的字段（省略的字段保持原值）
 * @returns 后端落库后的完整标记
 */
export async function update_chat_session(
  sessionId: string,
  patch: ChatSessionPatch,
): Promise<ChatSessionPatchResult> {
  const body: ChatSessionPatch = {}
  // 逐字段挑出"有定义的"，避免把 undefined 发过去被后端当成显式传入
  if (patch.title !== undefined) body.title = patch.title
  if (patch.pinned !== undefined) body.pinned = patch.pinned
  if (patch.archived !== undefined) body.archived = patch.archived
  return chatJson<ChatSessionPatchResult>(
    `/chat/history/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

/**
 * 重命名会话（UX-4）。
 *
 * @param sessionId 会话 id
 * @param title 新标题
 * @returns 后端落库后的标题
 */
export async function rename_chat_session(sessionId: string, title: string): Promise<string> {
  const data = await update_chat_session(sessionId, { title })
  return data.title
}

/** 导出格式：md=给人读的 Markdown，json=给程序再加工 */
export type ChatExportFormat = 'md' | 'json'

/** 导出结果，对应 GET /chat/history/sessions/{id}/export */
export interface ExportedSession {
  /** 会话 id */
  session_id: string
  /** 实际使用的格式 */
  format: ChatExportFormat
  /** 后端建议的文件名（已去掉非法字符，带扩展名） */
  filename: string
  /** 文件全文（md 文本或 json 字符串） */
  content: string
  /** 导出时该会话的消息条数 */
  message_count: number
}

/**
 * 导出一个会话（UX-4）。
 *
 * 后端只把内容当 JSON 文本返回，**不落任何临时文件**：写到哪里、叫什么名字
 * 由前端（浏览器下载 / Electron 保存框）决定，Python 侧不必关心磁盘权限。
 *
 * @param sessionId 会话 id
 * @param format md=Markdown，json=结构化 JSON
 */
export function export_chat_session(
  sessionId: string,
  format: ChatExportFormat = 'md',
): Promise<ExportedSession> {
  return chatJson<ExportedSession>(
    `/chat/history/sessions/${encodeURIComponent(sessionId)}/export?format=${format}`,
  )
}

/** 会话级用量汇总，对应 GET /chat/history/sessions/{id}/usage */
export interface SessionUsage {
  /** 会话 id */
  session_id: string
  /** 有用量记录的轮次数 */
  turns: number
  /** 累计输入 token */
  input_tokens: number
  /** 累计输出 token */
  output_tokens: number
  /** 累计总 token */
  total_tokens: number
  /** 折算费用（元） */
  cost: number
  /** 币种（当前恒为 CNY） */
  currency: string
  /** 按模型拆分：模型名 / 轮次 / token / 费用 */
  by_model: Array<{ model: string; turns: number; tokens: number; cost: number }>
}

/**
 * 拉取某个会话的累计 token 与费用（UX-5 右栏「本会话」）。
 *
 * @param sessionId 会话 id
 */
export function fetch_session_usage(sessionId: string): Promise<SessionUsage> {
  return chatJson(`/chat/history/sessions/${encodeURIComponent(sessionId)}/usage`)
}

/**
 * 取某个旧会话的完整消息，供页面回填气泡。
 *
 * 这里不传 limit：窗口大小（默认 200 条，也就是最近 200 条）只由后端决定。
 * 响应里还带 `has_more`（更早的还有没有），目前页面不消费它——
 * 等做「加载更早」时从这里接，不要在前端再猜一个数字。
 *
 * @param sessionId 会话 id
 * @returns 按时间升序的消息列表
 */
export async function get_chat_messages(sessionId: string): Promise<StoredChatMessage[]> {
  const data = await chatJson<{ session_id: string; messages: StoredChatMessage[]; has_more: boolean }>(
    `/chat/history/sessions/${encodeURIComponent(sessionId)}`,
  )
  return data.messages
}

/**
 * 永久删除一个会话的记录（连同它的全部消息），用于「最近会话」列表里的删除按钮。
 *
 * @param sessionId 要删除的会话 id
 * @returns deleted=true 表示确实删掉了一个会话；false 表示这个 id 本来就不存在
 */
export function delete_chat_session(sessionId: string): Promise<{ deleted: boolean; session_id: string }> {
  return chatJson(`/chat/history/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/** 续读接口的返回体，对应 GET /chat/tool-output/{ref}（EXT-5） */
export interface ToolOutputPayload {
  /** 续读标记 */
  ref: string
  /** 完整内容是否还在（被清理过时为 false） */
  found: boolean
  /** 完整文本；found=false 时为空串 */
  content: string
  /** 完整文本的字符数 */
  chars: number
}

/**
 * 按续读标记取回被截断工具输出的完整内容。
 * 用于工具轨迹里的「查看完整输出」：模型只看前 N 个字符，人想看全量时走这里。
 *
 * @param ref tool_end 事件里的 continuation_ref
 */
export function fetchToolOutput(ref: string): Promise<ToolOutputPayload> {
  return chatJson(`/chat/tool-output/${encodeURIComponent(ref)}`)
}

/** done 事件里附带的一个文件条目，对应后端 file_browse_service.describe() 的返回 */
export interface ChatFileRef {
  /** 文件绝对路径，预览与打开文件夹都用它 */
  path: string
  /** 文件名（含扩展名），用于在片段上显示短标签 */
  name: string
  /** 文件类别：text=可文本预览 / image=图片 / rich=pdf,docx / binary=其它二进制 / missing=不存在 */
  kind: 'text' | 'image' | 'rich' | 'binary' | 'missing'
  /** 能否在左侧面板内预览；false 时只提供"打开所在文件夹 / 用系统程序打开" */
  previewable: boolean
  /** 文件字节数，0 表示不存在或取不到 */
  size: number
  /** 人类可读的大小文案，如 "12.3 KB"；不存在时为空串 */
  size_text: string
  /** 不能预览的原因（可直接展示给用户）；能预览时为空串 */
  reason: string
  /** MIME 类型，如 image/png；后端识别不出时为空串 */
  mime: string
}
