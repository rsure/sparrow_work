/**
 * 把一个 AI 回答切成可直接渲染的片段数组：普通文本 + 文件引用。
 *
 * 之所以不在模板里用 v-html：文件片段需要绑定点击事件、显示图标与 tooltip，
 * 用 v-html 就得再用事件委托去挂，反而更难读。切成数组后模板里只需一个 v-for。
 */
// Vue 响应式：computed 派生素引结果
import { computed, type ComputedRef } from 'vue'
// 对话服务类型：FileRef 来自 done 事件的 files 字段
import type { ChatFileRef } from '@/services/chat'

/** 渲染片段：text 直接显示；file 渲染成可点击的文件胶囊 */
export interface Segment {
  /** 片段类型：text=普通文字，file=文件引用 */
  type: 'text' | 'file'
  /** 文本片段的内容（type=text 时有） */
  text?: string
  /** 文件信息（type=file 时有） */
  file?: ChatFileRef
}

/**
 * 纯函数：把"纯文本 + 文件清单"组合成片段数组。
 *
 * 匹配规则：回答文本里凡是出现某个清单条目的 `name` 或其完整 `path`，
 * 就把它替换成文件片段。优先匹配更长的字符串（完整路径优先于文件名），
 * 避免"a.md"先命中导致"d:/docs/a.md"只剩半截。
 *
 * @param text 后端清洗后的纯文本回答
 * @param files 该轮回答的文件清单（可能为空）
 * @returns 片段数组
 */
export function splitFileSegments(text: string, files: ChatFileRef[]): Segment[] {
  const refs = [...(files ?? [])]
  if (!text || refs.length === 0) return [{ type: 'text', text }]

  // 每个引用准备两个候选字符串（Windows 路径在正文里可能用 / 也可能用 \）
  const candidates = refs.flatMap((f) => [
    { key: f.path, file: f },
    { key: f.path.replace(/\\/g, '/'), file: f },
    { key: f.name, file: f },
  ]).sort((a, b) => b.key.length - a.key.length) // 长串优先，避免半截匹配

  const segments: Segment[] = []
  let rest = text
  while (rest) {
    // 在剩余文本里找最靠前的候选（多个候选位置相同时取更长的那个，已由排序保证）
    let hit: { index: number; key: string; file: ChatFileRef } | null = null
    for (const c of candidates) {
      const index = rest.indexOf(c.key)
      if (index < 0) continue
      if (!hit || index < hit.index || (index === hit.index && c.key.length > hit.key.length)) {
        hit = { index, key: c.key, file: c.file }
      }
    }
    if (!hit) {
      segments.push({ type: 'text', text: rest })
      break
    }
    if (hit.index > 0) segments.push({ type: 'text', text: rest.slice(0, hit.index) })
    segments.push({ type: 'file', file: hit.file })
    rest = rest.slice(hit.index + hit.key.length)
  }
  return segments
}

/**
 * 响应式版本：answer / files 变化时重新切分（单条回答流式拼接时用）。
 *
 * @param answer 后端清洗后的纯文本回答（响应式）
 * @param files 该轮回答的文件清单（响应式）
 * @returns 片段数组的 computed
 */
export function useFileSegments(
  answer: ComputedRef<string>,
  files: ComputedRef<ChatFileRef[]>,
): ComputedRef<Segment[]> {
  return computed<Segment[]>(() => splitFileSegments(answer.value ?? '', files.value ?? []))
}
