/**
 * stores/chat.ts —— 对话的全局状态（M2：从 scannHistory.vue 的巨石里抽出来）。
 *
 * 为什么要抽成 store：
 *   三栏布局下，「对话内容」同时被三个地方需要 ——
 *     左栏（会话列表 / 新建对话）、中栏（消息流 + 输入）、右栏（本轮 token、工具轨迹）。
 *   如果状态还留在页面组件里，就只能靠 props/emit 层层传递，且切换路由就全丢。
 *   放进 Pinia 后：页面组件只负责渲染，三处共享同一份数据。
 *
 * 状态边界：
 *   - **不落库**：消息本身由后端 SQLite 持久化（见 chat_history_service），本 store 只是当前视图。
 *   - **不拼请求**：SSE 请求与事件协议在 services/chat.ts，这里只消费回调。
 */

// Pinia：定义全局 store
import { defineStore } from 'pinia'
// Vant 反馈：确认弹窗（AI 要动文件/删索引时）、操作结果轻提示
import { showConfirmDialog, showToast } from 'vant'
// 文档列表接口：`\doc` 指令的文件名候选需要它（只取名字，不展示文档列表本身）
import { list_documents, type DocumentInfo } from '@/services/scan'
// 对话接口与事件类型：SSE 流、恢复执行、终止、会话历史
import {
  chat_resume,
  chat_stream,
  clear_chat_session,
  delete_chat_session,
  export_chat_session,
  fetch_session_usage,
  get_chat_messages,
  list_chat_sessions,
  rename_chat_session,
  stop_chat,
  steer_chat,
  cancel_tool,
  update_chat_session,
  type BudgetExceededEvent,
  type ChatExportFormat,
  type ChatFileRef,
  type ChatRequest,
  type ChatSessionInfo,
  type ChatStreamHandlers,
  type ConfirmRequiredEvent,
  type PlanEvent,
  type PlanUpdateEvent,
  type SessionUsage,
  type SteerInjectedEvent,
  type StoredChatMessage,
  type SubTaskStatus,
  type TaskEndEvent,
  type TaskStartEvent,
  type TokenUsage,
  type ToolEndEvent,
} from '@/services/chat'
// 斜杠命令：`/` 面板的清单来源、输入解析、来源标签，以及"输入里已敲了哪条命令"的纯解析（UX-8）
import {
  command_source_label,
  filter_commands,
  list_commands,
  parse_slash_input,
  type CommandInfo,
} from '@/services/command'
// 工作区文件搜索：`@` 提及的候选来源（只搜当前工作区，后端按文件名排好序）
import { search_workspace_files, type MentionFile } from '@/services/file'
// 把导出内容存成文件：浏览器/Electron 里都走 Blob + <a download>，不依赖主进程保存框
import { download_text_file } from '@/utils/download'
// 供应商清单：`/model <名字>` 要判断用户写的是不是"供应商/模型"两段式，
// 并查该供应商的预置模型名（清单外的名字要顺手登记成自定义模型）
import { fetchProviders, type LlmProvider } from '@/services/settings'
// 设置 store：切模型必须写回它（顶栏 chip 与设置页读的是同一份数据，才谈得上三处同步）
import { useSettingsStore } from '@/stores/settings'

// =========================================================================== //
// 1. 类型
// =========================================================================== //
/** 一次工具调用在界面上的展示模型 */
export interface UIToolCall {
  /** 工具名，如 read_file */
  name: string
  /** 工具返回文本；undefined 表示还在执行中（界面显示「执行中」） */
  output?: string
  /**
   * 仅「需要用户确认」的记录有：pending=等待中，approved=已同意，rejected=已拒绝。
   * 普通工具调用没有这个字段。
   */
  confirm?: 'pending' | 'approved' | 'rejected'
  /** 截断前的原始字符数（EXT-5）；普通执行中记录为 undefined */
  totalChars?: number
  /** 输出是否被截断（EXT-5）：true 时界面给「查看完整输出」入口 */
  truncated?: boolean
  /** 续读标记（EXT-5）；未截断时为 null */
  continuationRef?: string | null
}

/** 对话气泡的界面模型 */
export interface UIMessage {
  /** 说话人：user=用户，assistant=模型 */
  role: 'user' | 'assistant'
  /** 气泡正文；流式过程中被逐片追加 */
  content: string
  /** 是否仍在流式输出（true 时末尾显示闪烁光标） */
  streaming?: boolean
  /** 本轮 Agent 调用过的工具，按发生顺序排列 */
  tools?: UIToolCall[]
  /** 本轮是否被用户「终止」结束 */
  stopped?: boolean
  /** 本轮回答里提到的文件（用于把路径渲染成胶囊） */
  files?: ChatFileRef[]
  /** 本轮真实 token 用量（来自 done.usage，非估算） */
  usage?: TokenUsage | null
  /** 本轮使用的模型（provider/model，来自 done.model） */
  model?: string
  /** 本轮耗时（秒，来自 done.elapsed） */
  elapsed?: number
}

/**
 * 一次"停下来问用户"的请求，两种来源共用同一个弹层：
 *   confirm —— 有风险操作要授权（可带「记住本工作区」勾选）
 *   budget  —— 单任务超出预算，问继续/停止
 */
/** 右栏 Todo 面板里的一条子任务（plan 的结果 + 运行期状态） */
export interface TaskTodo {
  /** 子任务序号 */
  id: number
  /** 一句话标题 */
  title: string
  /** 目标说明 */
  description: string
  /** 预计写入的文件 */
  files: string[]
  /** 当前状态 */
  status: SubTaskStatus
  /** 结束后的结果摘要 */
  summary: string
}

export type PendingAsk =
  | { kind: 'confirm'; request: ConfirmRequiredEvent }
  | { kind: 'budget'; request: BudgetExceededEvent }

/** `\doc` 指令的前端粗解析结果（仅用于提示与候选，指令语义由后端决定） */
interface DocInput {
  /** 这条输入是不是 `\doc` 指令 */
  isDoc: boolean
  /** 该提示的文件名片段；null 表示不该提示候选 */
  pending: string | null
}

// =========================================================================== //
// 2. 常量
// =========================================================================== //
/** thinking 事件的 stage -> 展示文案；未收录的 stage 显示空串 */
const STAGE_TEXT: Record<string, string> = {
  analyzing: '正在理解你的问题…',
  session_ready: '',
  responding: '正在组织回答…',
  searching: '正在检索知识库…',
}

/** 需要确认的工具 -> 弹窗标题兜底文案（后端没带 title 时使用） */
export const CONFIRM_TITLE: Record<string, string> = {
  write_file: '确认覆盖文件',
  edit_file: '确认修改文件',
  run_command: '确认执行命令',
  delete_index: '确认从知识库删除',
  index_path: '扫描路径到知识库',
  file_ops: '确认文件操作',
  // TASK Phase 2：子任务失败后模型想改计划，这是"要不要换计划"的确认（不是文件写入）
  replan: '确认新的执行计划',
}

