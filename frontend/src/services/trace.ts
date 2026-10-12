/**
 * services/trace.ts —— 执行轨迹回放的接口封装（ARCH-7）。
 *
 * 回放分两步进：先挑会话（`/trace/sessions`），再挑轮次（`/turns`），
 * 最后按轮次读事件（`/trace/sessions/{id}?turn_id=`）。
 *
 * 为什么必须先有"挑一个"的能力：轨迹表里只存 session_id / turn_id，
 * 两个都是 uuid，用户根本记不住；没有列表接口，回放页就进不去。
 *
 * 这些接口同样直接返回裸 JSON（不套 { code, message, data } 外壳）。
 */

// 裸 JSON 请求封装：/trace/* 都返回业务对象本身
import { fetchRawJson } from './http'

/** 有轨迹的会话，对应后端 trace_service.list_trace_sessions 的元素 */
export interface TraceSessionRow {
  /** 会话 id（uuid） */
  session_id: string
  /** 会话标题（从对话记录里查回来的；查不到时为空串，界面显示 id 前 8 位） */
  title: string
  /** 这个会话一共写了多少条轨迹 */
  event_count: number
  /** 这个会话有多少轮对话 */
  turn_count: number
  /** 最早一条轨迹的时间（ISO 字符串） */
  started_at: string | null
  /** 最近一条轨迹的时间（ISO 字符串）；列表按它倒序 */
  last_at: string | null
}

/** 一轮对话的轨迹概要，对应 trace_service.list_turns 的元素 */
export interface TraceTurnRow {
  /** 轮次 id，形如 "t1a2b3c4d5e6f" */
  turn_id: string
  /** 这一轮写了多少条轨迹 */
  event_count: number
  /** 这一轮的模式：agent=工具对话，doc=文档库指令，空串表示没记 */
  mode: string
  /** 这一轮开始时间（ISO 字符串） */
  started_at: string | null
  /** 这一轮最后一条轨迹时间（ISO 字符串） */
  last_at: string | null
}

/** 一条轨迹事件，对应 trace_service.list_events 的元素 */
export interface TraceEventRow {
  /** 自增主键：越大越新（跨轮"整个会话"视图按它排序） */
  id: number
  /** 所属会话 id */
  session_id: string
  /** 所属轮次 id */
  turn_id: string
  /** 轮内步号，从 0 开始（0 是 turn_start）；回放按它排序 */
  seq: number
  /** 事件类型，如 turn_start / thinking / tool_start / tool_end */
  kind: string
  /** 工具名或阶段名（可能为空串） */
  name: string
  /** 结构化内容（后端已把超长字符串截到 2000 字符）；可能为 null */
  payload: Record<string, unknown> | null
  /** 该步耗时（毫秒）；没测时为 0 */
  duration_ms: number
  /** 写入时间（ISO 字符串） */
  created_at: string | null
}

/**
 * 拉取"有轨迹的会话"列表（回放页的左栏）。
 *
 * @param limit 最多取多少个会话（后端上限 200）
 * @returns 按最近有轨迹倒序排好的会话
 */
export async function list_trace_sessions(limit = 50): Promise<TraceSessionRow[]> {
  const data = await fetchRawJson<{ sessions?: TraceSessionRow[] }>(
    `/trace/sessions?limit=${limit}`,
  )
  return data.sessions ?? []
}

/**
 * 拉取某个会话的轮次列表（回放页的中栏）。
 *
 * @param sessionId 会话 id
 * @param limit 最多取多少轮（后端上限 200）
 * @returns 按最近一轮在前排好的轮次
 */
export async function list_trace_turns(sessionId: string, limit = 50): Promise<TraceTurnRow[]> {
  const data = await fetchRawJson<{ turns?: TraceTurnRow[] }>(
    `/trace/sessions/${encodeURIComponent(sessionId)}/turns?limit=${limit}`,
  )
  return data.turns ?? []
}

/**
 * 读取轨迹事件。
 *
 * @param sessionId 会话 id
 * @param turnId 只看某一轮；不传则返回整个会话（按写入顺序）
 * @param limit 最多返回多少条（后端上限 5000）
 * @returns 按 seq（限定轮次时）或写入顺序（整个会话时）排好的事件
 */
export async function fetch_trace_events(
  sessionId: string,
  turnId?: string,
  limit = 500,
): Promise<TraceEventRow[]> {
  // turn_id 只在要限定轮次时拼进 query，避免传空串让后端误以为要筛空轮次
  const turn = turnId ? `&turn_id=${encodeURIComponent(turnId)}` : ''
  const data = await fetchRawJson<{ events?: TraceEventRow[] }>(
    `/trace/sessions/${encodeURIComponent(sessionId)}?limit=${limit}${turn}`,
  )
  return data.events ?? []
}
