/**
 * services/command.ts —— 斜杠命令清单的接口封装（UX-8）。
 *
 * 后端 `GET /api/commands` 一次下发"输入框里敲 `/` 能选什么"：
 *   - 内置命令（source="builtin"）：由**前端**执行，action 告诉前端做哪件事；
 *   - 技能命令（source="skill"）：前端只把原文发出去，展开提示词由后端做。
 *
 * 为什么清单不写死在前端：技能是装在磁盘上的，用户随时新增/禁用，
 * 写死就意味着"装完新技能要改代码才选得到"。
 */

// 裸 JSON 请求封装：/commands 直接返回 { commands: [...] }，不套统一外壳
import { fetchRawJson } from './http'

/** 一条斜杠命令，对应后端 app/services/command_service.py 的 CommandSpec.to_dict() */
export interface CommandInfo {
  /** 命令名，**不含**斜杠，例如 "doc"、"model"；技能命令就是技能名 */
  name: string
  /** 一句话说明，显示在命令名右边 */
  description: string
  /** 参数提示（可为空串），仅用于占位展示 */
  args_hint: string
  /** 来源："builtin"=内置（前端执行），"skill"=技能（后端展开） */
  source: string
  /** 前端要执行的动作：doc / model / clear / export / help；技能命令为空串 */
  action: string
}

/** 命令清单响应，对应 GET /commands */
interface CommandsResponse {
  /** 命令列表：内置在前，技能按名字排序在后 */
  commands?: CommandInfo[]
}

/**
 * 拉取当前可用命令清单。
 *
 * 技能总开关关闭时后端不列技能——列出来也调不动，不如让 `/` 列表诚实反映现状。
 *
 * @returns 命令数组；后端不可达时抛错（调用方按"没有命令"降级即可）
 */
export async function list_commands(): Promise<CommandInfo[]> {
  const data = await fetchRawJson<CommandsResponse>('/commands')
  return data.commands ?? []
}

/**
 * 把命令来源翻译成界面上的小标签。
 *
 * @param source 命令来源（builtin / skill / 其它未知值）
 * @returns 中文标签；未知来源原样返回，便于排查后端加了新来源却没同步前端
 */
export function command_source_label(source: string): string {
  if (source === 'builtin') return '内置'
  if (source === 'skill') return '技能'
  return source
}

/**
 * 从输入框文本里解析出「命令名 + 参数」。
 *
 * 只做前端需要的粗解析（决定要不要弹命令面板），真正的语义由后端/动作执行方决定：
 *   - "/"             → 弹面板但还没有名字
 *   - "/mo"           → 弹面板并筛选
 *   - "/model xxx"    → 已经敲了空格：面板收起，参数原样交给动作
 *
 * @param text 输入框当前内容
 * @returns name=已敲的命令名（可能为空串）；args=第一个空格之后的全部内容（已 trim）
 */
export function parse_slash_input(text: string): { name: string; args: string } {
  const trimmed = text.trimStart()
  // 必须以 "/" 开头，且没有空格时才是在"挑命令"；已敲空格说明进入参数阶段
  if (!trimmed.startsWith('/')) return { name: '', args: '' }
  const body = trimmed.slice(1)
  const spaceAt = body.search(/\s/)
  if (spaceAt < 0) return { name: body.trim(), args: '' }
  return { name: body.slice(0, spaceAt).trim(), args: body.slice(spaceAt + 1).trim() }
}

/**
 * 按关键词筛命令：名字前缀命中的排前面，其次名字包含，最后说明里包含。
 *
 * @param commands 全量命令清单
 * @param keyword 用户已敲的部分（不含斜杠）；空串表示列出全部
 * @returns 排好序的新数组（不改原数组）
 */
export function filter_commands(commands: CommandInfo[], keyword: string): CommandInfo[] {
  const key = keyword.trim().toLowerCase()
  if (!key) return [...commands]
  /** 命中等级：0=名字前缀，1=名字包含，2=说明包含；-1 表示没命中 */
  const rank = (item: CommandInfo): number => {
    const name = item.name.toLowerCase()
    if (name.startsWith(key)) return 0
    if (name.includes(key)) return 1
    if (item.description.toLowerCase().includes(key)) return 2
    return -1
  }
  return commands
    .map((item) => ({ item, rank: rank(item) }))
    .filter((entry) => entry.rank >= 0)
    .sort((a, b) => a.rank - b.rank)
    .map((entry) => entry.item)
}
