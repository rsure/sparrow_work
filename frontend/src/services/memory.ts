/**
 * services/memory.ts —— 工作空间记忆接口（MEM）。
 *
 * 与技能 / 诊断一样，这些接口返回**裸 JSON**（没有 { code, message, data } 外壳），
 * 所以这里自己发 fetch，而不是走 services/request 的 get/post（后者会去解 body.data）。
 */
// 拼后端完整 URL
import { buildUrl } from './http'

/** 记忆分类：偏好 / 决策 / 事实 / 待办 */
export type MemoryCategory = 'preference' | 'decision' | 'fact' | 'todo'

/** 分类的中文名（界面展示用） */
export const MEMORY_CATEGORY_LABEL: Record<MemoryCategory, string> = {
  preference: '偏好',
  decision: '决策',
  fact: '事实',
  todo: '待办',
}

/** 一条记忆（对应后端 _to_dict()） */
export interface MemoryItem {
  /** 主键，删除时用 */
  id: number
  /** 所属工作区 id */
  workspace_id: string
  /** 来源会话 id（可能为空：手动添加的记忆没有来源会话） */
  session_id: string | null
  /** 记忆正文 */
  content: string
  /** 分类 */
  category: MemoryCategory
  /** 重要度 1~5 */
  importance: number
  /** auto=自动抽取 / manual=手动添加 */
  source: 'auto' | 'manual'
  /** 创建时间（ISO 字符串） */
  created_at: string | null
  /** 最后修改时间 */
  updated_at: string | null
  /** 最近一次被检索命中的时间（ISO）；null=从未命中 */
  last_used_at: string | null
  /** 被检索命中的累计次数 */
  use_count: number
  /** 被合并进来的次数（近似重复不再丢弃，而是合并到这条上） */
  merged_count: number
  /** 检索分数（只有 /memory/search 的命中项带） */
  score?: number
}

/** GET /api/memory 的响应 */
export interface MemoryList {
  /** 实际查询的工作区 id */
  workspace_id: string
  /** 记忆总开关状态（关掉时界面要提示"不生效"） */
  enabled: boolean
  /** 记忆列表 */
  memories: MemoryItem[]
}

/** GET /api/memory/stats 的响应 */
export interface MemoryStats {
  /** 工作区 id */
  workspace_id: string
  /** 总条数 */
  total: number
  /** 分类分布 */
  by_category: Record<string, number>
  /** 当前生效的向量化后端描述（如 local / remote:text-embedding-3-small / local（远端未配置，已降级）） */
  embedding: string
}

/** POST /api/memory/prune 的响应 */
export interface MemoryPruneResult {
  /** 工作区 id */
  workspace_id: string
  /** 本次共删除的条数（= 过期 + 超限） */
  removed: number
  /** 其中因过期被删的条数 */
  removed_expired: number
  /** 其中因超过条数上限被删的条数 */
  removed_overflow: number
  /** 整理后剩余的条数 */
  total: number
}

/** POST /api/memory/reindex 的响应 */
export interface MemoryReindexResult {
  /** 工作区 id */
  workspace_id: string
  /** 该工作区记忆总条数 */
  total: number
  /** 本次重算了多少条向量 */
  updated: number
  /** 跳过了多少条（维度已与当前后端一致） */
  skipped: number
  /** 当前后端的向量维度 */
  dim: number
  /** 当前生效的向量化后端描述 */
  embedding: string
}

/** 统一的裸 JSON 请求：出错时抛出带状态码的 Error，调用方自己决定怎么提示 */
async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(buildUrl(path), {
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`)
  return (await response.json()) as T
}

/**
 * 列出某个工作区的记忆。
 *
 * @param workspaceId 工作区 id；不传表示后端当前 active 工作区
 * @param category 只看某一类
 */
export async function listMemories(
  workspaceId?: string,
  category?: string,
): Promise<MemoryList> {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  if (category) params.set('category', category)
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return json<MemoryList>(`/memory${suffix}`)
}

/**
 * 拉取条数与分类分布。
 *
 * @param workspaceId 工作区 id；不传表示当前工作区
 */
export function fetchMemoryStats(workspaceId?: string): Promise<MemoryStats> {
  const suffix = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
  return json<MemoryStats>(`/memory/stats${suffix}`)
}

/**
 * 本地检索（纯本地计算，不产生模型调用费用）。
 *
 * @param query 检索关键词
 * @param workspaceId 工作区 id
 * @param topK 返回条数
 */
export async function searchMemories(
  query: string,
  workspaceId?: string,
  topK?: number,
): Promise<{ workspace_id: string; query: string; hits: MemoryItem[] }> {
  return json(`/memory/search`, {
    method: 'POST',
    body: JSON.stringify({ query, workspace_id: workspaceId ?? null, top_k: topK ?? null }),
  })
}

/**
 * 手动新增一条记忆。
 *
 * @param content 记忆正文
 * @param category 分类
 * @param importance 重要度 1~5
 * @param workspaceId 工作区 id
 * @returns saved=false 表示被判为重复（哈希相同或相似度过高）
 */
export function createMemory(
  content: string,
  category: MemoryCategory,
  importance: number,
  workspaceId?: string,
): Promise<{ saved: boolean; memory: MemoryItem | null }> {
  return json(`/memory`, {
    method: 'POST',
    body: JSON.stringify({
      content,
      category,
      importance,
      workspace_id: workspaceId ?? null,
    }),
  })
}

/**
 * 删除一条记忆。
 *
 * @param id 记忆 id
 */
export function deleteMemory(id: number): Promise<{ deleted: boolean }> {
  return json(`/memory/${id}`, { method: 'DELETE' })
}

/**
 * 清空某工作区的全部记忆。
 *
 * @param workspaceId 工作区 id；不传表示当前工作区
 */
export function clearMemories(workspaceId?: string): Promise<{ removed: number }> {
  const suffix = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
  return json(`/memory${suffix}`, { method: 'DELETE' })
}

/**
 * 立即整理记忆：删掉「低重要度且长期没被检索命中」的，再把条数压回上限。
 *
 * 正常流程里抽取结束会自动跑一次；这个接口给用户「刚把保留天数调小，想马上看到效果」用。
 *
 * @param workspaceId 工作区 id；不传表示当前工作区
 */
export function pruneMemories(workspaceId?: string): Promise<MemoryPruneResult> {
  return json(`/memory/prune`, {
    method: 'POST',
    body: JSON.stringify({ workspace_id: workspaceId ?? null }),
  })
}

/**
 * 按当前向量化后端重建记忆向量。
 *
 * 换过 `memory.embedding_backend`（本地 ↔ 远端）之后**必须**跑一次：
 * 两套后端维度不同，旧向量在相似度计算里会被直接跳过——也就是"检索不到"，而且不报错。
 *
 * @param workspaceId 工作区 id；不传表示当前工作区
 * @param force 是否连维度已经一致的行也重算
 */
export function reindexMemories(
  workspaceId?: string,
  force = false,
): Promise<MemoryReindexResult> {
  return json(`/memory/reindex`, {
    method: 'POST',
    body: JSON.stringify({ workspace_id: workspaceId ?? null, force }),
  })
}