/** 工具入参名 -> 弹窗里展示的中文标签 */
export const CONFIRM_ARG_LABEL: Record<string, string> = {
  path: '路径',
  content: '写入内容',
  overwrite: '覆盖已有文件',
  old_text: '原内容',
  new_text: '改为',
  replace_all: '替换全部匹配',
  sources: '将删除的文档',
  command: '命令',
  cwd: '工作目录',
  timeout: '超时(秒)',
  op: '操作类型',
  plan: '将执行的操作',
  permanent: '彻底删除',
}

/** 弹窗里每个参数值最多展示的字符数，超出用省略号 */
const CONFIRM_ARG_MAX_CHARS = 200

/** `\doc` 指令前缀：反斜杠 + doc，后面必须跟空白或结束（避免把 `\docs` 也认成指令） */
const DOC_PREFIX_RE = /^\\doc(\s|$)/i

/** 带参数的 `\doc` 子命令：只有这两个后面跟的是文件名/路径，需要给候选 */
const DOC_ARG_CMD_RE = /^(?:-d|--delete|-i|--import|-a|--add)\s+(.*)$/i

/** 输入框上方最多同时显示几个文档名候选 */
const DOC_SUGGEST_MAX = 8

/** `/` 命令面板最多同时显示几条命令（再多用户也看不过来） */
const COMMAND_SUGGEST_MAX = 8

/** `@` 文件候选一次最多取几条（与后端 GET /file/search 的默认 limit 一致） */
const MENTION_MAX_RESULTS = 20

/** 请求「终止」后最多再等多少毫秒就强行断开前端连接 */
const STOP_FALLBACK_MS = 3000

/** 左栏会话列表最多列多少个 */
export const SESSION_LIST_LIMIT = 20

// =========================================================================== //
// 3. 工具函数
// =========================================================================== //
/**
 * 把待确认工具的入参整理成弹窗正文：每个参数一行「标签：值」，过长的值截断。
 *
 * @param args 工具入参
 * @returns 多行文本（Vant 弹窗正文保留换行）
 */
export function describeConfirmArgs(args?: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return 'AI 准备执行一个需要你确认的操作。'
  return Object.entries(args)
    .map(([key, value]) => {
      const text = typeof value === 'string' ? value : JSON.stringify(value)
      const short =
        text.length > CONFIRM_ARG_MAX_CHARS ? `${text.slice(0, CONFIRM_ARG_MAX_CHARS)}…` : text
      return `${CONFIRM_ARG_LABEL[key] ?? key}：${short}`
    })
    .join('\n')
}

/** 弹层提交结果的回调：由 store 的 ask() 设置，resolveAsk() 调用一次后清空 */
let askResolver: ((answer: { approved: boolean; remember: boolean }) => void) | null = null

/**
 * 把后端落库的一条历史消息转成界面气泡模型。
 *
 * @param row 后端返回的历史消息
 * @returns 可直接塞进 messages 的界面模型
 */
function toUIMessage(row: StoredChatMessage): UIMessage {
  return {
    role: row.role,
    content: row.content,
    tools: (row.tool_calls ?? []).map((tool) => ({
      name: tool.name,
      output: tool.output,
      confirm: tool.confirm as UIToolCall['confirm'],
    })),
    // 只有"被用户终止"才在气泡上留标记；error/pending_confirm 的正文本身就说明了问题
    stopped: row.finish_reason === 'stopped',
  }
}

/**
 * 从后往前找第一条满足条件的工具记录下标（找不到返回 -1）。
 *
 * 为什么不用 `[...tools].reverse().find()`：那样拿到的是原始对象，
 * 改它不会触发 Vue 更新；改成返回下标，调用方用 `tools[i] = {...}` 替换元素才会触发。
 *
 * @param tools 工具记录数组
 * @param predicate 匹配条件
 * @returns 下标；-1 表示没有匹配项
 */
function findLastToolIndex(
  tools: UIToolCall[],
  predicate: (item: UIToolCall) => boolean,
): number {
  for (let i = tools.length - 1; i >= 0; i -= 1) {
    if (predicate(tools[i])) return i
  }
  return -1
}

/**
 * 只做 UI 用的粗解析：判断是不是 `\doc` 指令、以及当前该不该给文档名候选。
 *
 * 真正的指令语义由后端解析（见 chat_controller._parse_doc_command），
 * 这里判错最多让候选显示得不对，不会让指令执行跑偏。
 *
 * @param text 输入框当前内容
 * @param names 已导入文档名列表
 * @returns isDoc=是否指令；pending=该提示的文件名片段（null 表示不提示）
 */
function parseDocInput(text: string, names: string[]): DocInput {
  const trimmed = text.trim()
  if (!DOC_PREFIX_RE.test(trimmed)) return { isDoc: false, pending: null }
  const rest = trimmed.replace(DOC_PREFIX_RE, '').trim()
  if (!rest) return { isDoc: true, pending: '' }

  const argMatch = DOC_ARG_CMD_RE.exec(rest)
  let body: string
  if (argMatch) body = (argMatch[1] ?? '').trim()
  else if (rest.startsWith('-')) return { isDoc: true, pending: null }
  else body = rest
  if (!body) return { isDoc: true, pending: '' }

  const low = body.toLowerCase()
  for (const name of names) {
    const key = name.toLowerCase()
    // 整个剩余部分就是文件名，或「文件名 + 空格 + 问题」：文档已选定，不用再提示
    if (low === key || low.startsWith(`${key} `)) return { isDoc: true, pending: null }
  }
  // 打了空格却没匹配上任何文件名，说明在写问题：也不提示
  if (body.includes(' ')) return { isDoc: true, pending: null }
  return { isDoc: true, pending: body }
}

