/**
 * settings.ts —— 后端设置体系相关接口的封装层。
 *
 * 覆盖四组接口（按路由前缀拆分，对应后端 app/controllers/setting_controller.py）：
 *   1. /api/settings                  普通设置（meta + 全量读写）
 *   2. /api/settings/export|import    配置导入导出（OPS-5，导出的是脱敏快照）
 *   3. /api/settings/secrets/{key}    密钥（只进不出，只回脱敏值）
 *   4. /api/settings/workspaces(...) 工作区多 profile
 *
 * 单独再加一组 /api/llm/*：列出供应商清单 + 测试连接。
 *
 * 本文件只做「请求 → 后端 → 返回 data」一层薄封装，不缓存、不存状态——
 * 状态层在 stores/settings.ts 与 stores/workspaces.ts 中。
 * 调用方拿到的是已经解开 { code, message, data } 外壳后的真正数据；
 * 失败时一律走 request 抛出的 ApiError。
 */

import { del, get, post, put } from './request' // 通用请求封装：get/post/put/del 自动解析 {code,message,data} 外壳并抛 ApiError

// =========================================================================== //
// 1. 普通设置：元数据 + 全量值
// =========================================================================== //

/** 设置项的值类型，对应后端 SettingKind（app/services/settings_registry.py） */
export type SettingType = 'bool' | 'int' | 'float' | 'string' | 'json' | 'select'

/** 设置页分区，对应后端 category；前端据此把控件分到不同 SettingSection */
export type SettingCategory =
  | 'theme'
  | 'model'
  | 'input'
  | 'permission'
  | 'cost'
  | 'skill'
  | 'mcp'
  | 'diagnostic'
  | 'tools'
  | 'context'
  | 'agent'
  | 'task'
  | 'memory'
  | 'office'
  | 'advanced'
  | 'workspace'

/** 单个设置项的 schema 描述，对应 GET /api/settings/meta 的元素 */
export interface SettingDef {
  /** 设置键，形如 "llm.model"，全局唯一 */
  key: string
  /** 中文展示名（设置页标题）；后端没给时前端回退显示 key */
  label: string
  /** select 候选值的中文标签，与 options 一一对应；其它类型为 null */
  option_labels: string[] | null
  /** 值类型：bool/int/float/string/json/select；前端按它选控件 */
  type: SettingType
  /** 默认值；用户没落库时后端返回它；json/select 类型时是数组/字符串 */
  default: unknown
  /** 数值下界（int/float 才有）；其它类型为 null */
  min: number | null
  /** 数值上界（int/float 才有）；其它类型为 null */
  max: number | null
  /** select 类型的候选值；其它类型为 null */
  options: string[] | null
  /** 设置页分区；同一分区下渲染到同一个 SettingSection */
  category: SettingCategory
  /** 首次引入的里程碑（如 "M1"），仅展示用 */
  since: string
  /** 面向用户的一句话说明，写在控件上方当 hint */
  description: string
  /** 是否密钥项；当前 meta 接口里恒为 false（密钥走另外一组接口） */
  secret: boolean
}

/** 普通设置的当前值集合，对应 GET /api/settings 与 PUT /api/settings 的 data.values */
export type SettingsMap = Record<string, unknown>

/**
 * 拉取全部设置项的 schema（**只含元数据、不含当前值**）。
 * 后端在 create_app() 时一次性装配好 BUILTIN_DEFS + 各模块追加的声明，按键名排序返回。
 *
 * @returns SettingDef 数组；后端不可达或业务码非 0 时抛 ApiError
 */
export function fetchSettingsMeta(): Promise<SettingDef[]> {
  return get<SettingDef[]>('/settings/meta')
}

/**
 * 拉取全部非密钥设置项的当前值（**不含任何 secrets.* 键**）。
 * 已落库值优先，未落库则回落到声明默认值——调用方拿到时永远是合法值。
 *
 * @returns SettingsMap（key → value）；后端不可达或业务码非 0 时抛 ApiError
 */
