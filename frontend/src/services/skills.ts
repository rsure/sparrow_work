/**
 * services/skills.ts —— 技能管理接口（EXT-1）。
 *
 * 三个接口都是**裸 JSON**（不像 /settings 那样套 { code, message, data }），
 * 所以这里自己发 fetch，而不是走 services/request 的 get/post。
 */
// 拼后端完整 URL：技能接口不走统一外壳，需要自己发 fetch
import { buildUrl } from './http'

/** 一个已安装技能的元数据（对应后端 SkillSpec.to_dict()） */
export interface SkillInfo {
  /** 技能 id，也是 `/技能名` 指令里的名字 */
  name: string
  /** 一句话说明（进系统提示词） */
  description: string
  /** 声明会用到的工具名 */
  tools: string[]
  /** SKILL.md 的绝对路径（排障用） */
  path: string
  /** 文件修改时间（秒） */
  mtime: number
  /** 是否启用（由 skill.disabled 派生） */
  enabled: boolean
  /** 正文长度（字符），用于展示"这份技能多长" */
  body_chars: number
}

/** 加载失败的技能（用户手写 frontmatter 出错时会出现） */
export interface SkillError {
  /** 出问题的 SKILL.md 路径 */
  path: string
  /** 失败原因（可直接展示） */
  reason: string
}

/** GET /api/skills 的响应 */
export interface SkillSnapshot {
  /** 已解析成功的技能 */
  skills: SkillInfo[]
  /** 解析失败的文件 */
  errors: SkillError[]
  /** 实际扫描的目录 */
  dirs: string[]
  /** 技能系统总开关 */
  enabled: boolean
  /** 被单独禁用的技能名 */
  disabled: string[]
}

/** 技能详情（比列表多一个正文） */
export interface SkillDetail extends SkillInfo {
  /** 技能正文（给模型的操作说明） */
  body: string
}

/**
 * 发一个返回裸 JSON 的技能接口请求。
 *
 * @param path 接口路径（不含 /api 前缀）
 * @param init 额外 fetch 配置
 * @returns 后端返回的裸 JSON
 */
async function skillJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(buildUrl(path), init)
  if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`)
  return (await response.json()) as T
}

/**
 * 拉取技能清单与扫描状态。
 *
 * @returns 技能快照
 */
export function fetchSkills(): Promise<SkillSnapshot> {
  return skillJson<SkillSnapshot>('/skills')
}

/**
 * 重新扫描技能目录（用户装好新技能后点刷新）。
 * 后端会同时清空 LLM 缓存，让新技能在下一轮对话就生效。
 *
 * @returns 重载后的快照
 */
export function reloadSkills(): Promise<SkillSnapshot> {
  return skillJson<SkillSnapshot>('/skills/reload', { method: 'POST' })
}

/**
 * 读取某个技能的完整正文。
 *
 * @param name 技能名
 */
export function fetchSkillBody(name: string): Promise<SkillDetail> {
  return skillJson<SkillDetail>(`/skills/${encodeURIComponent(name)}`)
}