// =========================================================================== //
// 4. Store
// =========================================================================== //
export const useChatStore = defineStore('chat', {
  state: () => ({
    /** 当前会话的全部消息（内存态；历史记录在后端 SQLite） */
    messages: [] as UIMessage[],
    /** 当前阶段提示文案（思考中 / 正在执行工具）；空串表示不显示 */
    statusText: '',
    /** 输入框内容（放进 store 是为了让 `\doc` 候选与输入栏共享同一份文本） */
    input: '',
    /** 是否正在等待/接收回答：true 时发送按钮变「终止」 */
    sending: false,
    /** 本次发送是否由用户点了「终止」结束的 */
    stopRequested: false,
    /** 是否正在提交一条执行中插话（防止连点导致重复入队） */
    steering: false,
    /** 本会话已受理但还没注入模型的插话条数（>0 时输入栏提示"排队中"） */
    steerQueued: 0,
    /** 后端会话 id；首轮为 null，拿到事件后立刻存下来 */
    sessionId: null as string | null,
    /** 本轮请求的中断句柄：终止后若后端不响应，用它兜底断开 */
    abortController: null as AbortController | null,
    /** 已导入文档列表（只用文件名做候选） */
    documents: [] as DocumentInfo[],
    /** 最近会话列表（不含归档；置顶的排在前面，排序由后端 SQL 保证） */
    sessions: [] as ChatSessionInfo[],
    /** 归档箱里的会话（UX-4）：只在切到「归档」视图时才拉，启动时不多查一次库 */
    archivedSessions: [] as ChatSessionInfo[],
    /** 左栏当前看的是哪一箱：false=正常列表，true=归档箱 */
    showArchived: false,
    /** 会话列表是否正在加载 */
    loadingSessions: false,
    /** 归档箱是否正在加载（与 loadingSessions 分开，两箱可以各显各的 loading） */
    loadingArchived: false,
    /** 斜杠命令清单（UX-8，`/` 面板的数据源）；后端不可用时为空数组 */
    commands: [] as CommandInfo[],
    /** 「模型」选择面板是否展开（`/model` 命令或输入栏的模型胶囊触发） */
    modelPickerOpen: false,
    /** 是否正在读取某个旧会话的消息 */
    loadingHistory: false,
    /** 右栏预览的文件；null 表示右栏没有预览内容 */
    previewFile: null as ChatFileRef | null,
    /** 当前会话标题（从会话列表里取；新建会话时为空） */
    title: '',
    /** 会话搜索关键词（打到后端，命中标题或消息正文） */
    searchQuery: '',
    /** 当前会话的累计用量与费用（右栏「本会话」）；null 表示还没拉 */
    usage: null as SessionUsage | null,
    /** 正在等待用户回答的询问；null 表示没有 */
    pendingAsk: null as PendingAsk | null,
    /** 「记住本工作区授权」勾选状态（仅 confirm 且 can_remember 时有意义） */
    rememberWorkspace: false,
    /** TASK：当前这轮的任务计划（Todo 面板的数据源）；空数组表示不是任务模式 */
    taskPlan: [] as TaskTodo[],
    /** TASK：拆分理由（面板上的一行说明） */
    taskReason: '',
  }),

  getters: {
    /** 输入框里是否已经是一条 `\doc` 指令 */
    isDocInput(state): boolean {
      return DOC_PREFIX_RE.test(state.input.trim())
    },
    /**
     * 输入框上方的文档名候选：`\doc ` / `\doc -d ` 后面还没写完文件名时给出。
     * 把已敲的半截当子串筛，所以 `\doc 需求` 会列出名字里带"需求"的文档。
     */
    docSuggestions(state): string[] {
      const names = state.documents.map((doc) => doc.name)
      const { isDoc, pending } = parseDocInput(state.input, names)
      if (!isDoc || pending === null) return []
      const prefix = pending.toLowerCase()
      return names
        .filter((name) => !prefix || name.toLowerCase().includes(prefix))
        .slice(0, DOC_SUGGEST_MAX)
    },
    /** 输入区下方的能力提示文案 */
    inputHint(): string {
      return this.isDocInput
        ? '\\doc -l 列出文档 · \\doc -d 文件名 删除 · \\doc -i 路径 导入 · \\doc -h 看全部用法'
        : '直接提问由 AI 自行查资料 · / 唤起命令 · @ 引用工作区文件 · \\doc 使用知识库指令'
    },
    /** 最近一条助手消息（右栏用它展示本轮 token / 工具轨迹） */
    lastAssistant(state): UIMessage | null {
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        if (state.messages[i].role === 'assistant') return state.messages[i]
      }
      return null
    },
    /** 会话 id 的短形式（右栏展示用，完整 id 太长） */
    shortSessionId(state): string {
      return state.sessionId ? state.sessionId.slice(0, 8) : '未开始'
    },
    /** 当前询问若是「操作确认」，返回它（模板据此渲染工具名/参数） */
    confirmAsk(state): ConfirmRequiredEvent | null {
      return state.pendingAsk?.kind === 'confirm' ? state.pendingAsk.request : null
    },
    /** 当前询问若是「预算超限」，返回它 */
    budgetAsk(state): BudgetExceededEvent | null {
      return state.pendingAsk?.kind === 'budget' ? state.pendingAsk.request : null
    },
    /** 是否处于任务模式（有拆分结果才显示 Todo 面板） */
    hasTaskPlan(state): boolean {
      return state.taskPlan.length > 0
    },
    /** 任务进度：已完成数 / 总数（右栏标题用） */
    taskProgress(state): { done: number; total: number } {
      const done = state.taskPlan.filter(
        (item) => item.status === 'success' || item.status === 'failed' || item.status === 'verify_failed',
      ).length
      return { done, total: state.taskPlan.length }
    },

    // --------------------------------------------------------------------- //
    // UX 收尾：会话分箱、`/` 命令、`@` 提及、模型胶囊
    // --------------------------------------------------------------------- //

    /** 置顶的会话（左栏单独一栏，不参与"最近"列表的滚动） */
    pinnedSessions(state): ChatSessionInfo[] {
      return state.sessions.filter((sess) => sess.pinned)
    },
    /** 没置顶的会话（左栏「最近」栏；后端已按 updated_at 倒序） */
    recentSessions(state): ChatSessionInfo[] {
      return state.sessions.filter((sess) => !sess.pinned)
    },
    /** 左栏当前要渲染的那一箱：归档视图显示归档箱，否则显示正常列表 */
    visibleSessions(state): ChatSessionInfo[] {
      return state.showArchived ? state.archivedSessions : state.sessions
    },
    /** 归档箱里有没有东西（决定「归档」入口是否显示数量角标） */
    archivedCount(state): number {
      return state.archivedSessions.length
    },
    /** 输入框里是否以 `/` 开头（正在敲命令） */
    isCommandInput(state): boolean {
      return state.input.trimStart().startsWith('/')
    },
    /**
     * `/` 面板要列的命令：只在"命令名还没敲完"（`/exp` 这种，还没打空格）时给。
     * 一旦打了空格进入参数区（`/doc -l`），面板就该让位给正文输入。
     */
    commandSuggestions(state): CommandInfo[] {
      const { name, args } = parse_slash_input(state.input)
      // 没有 `/` 前缀，或已经进入参数区 → 不弹面板
      if (!name || args) return []
      return filter_commands(state.commands, name).slice(0, COMMAND_SUGGEST_MAX)
    },
    /**
     * 输入框末尾那个还没写完的 `@关键词`（没有则 null）。
     * 返回空串表示"刚敲下 @"，此时列出工作区的头几个文件让用户先看到东西。
     */
    mentionQuery(state): string | null {
      const matched = /(^|\s)@([^\s@]*)$/.exec(state.input)
      return matched ? matched[2] : null
    },
    /**
     * 输入栏模型胶囊的文案。
     * 优先用"这轮回答实际用的模型"（后端 done 事件回的 model），
     * 还没跑过问句时显示"当前模型"，都不显示内部 id 以外的猜测。
     */
    currentModelLabel(): string {
      const used = this.lastAssistant?.model
      return used && used.trim() ? used : '当前模型'
    },
  },

  actions: {
    // --------------------------------------------------------------------- //
    // 数据加载
    // --------------------------------------------------------------------- //
    /**
     * 拉取已导入文档列表（只用于 `\doc` 候选）。
     * 失败时保留旧数据只做提示——它只是输入辅助，不该挡住正常聊天。
     */
    async loadDocuments(): Promise<void> {
      try {
        this.documents = await list_documents()
      } catch (error) {
        console.error('加载文档名失败:', error)
      }
    },

    /** 拉取「最近会话」列表；失败时保留旧数据并提示 */
    async loadSessions(): Promise<void> {
      this.loadingSessions = true
      try {
        this.sessions = await list_chat_sessions(SESSION_LIST_LIMIT, this.searchQuery)
      } catch (error) {
        console.error('加载会话记录失败:', error)
        showToast('加载会话记录失败')
      } finally {
        this.loadingSessions = false
      }
    },

    /**
     * 拉取「归档箱」列表（UX-4）。
     *
     * 归档箱平时不加载：绝大多数用户永远不看它，启动时多查一次库纯属浪费。
     * 失败时同样只提示、不清空旧数据。
     */
    async loadArchivedSessions(): Promise<void> {
      this.loadingArchived = true
      try {
        this.archivedSessions = await list_chat_sessions(SESSION_LIST_LIMIT, this.searchQuery, true)
      } catch (error) {
        console.error('加载归档会话失败:', error)
        showToast('加载归档会话失败')
      } finally {
        this.loadingArchived = false
      }
    },

    /**
     * 拉取斜杠命令清单（UX-8）。
     *
     * 拿不到时只把 commands 留空——`/` 面板不弹，但输入框仍然能把 `/doc` 当普通消息发出去，
     * 所以这个接口失败不该挡住聊天。
     */
    async loadCommands(): Promise<void> {
      try {
        this.commands = await list_commands()
      } catch (error) {
        console.error('加载命令清单失败:', error)
      }
    },

    /** 应用启动时拉一次：文档候选 + 会话列表 + 命令清单（三件事互不依赖，失败互不影响） */
    async bootstrap(): Promise<void> {
      await Promise.all([this.loadDocuments(), this.loadSessions(), this.loadCommands()])
    },

    // --------------------------------------------------------------------- //
    // 会话操作
    // --------------------------------------------------------------------- //
    /**
     * 打开一个历史会话：把消息从后端读回来，并把它设为当前会话。
     *
     * 之后继续提问会带上同一个 session_id；后端发现内存里没有现场时，
     * 会自动从 SQLite 的历史记录补种上下文，所以隔很久再回来聊也能接上。
     *
     * @param sid 要点开的会话 id
     */
    async openSession(sid: string): Promise<void> {
      if (this.sending || this.loadingHistory) return
      this.loadingHistory = true
      try {
        const rows = await get_chat_messages(sid)
        this.messages = rows.map(toUIMessage)
        this.sessionId = sid
        this.statusText = ''
        this.previewFile = null
        this.title = this.sessions.find((item) => item.session_id === sid)?.title ?? ''
        void this.refreshUsage()
      } catch (error) {
        console.error('读取会话消息失败:', error)
        showToast('读取会话消息失败')
      } finally {
        this.loadingHistory = false
      }
    },

    /**
     * 删除一条会话记录：先确认，再永久删除，最后同步本地列表。
     *
     * @param sess 要删除的会话
     */
    async removeSession(sess: ChatSessionInfo): Promise<void> {
      try {
        await showConfirmDialog({
          title: '删除会话',
          message: `确定删除「${sess.title}」及其全部对话内容吗？删除后无法恢复。`,
        })
      } catch {
        return // 用户取消
      }
      try {
        await delete_chat_session(sess.session_id)
        // 两箱都要删：一条被归档的会话同样可能在归档箱里显示着
        this.sessions = this.sessions.filter((item) => item.session_id !== sess.session_id)
        this.archivedSessions = this.archivedSessions.filter((item) => item.session_id !== sess.session_id)
        // 删的正好是当前会话：清空气泡，免得对着一个已经不存在的会话继续聊
        if (this.sessionId === sess.session_id) {
          this.messages = []
          this.sessionId = null
          this.title = ''
        }
        showToast('已删除')
      } catch (error) {
        console.error('删除会话失败:', error)
        showToast('删除会话失败')
      }
    },

    /**
     * 「新建对话」：清掉后端上下文与本地气泡，让下一轮从零上下文开始。
     * 只清上下文，**不删**历史记录。
     */
    async newConversation(): Promise<void> {
      if (this.sending) return
      const sid = this.sessionId
      this.messages = []
      this.statusText = ''
      this.sessionId = null
      this.title = ''
      this.previewFile = null
      this.input = ''
      this.usage = null
      this.taskPlan = []
      this.taskReason = ''
      if (!sid) return
      try {
        await clear_chat_session(sid)
      } catch (error) {
        // 后端会话 1 小时后本就会过期，清不掉不影响前端已经重置的新会话
        console.error('清空会话上下文失败:', error)
      }
      void this.loadSessions()
    },

    /**
     * 点文档候选：把输入框补成 `\doc 文件名 ` 或 `\doc -d 文件名 `。
     *
     * @param name 被点击的文档名
     */
    pickDoc(name: string): void {
      const trimmed = this.input.trim()
      const rest = trimmed.replace(DOC_PREFIX_RE, '').trim()
      const argMatch = DOC_ARG_CMD_RE.exec(rest)
      this.input = argMatch
        ? `\\doc ${argMatch[0].trim().split(/\s+/)[0]} ${name} `
        : `\\doc ${name} `
    },

    // --------------------------------------------------------------------- //
    // UX-4：置顶 / 归档 / 导出
    // --------------------------------------------------------------------- //
    /**
     * 把一次 PATCH 的结果写回两个列表缓存，免得为了一个布尔值重拉两箱数据。
     *
     * @param sessionId 被修改的会话 id
     * @param patch 后端返回的新字段（title 只在有值时覆盖，避免把标题刷成空串）
     */
    applySessionPatch(sessionId: string, patch: { title?: string; pinned?: boolean; archived?: boolean }): void {
      /** 对单个列表做"按下标替换"，保持 Vue 对每个条目的引用可追踪 */
      const apply = (list: ChatSessionInfo[]): ChatSessionInfo[] =>
        list.map((item) => (item.session_id === sessionId ? { ...item, ...patch } : item))
      this.sessions = apply(this.sessions)
      this.archivedSessions = apply(this.archivedSessions)
      // 改的正好是当前会话 → 页面头部标题跟着变
      if (this.sessionId === sessionId && patch.title) this.title = patch.title
    },

    /**
     * 置顶 / 取消置顶一条会话。
     *
     * 置顶会改变后端返回的顺序（SQL 里 `pinned DESC` 优先），
     * 所以改完必须重拉一次「最近会话」，不能只改本地那个布尔值。
     *
     * @param sess 目标会话
     * @param pinned true=置顶，false=取消置顶
     */
    async setSessionPinned(sess: ChatSessionInfo, pinned: boolean): Promise<void> {
      try {
        await update_chat_session(sess.session_id, { pinned })
        this.applySessionPatch(sess.session_id, { pinned })
        await this.loadSessions()
        showToast(pinned ? '已置顶' : '已取消置顶')
      } catch (error) {
        console.error('修改会话置顶失败:', error)
        showToast('修改会话置顶失败')
      }
    },

    /**
     * 归档 / 取消归档一条会话。
     *
     * 刻意不把当前正在聊的会话踢出页面：用户可能只是想把旧会话收起来，
     * 而不是想中断手上这轮对话。归档只影响它在左栏出现在哪一箱，
     * 消息本身一条都不删（取消归档后原样回来）。
     *
     * @param sess 目标会话
     * @param archived true=归档，false=取消归档
     */
    async setSessionArchived(sess: ChatSessionInfo, archived: boolean): Promise<void> {
      try {
        await update_chat_session(sess.session_id, { archived })
        this.applySessionPatch(sess.session_id, { archived })
        // 归档换箱：两箱都要重拉，否则刚归档的会话会同时出现在两处
        await Promise.all([this.loadSessions(), this.loadArchivedSessions()])
        showToast(archived ? '已归档' : '已取消归档')
      } catch (error) {
        console.error('修改会话归档状态失败:', error)
        showToast('修改会话归档状态失败')
      }
    },

    /**
     * 切换左栏显示「最近」还是「归档箱」。
     *
     * 第一次切到归档箱时才真正去拉数据（见 loadArchivedSessions 的注释）。
     *
     * @param show true=看归档箱，false=看正常列表
     */
    async switchArchivedView(show: boolean): Promise<void> {
      this.showArchived = show
      if (show && this.archivedSessions.length === 0) await this.loadArchivedSessions()
      // 归档箱也要能按关键词搜：切回来时把正常列表按当前关键词刷新一次
      if (!show) await this.loadSessions()
    },

    /**
     * 把一条会话导出成文件并触发下载（UX-4）。
     *
     * 后端返回的是文件全文而不是二进制流：导出只是把已有记录拼成文本，
     * 没必要让后端落临时文件；前端用 Blob 存盘，浏览器和 Electron 渲染进程都能用。
     * 提示里带上文件名——浏览器默认只说"已下载"，用户不知道存成了什么。
     *
     * @param sessionId 要导出的会话 id
     * @param format 导出格式：md（人读）或 json（机器读）
     */
    async exportSession(sessionId: string, format: ChatExportFormat = 'md'): Promise<void> {
      try {
        const data = await export_chat_session(sessionId, format)
        download_text_file(
          data.filename,
          data.content,
          format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8',
        )
        showToast(`已导出 ${data.filename}`)
      } catch (error) {
        console.error('导出会话失败:', error)
        showToast('导出会话失败')
      }
    },

    /**
     * 导出**当前**会话（`/export` 命令用）。
     *
     * @param format 导出格式：md 或 json
     */
    async exportCurrent(format: ChatExportFormat = 'md'): Promise<void> {
      const sid = this.sessionId
      // 还没有会话 id 说明这轮对话还没落库，导出只会拿到 404
      if (!sid) {
        showToast('当前还没有会话可以导出')
        return
      }
      await this.exportSession(sid, format)
    },

    // --------------------------------------------------------------------- //
    // UX-8：`@` 文件提及与 `/` 命令
    // --------------------------------------------------------------------- //
    /**
     * 搜当前工作区的文件，作为 `@` 提及的候选。
     *
     * 结果不存进 state：候选面板只关心"这次关键词的结果"，
     * 存起来反而要维护"上一次查询是否已过期"，成本大于收益。
     *
     * @param query 关键词；空串表示刚敲下 `@`，让后端随便给一批
     * @returns 命中文件；请求失败返回空数组（提示由面板显示"没搜到"）
     */
    async searchMentions(query: string): Promise<MentionFile[]> {
      try {
        const data = await search_workspace_files(query, MENTION_MAX_RESULTS)
        return data.items
      } catch (error) {
        console.error('搜索工作区文件失败:', error)
        return []
      }
    },

    /**
     * 选中一个 `@` 候选：把输入框末尾半截 `@关键词` 换成完整文件路径。
     *
     * 为什么插绝对路径：后端工具（read_file 等）认的是绝对路径，
     * 只插文件名的话模型还得再猜一遍目录，多一次工具调用。
     *
     * @param file 被选中的文件
     */
    insertMention(file: MentionFile): void {
      const matched = /(^|\s)@([^\s@]*)$/.exec(this.input)
      const suffix = `${file.path} `
      // 末尾没有 `@关键词`（比如用户直接点了候选）→ 追加，别把已有内容吃掉
      this.input = matched
        ? `${this.input.slice(0, matched.index + matched[1].length)}${suffix}`
        : `${this.input}${suffix}`
    },

    /**
     * 执行一条**内置**斜杠命令。
     *
     * 为什么内置命令放前端：`/doc` 只是 `\doc` 的另一种写法（后端只认反斜杠），
     * 而 `/clear`、`/export`、`/model`、`/help` 是纯客户端动作——
     * 发给模型只会白白多花一次调用，还得等它回复。
     * 技能命令（source="skill"）不走这里，它们必须按原文发给后端展开提示词。
     *
     * @param cmd 命令定义
     * @param args 空格之后的参数（已 trim，可能为空串）
     * @returns true=这条输入已被前端消化，不要再发请求
     */
    async runCommand(cmd: CommandInfo, args: string): Promise<boolean> {
      switch (cmd.action) {
        case 'doc':
          // 等价改写：`/doc -l` → `\doc -l`，交给原来的文档指令通道（mode='doc'）
          this.input = args ? `\\doc ${args}` : '\\doc'
          await this.send()
          return true
        case 'clear':
          await this.newConversation()
          showToast('已开始新对话')
          return true
        case 'export':
          // 参数只认 json，其余（含空）都按 md 处理，不因为写错参数就报错
          await this.exportCurrent(args.trim().toLowerCase() === 'json' ? 'json' : 'md')
          return true
        case 'model':
          // `/model` 单独敲：弹面板让用户挑；`/model deepseek-v4-pro`：直接切（命令式入口）
          if (args) await this.switchModel(args)
          else this.modelPickerOpen = true
          return true
        case 'help':
          this.showCommandHelp()
          return true
        default:
          return false
      }
    },

    /**
     * `/help`：把命令清单作为一条**本地**助手消息贴出来。
     *
     * 这条消息不进后端历史（后端根本没收到它），所以刷新页面就没了——
     * 这是刻意的：它只是一张说明书，不该污染会话记录、也不该占用上下文预算。
     */
    showCommandHelp(): void {
      const lines = this.commands.map(
        (cmd) => `- \`/${cmd.name}\`（${command_source_label(cmd.source)}）${cmd.description}`,
      )
      this.messages.push({
        role: 'assistant',
        content: lines.length ? `可用命令：\n\n${lines.join('\n')}` : '命令清单还没加载出来，稍后再试。',
      })
    },

    /** 关闭模型选择面板（点遮罩、按 Esc、选完模型都会调它） */
    closeModelPicker(): void {
      this.modelPickerOpen = false
    },

    /**
     * `/model <参数>`：直接切换模型，不弹面板。
     *
     * 参数支持两种写法：
     *   - `deepseek-flash` —— 只写模型名，供应商保持不变；
     *   - `deepseek/deepseek-v4-pro` —— 两段式，前一段必须是已知供应商 id。
     * 无论哪种写法，清单里没有的模型名都会被自动登记成自定义模型（见 settings.selectModel），
     * 所以厂商发新模型时不用等我们改代码，这里直接敲新名字就能用。
     * 为什么要拿供应商清单去比对：很多**模型名本身带斜杠**（如 `meta-llama/Llama-3`），
     * 不比对的话会把模型名劈成供应商 + 模型，反而切错了。
     *
     * 写完立刻生效：后端每轮开头重新读 llm.provider / llm.model，
     * 进行中的流不中断、不换模型（与 UX-8 的切换语义一致）。
     *
     * @param raw 空格之后的原始参数
     */
    async switchModel(raw: string): Promise<void> {
      const text = raw.trim()
      const settings = useSettingsStore()
      // 拉供应商清单：既用来解析两段式，也用来判断「这个模型名要不要顺手登记成自定义模型」
      let providers: LlmProvider[] = []
      try {
        providers = (await fetchProviders()).providers
      } catch (error) {
        // 拉不到清单就退回"整串是模型名"，不因为一次网络失败挡住切换
        console.error('读取供应商清单失败，按模型名处理:', error)
      }

      // 供应商默认沿用当前设置里的那个（只写模型名时供应商不变）
      let providerId = String(settings.entries['llm.provider']?.value ?? 'deepseek')
      let modelName = text
      const slashAt = text.indexOf('/')
      if (slashAt > 0) {
        const maybeProvider = text.slice(0, slashAt)
        const maybeModel = text.slice(slashAt + 1).trim()
        // 前一段确实是供应商 id 才按两段式处理，否则整串当模型名
        if (maybeModel && providers.some((item) => item.id === maybeProvider)) {
          providerId = maybeProvider
          modelName = maybeModel
        }
      }
      if (!modelName) {
        showToast('模型名不能为空')
        return
      }

      // 走 store.selectModel 而不是 saveMany：手写的陌生模型名会自动登记进自定义模型，
      // 否则内置供应商下一轮会报「没有这个模型」，而用户看不出是登记这一步漏了
      const current = providers.find((item) => item.id === providerId)
      const result = await settings.selectModel(
        providerId,
        modelName,
        current?.models.map((item) => item.model) ?? [],
        current?.is_custom ?? false,
      )
      // selectModel 内部走 saveMany，失败会写进 entry.error（不抛异常），读出来判断是否真存下去了
      const failure =
        settings.entries['llm.model']?.error || settings.entries['llm.provider']?.error || ''
      if (failure) {
        showToast(failure)
        return
      }
      showToast(
        result.registered
          ? `已切换到 ${modelName}（已登记为自定义模型，请在设置页确认上下文窗口）`
          : `已切换到 ${modelName}`,
      )
    },

    // --------------------------------------------------------------------- //
    // 发送与终止
    // --------------------------------------------------------------------- //
    /**
     * 发送一轮对话：先把用户消息和空的助手气泡入列，再消费 SSE 事件流逐步填充。
     *
     * 人工确认（human-in-the-loop）：AI 要覆盖/修改文件、删除知识库记录时，后端发
     * confirm_required 并结束本次流；这里弹窗询问，再用 chat_resume 把决定交回后端。
     * 一轮里可能出现多次确认，所以用 while 循环处理，直到某次流里不再有待确认请求。
     */
    async send(): Promise<void> {
      const raw = this.input.trim()
      if (!raw || this.sending) return

      // UX-8：内置斜杠命令在前端执行，不发给模型。
      // 命令清单没拉到（commands 为空）时按普通消息发出去——宁可让后端报"未知技能"，
      // 也不能把用户的输入悄悄吞掉。
      const slash = parse_slash_input(raw)
      if (slash.name && this.commands.length > 0) {
        const builtin = this.commands.find(
          (item) => item.source === 'builtin' && item.name.toLowerCase() === slash.name.toLowerCase(),
        )
        if (builtin) {
          this.input = ''
          if (await this.runCommand(builtin, slash.args)) return
        } else if (!this.commands.some((item) => item.name.toLowerCase() === slash.name.toLowerCase())) {
          // 既不是内置命令也不是已装技能：明确报错。放任它发出去会被模型当成
          // 普通提问回答，用户以为命令生效了，其实什么都没做。
          this.input = ''
          showToast(`未知命令：/${slash.name}`)
          return
        }
      }
      // 只敲了一个 `/`、还没写命令名：继续等用户敲字，别发出去
      if (!slash.name && this.isCommandInput) return

      // 用户气泡显示原始输入（保留 `\doc ...` 写法），做到所见即所发
      this.messages.push({ role: 'user', content: raw })
      this.messages.push({ role: 'assistant', content: '', streaming: true, tools: [] })
      // 关键：拿数组里的**响应式代理**来改，而不是改 push 进去的那个原始对象。
      // Vue 的响应式是"读时包装"的，直接改原始对象不会触发更新（流式输出会一动不动）。
      const bubble = this.messages[this.messages.length - 1] as UIMessage
      const tools = bubble.tools as UIToolCall[]

      // 必须在清空输入框**之前**判断：清空之后 isDocInput 恒为 false，`\doc` 指令会被当成普通提问
      const isDocRequest = this.isDocInput

      this.sending = true
      this.stopRequested = false
      // 新一轮从零开始：上一轮遗留的"排队中"计数不该跟着进来
      this.steerQueued = 0
      this.statusText = STAGE_TEXT.analyzing ?? ''
      this.input = ''
      this.previewFile = null
      // 新一轮重新开始：上一轮的计划不能留在 Todo 面板上
      this.taskPlan = []
      this.taskReason = ''

      /** 后端通过 error 事件下发的错误（HTTP 仍是 200），用于结束后统一提示 */
      let streamError = ''
      /**
       * 本次流里收到的"要问用户"的请求（确认 / 预算），按到达顺序排队。
       * 约定每次流最多一条，但恢复后可能又有新的，所以用队列 + 循环处理。
       */
      const pendingAsks: PendingAsk[] = []

      /** 首次提问与每次恢复执行共用的一套事件回调 */
      const handlers: ChatStreamHandlers = {
        onThinking: (data) => {
          if (data.session_id) this.sessionId = data.session_id
          this.statusText = data.text || STAGE_TEXT[data.stage] || ''
        },
        onToken: (chunk) => {
          this.statusText = ''
          bubble.content += chunk
        },
        onToolStart: (data) => {
          tools.push({ name: data.name })
          this.statusText = `正在执行：${data.name}…`
        },
        onToolEnd: (data: ToolEndEvent) => {
          // 回填到最近一条同名、无结果、且不是确认记录的那一条上。
          // 用下标赋值而不是改对象：数组元素替换才会触发响应式更新
          const index = findLastToolIndex(tools, (item) => item.name === data.name && item.output === undefined && item.confirm === undefined)
          const patch: Partial<UIToolCall> = {
            output: data.output,
            totalChars: data.total_chars,
            truncated: data.truncated,
            continuationRef: data.continuation_ref,
          }
          if (index >= 0) tools[index] = { ...tools[index], ...patch }
          else tools.push({ name: data.name, ...patch })
          this.statusText = ''
        },
        onConfirmRequired: (data) => {
          if (data.session_id) this.sessionId = data.session_id
          pendingAsks.push({ kind: 'confirm', request: data })
          // 先把轨迹标成"等待确认"，让用户在弹窗出现前就知道卡在哪个工具上
          const index = findLastToolIndex(tools, (item) => item.name === data.tool && item.output === undefined && item.confirm === undefined)
          if (index >= 0) tools[index] = { ...tools[index], confirm: 'pending' }
          else tools.push({ name: data.tool, confirm: 'pending' })
          this.statusText = '等待你确认…'
        },
        onBudgetExceeded: (data) => {
          if (data.session_id) this.sessionId = data.session_id
          pendingAsks.push({ kind: 'budget', request: data })
          this.statusText = '预算已超出，等待你选择…'
        },
        onPlan: (data: PlanEvent) => {
          // 拆分结果：初始化 Todo 列表（状态全是 pending，等 task_start 推动）
          this.taskReason = data.reason || ''
          this.taskPlan = data.subtasks.map((item) => ({
            id: item.id,
            title: item.title,
            description: item.description,
            files: item.files ?? [],
            status: 'pending' as SubTaskStatus,
            summary: '',
          }))
        },
        onPlanUpdate: (data: PlanUpdateEvent) => {
          // TASK Phase 2：失败后模型给了新计划。
          // pending=true 是"待确认的草稿"，这里只更新 Todo 列表让用户看清要改成什么；
          // 用户点确认后后端会再推一条 pending=false 的同一事件，那时才把它当作当前计划生效
          this.taskReason = data.reason || this.taskReason
          this.taskPlan = data.subtasks.map((item) => ({
            id: item.id,
            title: item.title,
            description: item.description,
            files: item.files ?? [],
            status: 'pending' as SubTaskStatus,
            summary: '',
          }))
          if (data.pending) {
            showToast('执行计划有调整，等待你确认')
            this.statusText = '等待你确认新的执行计划…'
          } else {
            showToast('已按新计划继续')
            this.statusText = ''
          }
        },
        onTaskStart: (data: TaskStartEvent) => {
          // 用下标替换而不是改对象：Vue 的响应式是"读时包装"，改原对象不会触发更新
          const index = this.taskPlan.findIndex((item) => item.id === data.id)
          if (index >= 0) this.taskPlan[index] = { ...this.taskPlan[index], status: 'running' }
          this.statusText = `第 ${data.index}/${data.total} 步：${data.title}`
        },
        onTaskEnd: (data: TaskEndEvent) => {
          const index = this.taskPlan.findIndex((item) => item.id === data.id)
          const patch = { status: data.status, summary: data.summary ?? '' }
          if (index >= 0) this.taskPlan[index] = { ...this.taskPlan[index], ...patch }
          this.statusText = ''
        },
        onDone: (data) => {
          this.sessionId = data.session_id
          if (data.answer) bubble.content = data.answer
          bubble.streaming = false
          bubble.files = data.files ?? []
          bubble.usage = data.usage ?? null
          bubble.model = data.model
          bubble.elapsed = data.elapsed
          // 后端结果是权威值：用它校正本地状态（也覆盖"刷新后回放"的场景）
          if (data.subtasks?.length) {
            this.taskPlan = data.subtasks.map((item) => ({
              id: item.id,
              title: item.title,
              description: item.description,
              files: item.files ?? [],
              status: item.status,
              summary: item.summary ?? '',
            }))
          }
          this.statusText = ''
        },
        onStopped: (data) => {
          if (data.session_id) this.sessionId = data.session_id
          if (data.answer) bubble.content = data.answer
          bubble.stopped = true
          bubble.streaming = false
          this.statusText = ''
        },
        onSteerInjected: (data: SteerInjectedEvent) => {
          // 插话已经拼进某个工具的结果里，模型下一步就能看到：把"排队中"减掉
          if (data.session_id) this.sessionId = data.session_id
          this.steerQueued = Math.max(0, this.steerQueued - 1)
          this.statusText = '插话已送入上下文，下一步模型会看到'
        },
        onError: (message) => {
          streamError = message
        },
      }

      const controller = new AbortController()
      this.abortController = controller

      try {
        // `\doc` 指令走 doc 模式：整条原文发过去，由后端解析是哪种子命令
        const payload: ChatRequest = isDocRequest
          ? { message: raw, mode: 'doc', session_id: this.sessionId }
          : { message: raw, session_id: this.sessionId }

        await chat_stream(payload, handlers, { signal: controller.signal })

        // 逐个处理"要问用户"的请求：弹层 → 交回后端继续（恢复流里可能又出现新的确认/预算）。
        // 已被终止的轮次不再弹，否则用户点了终止还要再点一次拒绝。
        while (pendingAsks.length > 0 && !streamError && !this.stopRequested) {
          const ask = pendingAsks.shift()!
          // 暂停期间气泡不再闪烁光标（"正在生成"是假的），恢复后重新打开
          bubble.streaming = false
          const { approved, remember } = await this.ask(ask)

          if (ask.kind === 'confirm') {
            const req = ask.request
            const index = tools.findIndex((item) => item.name === req.tool && item.confirm === 'pending')
            if (index >= 0) tools[index] = { ...tools[index], confirm: approved ? 'approved' : 'rejected' }
            this.statusText = approved ? '已同意，继续执行…' : '已拒绝，正在告知 AI…'
            bubble.streaming = true
            await chat_resume(
              { session_id: req.session_id, interrupt_id: req.interrupt_id, approved, remember },
              handlers,
              { signal: controller.signal },
            )
          } else {
            const req = ask.request
            this.statusText = approved ? '继续执行…' : '正在停止…'
            bubble.streaming = true
            await chat_resume(
              { session_id: req.session_id, interrupt_id: req.interrupt_id, approved },
              handlers,
              { signal: controller.signal },
            )
          }
        }
        if (streamError) throw new Error(streamError)
      } catch (error) {
        // 用户主动终止导致的断开（AbortError）不是故障，不弹错误提示
        if (!this.stopRequested) {
          console.error('对话失败:', error)
          if (!bubble.content) bubble.content = `对话失败：${streamError || '请重试'}`
          showToast(streamError || '对话失败')
        }
      } finally {
        bubble.streaming = false
        this.statusText = ''
        this.sending = false
        this.stopRequested = false
        // 这一轮结束后，后端会把没等到工具边界的插话丢掉，前端计数也归零
        this.steerQueued = 0
        this.abortController = null
        // 本轮已经写进后端对话记录，刷新一下会话列表让标题/条数保持最新
        void this.loadSessions()
        // UX-5：本轮用量已经落库，刷新右栏的「本会话」累计
        void this.refreshUsage()
        if (!this.title && this.sessionId) {
          this.title = bubble.content.slice(0, 24) || '新对话'
        }
      }
    },

    /**
     * 点「终止」：叫停本轮对话。
     *
     * 优先"温柔"地中断：只调 POST /chat/stop，让后端自己收尾并推 stopped 事件；
     * 后端在 STOP_FALLBACK_MS 内没反应时才 AbortController 强断前端连接兜底。
     */
    async stop(): Promise<void> {
      if (!this.sending || this.stopRequested) return
      this.stopRequested = true
      this.statusText = '正在终止…'
      const sid = this.sessionId
      if (!sid) {
        this.abortController?.abort()
        return
      }
      try {
        await stop_chat(sid)
      } catch (error) {
        console.error('终止请求失败:', error)
      }
      window.setTimeout(() => {
        if (this.sending) this.abortController?.abort()
      }, STOP_FALLBACK_MS)
    },

    /**
     * 执行中插话（ARCH-6 第 1 档）：把输入框内容作为「追加指令」送给正在跑的那一轮。
     *
     * 与 send 的区别：send 会新开一轮（并要求当前没有在跑），这里只在**已经有一条流**时可用。
     * 后端不会立刻打断当前工具，而是等下一个工具结束时把这句话拼进工具结果——
     * 所以界面上的反馈是「排队中」，不是「已发送」。
     */
    async steer(): Promise<void> {
      if (!this.sending || this.steering) return
      const raw = this.input.trim()
      if (!raw) return
      const sid = this.sessionId
      if (!sid) {
        // 还没有会话 id：说明首轮请求都没送到后端，插话没有落点
        showToast('会话还没建立，暂时不能插话')
        return
      }
      this.steering = true
      try {
        const result = await steer_chat(sid, raw)
        this.input = ''
        this.steerQueued = result.pending
        this.statusText = `已插话，当前工具结束后生效（排队 ${result.pending} 条）`
      } catch (error) {
        // 后端给的是中文原因（开关关了 / 没有活跃流 / 排队已满），直接展示
        showToast(error instanceof Error ? error.message : '插话失败')
      } finally {
        this.steering = false
      }
    },

    /**
     * 取消一个「还没开始执行」的工具（ARCH-6 第 2 档）。
     *
     * 工具已经开始跑时后端会拒绝并说明原因（同步工具无法安全中断），
     * 这里如实把那条提示弹出来，不假装取消成功。
     *
     * @param name 工具名；取自工具轨迹卡片
     */
    async cancelTool(name: string): Promise<void> {
      const sid = this.sessionId
      if (!this.sending || !sid) return
      try {
        const result = await cancel_tool(sid, name)
        this.statusText = `已请求取消 ${result.tool}`
        showToast(`下一个工具开始前会跳过 ${result.tool}`)
      } catch (error) {
        showToast(error instanceof Error ? error.message : '取消失败')
      }
    },

    /**
     * 设置右栏预览的文件；传 null 表示关闭预览。
     *
     * @param file 要预览的文件条目
     */
    setPreview(file: ChatFileRef | null): void {
      this.previewFile = file
    },

    /**
     * 设置搜索关键词并重新拉列表（服务端搜索）。
     *
     * @param query 关键词；空串表示清空搜索
     */
    async searchSessions(query: string): Promise<void> {
      this.searchQuery = query
      await this.loadSessions()
    },

    /**
     * 重命名会话（UX-4）：先本地乐观更新，失败再回滚。
     *
     * @param sessionId 会话 id
     * @param title 新标题
     */
    async renameSession(sessionId: string, title: string): Promise<void> {
      const clean = title.trim()
      if (!clean) return
      // 归档箱里的会话也能改名，所以两个列表都要找一遍
      const target =
        this.sessions.find((item) => item.session_id === sessionId) ??
        this.archivedSessions.find((item) => item.session_id === sessionId)
      const before = target?.title
      // 乐观更新：改名是低风险操作，等一轮网络往返再显示会让输入框"跳回去"
      if (target) target.title = clean
      if (this.sessionId === sessionId) this.title = clean
      try {
        const saved = await rename_chat_session(sessionId, clean)
        if (target) target.title = saved
        if (this.sessionId === sessionId) this.title = saved
      } catch (error) {
        console.error('重命名会话失败:', error)
        if (target && before !== undefined) target.title = before
        if (this.sessionId === sessionId && before !== undefined) this.title = before
        showToast('重命名失败')
      }
    },

    /**
     * 拉取当前会话的累计 token / 费用（UX-5）。
     *
     * 失败时保留旧值并静默（面板少一个数字，不该打断用户）。
     */
    async refreshUsage(): Promise<void> {
      const sid = this.sessionId
      if (!sid) {
        this.usage = null
        return
      }
      try {
        const data = await fetch_session_usage(sid)
        // 请求期间可能已经切到别的会话，丢弃过期响应，避免把 A 的用量显示在 B 上
        if (this.sessionId === sid) this.usage = data
      } catch (error) {
        console.error('加载会话用量失败:', error)
      }
    },

    /**
     * 发起一次询问并等待用户回答（弹层由 ChatView 的 AskOverlay 渲染）。
     *
     * 为什么不像以前那样用命令式 showConfirmDialog：
     * workspace 模式要在弹窗里加一个「记住本工作区授权」勾选框，
     * Vant 的确认框不支持自定义内容；统一成一个受控弹层后，
     * 确认与预算两种询问也能共用同一套交互与样式。
     *
     * @param ask 确认或预算询问
     * @returns 用户的选择（approved + 是否记住授权）
     */
    ask(ask: PendingAsk): Promise<{ approved: boolean; remember: boolean }> {
      this.rememberWorkspace = false
      this.pendingAsk = ask
      return new Promise((resolve) => {
        askResolver = resolve
      })
    },

    /**
     * 提交弹层里的选择（由 AskOverlay 调用）。
     *
     * @param approved true=同意执行 / 继续；false=拒绝 / 停止
     */
    resolveAsk(approved: boolean): void {
      const resolve = askResolver
      askResolver = null
      const ask = this.pendingAsk
      // 只有"确认 + 后端允许记住 + 勾了勾选框"才把 remember 传下去
      const remember = Boolean(
        approved && ask?.kind === 'confirm' && ask.request.can_remember && this.rememberWorkspace,
      )
      this.pendingAsk = null
      this.rememberWorkspace = false
      if (resolve) resolve({ approved, remember })
    },
  },
})