export async function fetchSettings(): Promise<SettingsMap> {
  // 注意：后端返回的是 { values: {...} }（SettingsOut），不是裸的键值表——
  // 少拆一层会让所有设置项都回落到默认值，而且不会报错，是很容易漏的坑
  const data = await get<{ values: SettingsMap }>('/settings')
  return data.values ?? {}
}

/**
 * 批量保存普通设置：partial 里只需包含要改的键，未出现的键保持原值。
 * 后端「全量校验通过才落库」：只要有一个键非法，整个请求都不写。
 *
 * @param partial 要保存的键值对（仅含本次要改的键）
 * @returns 保存后**全部**非密钥设置项的当前值（前端用这次返回值原地刷新视图）
 */
export async function saveSettings(partial: SettingsMap): Promise<SettingsMap> {
  // 与 fetchSettings 同理：写入后后端回的是 { values: {...} }，这里拆出真正的键值表
  const data = await put<{ values: SettingsMap }>('/settings', { values: partial })
  return data.values ?? {}
}

// =========================================================================== //
// 2. 配置导入导出（OPS-5）
// =========================================================================== //

/** 导出文件里的「某个密钥设置过没有」；只有布尔，没有密钥值 */
export interface SecretPoint {
  /** 密钥名（不带 secrets. 前缀），如 "deepseek.api_key" */
  key: string
  /** 该密钥在本机是否已设置；true 表示换机器后需要重新填写 */
  set: boolean
}

/**
 * 配置导出快照，对应 GET /api/settings/export 的 data。
 *
 * 注意：这是一份**脱敏**快照——不含任何密钥明文；含疑似密钥的设置项（如 mcp.servers）
 * 其值被替换成 `***REDACTED***`，并出现在 redacted_keys 里。
 */
export interface SettingsExport {
  /** 导出格式标识，形如 "app-settings/1"；导入时后端会校验它 */
  format: string
  /** 导出时间（ISO 8601，精确到秒），用于分辨新旧备份 */
  exported_at: string
  /** 导出时的应用版本号 */
  app_version: string
  /** 键 → 值；含疑似密钥的键其值是占位符 */
  values: Record<string, unknown>
  /** 值被脱敏的键名；导入时后端会整键跳过 */
  redacted_keys: string[]
  /** 密钥设置状态清单（只有键名与是否设置） */
  secrets: SecretPoint[]
}

/** 导入时被跳过的一个键及原因 */
export interface SettingsImportSkipped {
  /** 被跳过的设置键 */
  key: string
  /** 跳过原因（中文，可直接展示给用户） */
  reason: string
}

/** 配置导入结果，对应 POST /api/settings/import 的 data */
export interface SettingsImportResult {
  /** 真正写入本机的键 */
  applied: string[]
  /** 被跳过的键及原因 */
  skipped: SettingsImportSkipped[]
  /** 导入后全部非密钥设置项的当前值 */
  values: SettingsMap
}

/**
 * 导出当前配置（脱敏 JSON 对象）。
 * 后端已经把密钥与疑似密钥的值抹掉了，前端只需把它存成文件。
 */
export function exportSettings(): Promise<SettingsExport> {
  return get<SettingsExport>('/settings/export')
}

/**
 * 导入一份配置：后端逐键校验，只写合法且未被脱敏的键。
 *
 * @param payload 从导出文件里读回来的 JSON（多出的字段会被忽略）
 * @returns 写入/跳过清单 + 导入后的全量设置值
 */
export function importSettings(payload: {
  format?: string
  values: Record<string, unknown>
  redacted_keys?: string[]
}): Promise<SettingsImportResult> {
  return post<SettingsImportResult>('/settings/import', payload)
}

// =========================================================================== //
// 3. 密钥：只进不出
// =========================================================================== //

