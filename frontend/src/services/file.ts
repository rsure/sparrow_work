import { get } from './request' // 通用请求封装：GET 查列表，自动解开统一响应外壳（file 预览接口用）

/** 文件大类。字面量联合而不是 string —— 拼错立刻编译报错 */
export type FileKind = 'document' | 'image' | 'video' | 'audio' | 'archive' | 'code' | 'other'

/**
 * 扩展名 → 文件大类的映射表。
 * key 是小写扩展名（不带点），value 是归类结果；表里查不到的扩展名由调用方落到 'other'。
 */
export const EXT_TO_KIND: Readonly<Record<string, FileKind>> = {
  // 文档类：可被 RAG 切片入库的文本/办公文档
  pdf: 'document',
  doc: 'document',
  docx: 'document',
  txt: 'document',
  md: 'document',
  // 图片类
  jpg: 'image',
  jpeg: 'image',
  png: 'image',
  gif: 'image',
  webp: 'image',
  // 视频类
  mp4: 'video',
  mkv: 'video',
  avi: 'video',
  mov: 'video',
  // 音频类
  mp3: 'audio',
  wav: 'audio',
  flac: 'audio',
  // 压缩包类
  zip: 'archive',
  rar: 'archive',
  '7z': 'archive',
  tar: 'archive',
  gz: 'archive',
  // 代码类
  ts: 'code',
  js: 'code',
  py: 'code',
  java: 'code',
  vue: 'code',
  json: 'code',
}

/** 全部文件大类的有序列表：供下拉筛选等需要「遍历所有类别」的场景使用（含兜底的 other） */
export const FILE_KINDS: readonly FileKind[] = [
  'document',
  'image',
  'video',
  'audio',
  'archive',
  'code',
  'other',
] as const

export interface FileEntry {
  /** 绝对路径，全局唯一 —— 拿它当 key（见 10.2） */
  readonly path: string
  /** 文件名（含扩展名，不含目录），列表里展示用 */
  readonly name: string
  /** 字节数。格式化是展示层的事，这里存原始值 */
  readonly fileSize: number
  /** 文件大类，由扩展名经 EXT_TO_KIND 映射而来，用于按类别筛选/着色 */
  readonly kind: FileKind
  /** 是否是文件夹：为 true 时 fileSize 恒为 0，且不能被导入 RAG */
  readonly isDirectory: boolean
  /** ISO 8601 字符串，不是 Date（见下） */
  readonly modifiedAt: string
  /** 是否已经入库到 RAG 索引：false 表示还没导入，可作为「待导入」标记 */
  readonly indexed: boolean
}

/** 文件列表可排序的字段：与 FileEntry 的键同名，排序时直接按该键取值 */
export type SortField = 'name' | 'fileSize' | 'modifiedAt' | 'kind'
/** 排序方向：asc=升序（小→大/旧→新），desc=降序（大→小/新→旧） */
export type SortOrder = 'asc' | 'desc'

/** 类型守卫：把 unknown 收窄为 FileKind（Set.has 本身不收窄，这里补上） */
export function isFileKind(value: unknown): value is FileKind {
  return typeof value === 'string' && FILE_KINDS.includes(value as FileKind)
}

/**
 * 索引状态：判别联合的雏形，每种状态带自己的附加字段。
 * - idle：空闲，没有进行中的索引任务
 * - running：运行中，done=已处理块数、total=总块数（进度按 done/total 展示）
 * - failed：失败，message=失败原因，可直接展示给用户
 * - done：已完成，chunkCount=本次最终入库的切片数量
 */
export type IndexStatus =
    | { phase: 'idle' }
    | { phase: 'running'; done: number; total: number }
    | { phase: 'failed'; message: string }
    | { phase: 'done'; chunkCount: number }

/** 判断索引是否正在运行：收窄成 running 成员后可直接读 done/total 画进度条 */
export function isIndexRunning(
    status: IndexStatus,
): status is Extract<IndexStatus, { phase: 'running' }> {
  return status.phase === 'running'
}

