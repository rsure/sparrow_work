/**
 * services 统一出口（barrel file）：外部一律从 '@/services' 引入，
 * 这样将来替换底层实现（如把 fetch 换成 axios）时，调用方的 import 路径不用改。
 */
export { fetchHealth } from './health' // 健康检查接口调用
export { API_BASE_URL, API_PREFIX, buildUrl } from './http' // 后端基地址、接口前缀与 URL 拼接工具
export { ApiError, request, get, post, put, del, stream, sse, type ApiResponse } from './request' // 通用请求封装（含 NDJSON/SSE 流式）与统一响应/异常类型
export type { HealthData } from './types' // 健康检查返回的数据结构（仅类型，编译后会被抹掉）

// 斜杠命令清单（UX-8）：`/` 面板的数据源与筛选用纯函数
export {
  command_source_label,
  filter_commands,
  list_commands,
  parse_slash_input,
  type CommandInfo,
} from './command'
// 执行轨迹回放（ARCH-7）：会话 / 轮次 / 事件三级读取
export {
  fetch_trace_events,
  list_trace_sessions,
  list_trace_turns,
  type TraceEventRow,
  type TraceSessionRow,
  type TraceTurnRow,
} from './trace'

// 设置页用的全部接口与类型：普通设置读写、密钥状态、工作区多 profile、供应商清单、测试连接
export {
  createWorkspace,
  deleteSecret,
  deleteWorkspace,
  fetchProviders,
  fetchSecretStatus,
  fetchSettings,
  fetchSettingsMeta,
  fetchWorkspaces,
  probeLlm,
  saveSecret,
  saveSettings,
  setActiveWorkspace,
  updateWorkspace,
  type LlmModel,
  type LlmProbeRequest,
  type LlmProbeResult,
  type LlmProvider,
  type LlmProvidersResponse,
  type SecretStatus,
  type SettingCategory,
  type SettingDef,
  type SettingType,
  type SettingsMap,
  type Workspace,
  type WorkspacesResponse,
} from './settings'