/** 某个密钥的状态，对应 GET /api/settings/secrets/{key} */
export interface SecretStatus {
  /** 该密钥是否已设置 */
  set: boolean
  /** 脱敏后的密钥（形如 sk-****ijkl）；未设置时为 null；永远不会回明文 */
  masked: string | null
}

/**
 * 查询某个密钥是否已设置，**只回脱敏值**（绝不返回明文）。
 * 注意 key 不带 "secrets." 前缀，例如 "deepseek.api_key"。
 *
 * @param key 密钥名（如 "deepseek.api_key"）
 */
export function fetchSecretStatus(key: string): Promise<SecretStatus> {
  return get<SecretStatus>(`/settings/secrets/${encodeURIComponent(key)}`)
}

/**
 * 覆盖写入一个密钥：保存后立即返回脱敏状态（前端无需再发 GET 就能刷新显示）。
 * 后端优先存进系统钥匙串，钥匙串不可用时降级为 Fernet 密文存库，库中始终没有明文。
 *
 * @param key 密钥名（不带 "secrets." 前缀）
 * @param value 密钥明文
 */
export function saveSecret(key: string, value: string): Promise<SecretStatus> {
  return put<SecretStatus>(`/settings/secrets/${encodeURIComponent(key)}`, { value })
}

/** 删除某个密钥，使其回到「未设置」状态 */
export function deleteSecret(key: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/settings/secrets/${encodeURIComponent(key)}`)
}

// =========================================================================== //
// 4. 工作区（多 profile）
// =========================================================================== //

/** 单个工作区 profile，对应 app/schemas/workspace.py 的 WorkspaceProfile */
export interface Workspace {
  /** 工作区唯一 id（后端分配），形如 "w-1"；旧数据迁移出来的默认工作区是 "w-default" */
  id: string
  /** 工作区展示名，可重命名；同一台机器上不要求唯一 */
  name: string
  /** 该工作区的根目录绝对路径列表（文件工具允许写入/执行的目录范围） */
  roots: string[]
  /** 是否为当前生效工作区；这是冗余标记，权威值见 WorkspacesResponse.active_id */
  active: boolean
}

/** 工作区列表响应，对应 GET /api/settings/workspaces 的 data */
export interface WorkspacesResponse {
  /** 全部工作区，顺序与用户创建顺序一致 */
  workspaces: Workspace[]
  /** 当前生效工作区的 id；没有任何工作区时为空字符串 */
  active_id: string
}

/**
 * 拉取全部工作区。首次调用时若后端检测到旧数据（workspace_roots 键），
 * 会自动迁移成一个默认工作区（id="w-default"），迁移是只读的。
 */
export function fetchWorkspaces(): Promise<WorkspacesResponse> {
  return get<WorkspacesResponse>('/settings/workspaces')
}

/** 新建工作区；新建不会抢走当前工作区，但若这是第一个则会自动成为当前工作区 */
export function createWorkspace(name: string, roots: string[]): Promise<Workspace> {
  return post<Workspace>('/settings/workspaces', { name, roots })
}

/**
 * 更新工作区。name 与 roots 都可省略：
 *   - 只传 name → 改名
 *   - 只传 roots → 改根目录
 *   - 都不传 → 原样返回（不写入）
 *
 * 注意：传 roots=[] 表示「清空全部根目录」，与不传语义不同。
 */
export function updateWorkspace(
  id: string,
  patch: { name?: string; roots?: string[] },
): Promise<Workspace> {
  // 显式挑出有定义的字段，避免传 undefined 把后端「不传 = 保持原值」的语义挤掉
  const body: { name?: string; roots?: string[] } = {}
  if (patch.name !== undefined) body.name = patch.name
  if (patch.roots !== undefined) body.roots = patch.roots
  return put<Workspace>(`/settings/workspaces/${encodeURIComponent(id)}`, body)
}

/** 删除工作区；若删的是当前工作区，后端会自动顺延到剩下的第一个 */
export function deleteWorkspace(id: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/settings/workspaces/${encodeURIComponent(id)}`)
}

