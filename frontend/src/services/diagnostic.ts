/**
 * services/diagnostic.ts —— 诊断接口（OPS-3）。
 *
 * 两个接口都是裸 JSON / 文件流，没有 { code, message, data } 外壳。
 */
// 拼后端完整 URL：导出是文件流，需要自己发 fetch 才能拿到 blob
import { buildUrl } from './http'

/** 诊断概要（对应 GET /api/diagnostic/summary） */
export interface DiagnosticSummary {
  /** 应用版本 */
  version: string
  /** Python 版本 */
  python: string
  /** 操作系统 */
  platform: string
  /** 是否是打包运行 */
  packaged: boolean
  /** 数据库当前迁移版本 */
  db_revision: string
  /** 日志文件绝对路径 */
  log_file: string
  /** 日志文件大小（字节） */
  log_bytes: number
  /** 可导出的轨迹条数 */
  trace_events: number
  /** 库里的表数量 */
  tables: number
}

/** 拉取诊断概要 */
export async function fetchDiagnosticSummary(): Promise<DiagnosticSummary> {
  const response = await fetch(buildUrl('/diagnostic/summary'))
  if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`)
  return (await response.json()) as DiagnosticSummary
}

/** 导出结果：文件名 + 内容 */
export interface DiagnosticPackage {
  /** 后端建议的文件名 */
  filename: string
  /** zip 内容 */
  blob: Blob
}

/**
 * 下载诊断包（zip，已脱敏）。
 *
 * 为什么不直接 `window.open(url)`：那会在浏览器里打开一个白页；
 * 这里取回 blob 后走下载链接，桌面端与浏览器端行为一致。
 *
 * @returns 文件名与 blob
 */
export async function exportDiagnosticPackage(): Promise<DiagnosticPackage> {
  const response = await fetch(buildUrl('/diagnostic/export'))
  if (!response.ok) throw new Error(`导出失败：HTTP ${response.status}`)

  // 文件名优先从 Content-Disposition 里取；取不到就本地生成一个
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const matched = /filename=([^;]+)/.exec(disposition)
  const filename = matched ? matched[1].trim().replace(/^"|"$/g, '') : `diagnostic-${Date.now()}.zip`

  return { filename, blob: await response.blob() }
}

/**
 * 把 blob 存到用户磁盘（浏览器下载语义）。
 *
 * @param blob 文件内容
 * @param filename 文件名
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 立刻 revoke 会让部分浏览器下载中断，延后释放
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
