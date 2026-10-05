/**
 * services/mcp.ts —— MCP 管理接口（EXT-2）。
 *
 * 与 /skills 一样是**裸 JSON**（没有 { code, message, data } 外壳），
 * 所以自己发 fetch，不走 services/request 的统一封装。
 */
// 拼后端完整 URL
import { buildUrl } from './http'

/** 一个 server 里已发现的工具（名字已带 mcp__ 前缀） */
export interface McpToolInfo {
  /** 包装后的工具名（mcp__server__tool），也是策略与审计里的名字 */
  name: string
  /** MCP 侧的原始工具名 */
  raw_name: string
  /** 工具说明（已截断，够展示即可） */
  description: string
}

/** 一个 server 的连接状态 */
export interface McpServerStatus {
  /** server 名 */
  name: string
  /** 传输方式描述（不含密钥） */
  description: string
  /** 是否连上了 */
  ok: boolean
  /** 工具数 */
  tool_count: number
  /** 工具清单 */
  tools: McpToolInfo[]
  /** 失败原因（ok=false 时非空） */
  error: string
  /** 发现耗时（毫秒） */
  duration_ms: number
}

/** GET /api/mcp/servers 的响应 */
export interface McpSnapshot {
  /** 总开关 */
  enabled: boolean
  /** 各 server 状态 */
  servers: McpServerStatus[]
  /** 配置级错误（JSON 写错、字段缺失等，不是连接错误） */
  errors: string[]
  /** 可用工具总数 */
  tool_count: number
}

/** POST /api/mcp/test 的响应 */
export interface McpTestResult {
  /** 是否连上 */
  ok: boolean
  /** 该配置会提供的工具 */
  tools: Array<{ name: string; description: string }>
  /** 失败原因 */
  error: string
  /** 耗时（毫秒） */
  duration_ms: number
}

/**
 * 发一个返回裸 JSON 的 MCP 接口请求。
 *
 * @param path 接口路径（不含 /api 前缀）
 * @param init 额外 fetch 配置
 * @returns 后端返回的裸 JSON
 */
async function mcpJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(buildUrl(path), init)
  if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`)
  return (await response.json()) as T
}

/**
 * 拉取 server 状态快照。
 *
 * @returns 快照
 */
export function fetchMcpServers(): Promise<McpSnapshot> {
  return mcpJson<McpSnapshot>('/mcp/servers')
}

/**
 * 重新连接全部 server（改完配置后点「重连」）。
 * 后端会同时清空 LLM 缓存，让新工具在下一轮对话就可见。
 *
 * @returns 重连后的快照
 */
export function reloadMcpServers(): Promise<McpSnapshot> {
  return mcpJson<McpSnapshot>('/mcp/reload', { method: 'POST' })
}

/**
 * 试连一条 server 配置（不保存、不影响当前工具集）。
 *
 * @param config 单条 server 配置（与 mcp.servers 的元素同构）
 * @returns 试连结果
 */
export function testMcpServer(config: Record<string, unknown>): Promise<McpTestResult> {
  return mcpJson<McpTestResult>('/mcp/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}