/**
 * 切换当前工作区。请求体同时接受 { id } 与 { workspace_id }，两个都传时以 id 为准。
 *
 * @param id 目标工作区 id
 */
export function setActiveWorkspace(id: string): Promise<{ active_id: string }> {
  return post<{ active_id: string }>('/settings/workspaces/active', { id })
}

// =========================================================================== //
// 5. 模型供应商 + 测试连接
// =========================================================================== //

/** 单个模型的元数据，对应 app/llm/registry.py 的 ModelSpec.to_dict() */
export interface LlmModel {
  /** API 调用用的模型名（如 "deepseek-chat"） */
  model: string
  /** 展示名（如 "DeepSeek Chat"） */
  label: string
  /** 上下文窗口上限（单位：token）；压缩策略用它作为分母 */
  context_window: number
  /** 是否支持工具调用（function calling） */
  supports_tools: boolean
  /** 是否支持图片输入（首版只展示，不启用多模态） */
  supports_vision: boolean
  /** 每百万输入 token 的价格（单位：元） */
  price_in: number
  /** 每百万输出 token 的价格（单位：元） */
  price_out: number
}

/** 单个供应商的清单，对应 GET /api/llm/providers 的元素 */
export interface LlmProvider {
  /** 供应商 id（"deepseek" / "openai" / "custom-myapi" 等），全局唯一 */
  id: string
  /** 展示名（设置页下拉里显示） */
  label: string
  /** 默认接口地址；空串表示用供应商官方默认地址 */
  base_url: string
  /** 是否需要 API Key（Ollama 跑本地，不需要） */
  requires_key: boolean
  /** 是否为用户自定义的供应商（前端展示时标「自定义」标签） */
  is_custom: boolean
  /** 该供应商的模型清单；自定义端点查不到时为 [] */
  models: LlmModel[]
}

/** 供应商清单响应，对应 GET /api/llm/providers 的 data */
export interface LlmProvidersResponse {
  /** 全部供应商（内置 + 用户自定义） */
  providers: LlmProvider[]
}

/** 拉取全部可用的供应商与模型清单；用于模型区下拉框 + 显示上下文窗口与价格 */
export function fetchProviders(): Promise<LlmProvidersResponse> {
  return get<LlmProvidersResponse>('/llm/providers')
}

/** 测试连接的请求体，对应 POST /api/llm/probe */
export interface LlmProbeRequest {
  /** 要测的供应商 id */
  provider: string
  /** 要测的模型名；留空则用该供应商的默认模型 */
  model?: string | null
  /** 要测的接口地址；留空则用设置里的 llm.base_url */
  base_url?: string | null
}

/** 测试连接的响应，对应 POST /api/llm/probe 的 data */
export interface LlmProbeResult {
  /** 是否成功（发了一次最小请求并拿到响应） */
  ok: boolean
  /** 请求耗时毫秒数（成功失败都有） */
  latency_ms: number
  /** 失败原因（成功时为 null）；只是错误文案，不含任何密钥内容 */
  error: string | null
  /** 失败分类；前端按它给不同提示：
   *  - "secret"  → 密钥未配置或鉴权失败 → 提示「请检查 API Key」
   *  - "model"   → 该供应商下没有这个模型 → 提示「请选择下拉框里的模型」
   *  - "network" → 网络不通 / 服务不可达 → 提示「检查网络或代理设置」
   *  - null      → 成功
   */
  error_kind: 'secret' | 'model' | 'network' | null
}

/**
 * 发一次最小请求验证「密钥对不对、模型名存不存在、网络通不通」。
 * 后端只用钥匙串里的密钥去发请求，不回传、不打日志，**安全红线**。
 *
 * @param req 测试连接的参数（供应商必填，模型与 base_url 可选）
 */
export function probeLlm(req: LlmProbeRequest): Promise<LlmProbeResult> {
  return post<LlmProbeResult>('/llm/probe', req)
}