/** 把索引状态翻译成一句中文文案，直接渲染到界面上（tooltip / 状态行） */
export function describeStatus(status: IndexStatus): string {
  switch (status.phase) {
    case 'idle':
      return '空闲'
    case 'running':
      return `正在索引 ${status.done}/${status.total}`
    case 'failed':
      return `索引失败：${status.message}`
    case 'done':
      return `已完成，共 ${status.chunkCount} 块`
  }
}

/** 文件类型条目，对应后端 GET /api/file/catalog 的返回元素 */
export interface FileMeta {
  /** 文件绝对路径 */
  path: string
  /** 文件名 */
  name: string
  /** 类别：text/image/rich/binary/missing */
  kind: 'text' | 'image' | 'rich' | 'binary' | 'missing'
  /** 是否可在页面内预览 */
  previewable: boolean
  /** 字节数 */
  size: number
  /** 人类可读大小文案 */
  size_text: string
  /** 不可预览的原因 */
  reason: string
  /** MIME 类型 */
  mime: string
}

/** 预览结果，对应后端 GET /api/file/preview 的返回 */
export interface FilePreview {
  /** 是否取到了内容（false 时看 reason） */
  ok: boolean
  /** 内容类型，与 FileMeta.kind 同义，另含 denied */
  kind: string
  /** 文本内容；图片与不可预览格式为空串 */
  content: string
  /** 失败或不可预览的原因 */
  reason: string
  /** 文本编码（如 utf-8），仅 text 有 */
  encoding?: string
  /** 内容是否被截断 */
  truncated: boolean
  /** 图片的直链地址（相对 /api，仅 image 有） */
  raw_url?: string
}

/** 批量取文件清单：paths 以重复 query 键传递，后端用 list[str] 接收 */
export function fetch_file_catalog(paths: string[]): Promise<FileMeta[]> {
  const qs = paths.map((p) => `paths=${encodeURIComponent(p)}`).join('&')
  return get<FileMeta[]>(`/file/catalog${qs ? `?${qs}` : ''}`)
}

/** 取文本预览内容 */
export function fetch_file_preview(path: string): Promise<FilePreview> {
  return get<FilePreview>('/file/preview', { path })
}

/** `@` 文件提及的候选条目，对应后端 GET /api/file/search 的 items 元素 */
export interface MentionFile {
  /** 文件绝对路径；用户选中后插进输入框的就是它（后端工具认绝对路径） */
  path: string
  /** 文件名（含扩展名），候选列表的主行 */
  name: string
  /** 相对当前工作区根目录的路径，候选列表的副行（用来区分同名文件） */
  rel: string
  /** 后端判定的类别：text/image/rich/binary；前端只用它选图标 */
  kind: string
  /** 人类可读的大小文案，如 "12.3 KB" */
  size_text: string
}

/** `@` 文件搜索的返回体，对应 GET /api/file/search 的 data */
export interface MentionSearchResult {
  /** 本次搜索的关键词（原样回显，便于前端判断响应是否已经过期） */
  query: string
  /** 命中的文件：文件名前缀命中的排最前 */
  items: MentionFile[]
  /** 本次搜索覆盖的工作区根目录；空数组说明还没设置工作区 */
  roots: string[]
  /** 是否因为文件太多提前截断（true 时提示用户写更精确的关键词） */
  truncated: boolean
}

/**
 * 在当前工作区里按文件名搜文件（`@` 提及的候选来源）。
 *
 * 为什么走后端而不是在前端遍历：工作区可能有几万个文件，
 * 前端拿到全量目录再筛既慢又占内存；后端走一次目录遍历就能按分数排好。
 *
 * 不传 limit：候选条数由后端契约表决定（默认 20、上限 50）。
 * 后端返回多少，提及面板就渲染多少（SuggestPanel 是全量 v-for），前端不再自己乘以或截断。
 *
 * @param query 关键词；空串表示"刚敲下 `@`"，返回一批文件让用户先看到东西
 */
export function search_workspace_files(query: string): Promise<MentionSearchResult> {
  return get<MentionSearchResult>('/file/search', { q: query })
}
