import { get , post, put, del } from './request' // 通用请求封装：GET 查列表、POST 发起动作、PUT 覆盖式更新、DELETE 删记录，自动解开统一响应外壳
import { buildUrl } from './http' // 只拼地址不发请求：SSE 地址要交给 EventSource，所以不能走 request
import type {FileEntry} from "@/services/file"; // 文件条目类型：SSE 推送的每个文件项都是这个形状，前端可直接当 FileEntry 用

export interface ScanTaskInfo {
  /** 任务唯一标识，订阅进度/文件 SSE 时作为 query 参数回传 */
  task_id: string
  /** 被扫描的文件夹绝对路径 */
  path: string
  /** 任务状态：pending=排队中，running=扫描中，done=已完成，cancelled=用户取消，failed=失败 */
  status: 'pending' | 'running' | 'done' | 'cancelled' | 'failed'
  /** 已扫描到的文件数量（进度计数） */
  scanned: number
  /** 已扫描文件的总字节数（原始值，格式化交给 total_bytes_human） */
  total_bytes: number
  /** 总字节数的人类可读文本，如 '1.2 GB'，直接展示 */
  total_bytes_human: string
  /** 被跳过的文件/目录数量（无权限、符号链接等） */
  skipped: number
  /** 失败原因文案；非失败状态时为 null */
  error: string | null
  /** 任务创建时间（ISO 8601 字符串） */
  created_at: string
  /** 实际开始扫描的时间；尚未开始时为 null */
  started_at: string | null
  /** 任务结束时间（完成/取消/失败）；未结束时为 null */
  ended_at: string | null
  /** 已耗时秒数，前端 toFixed(1) 后展示为「耗时 x.x s」 */
  elapsed: number
}

/** 后端统一分页外壳：一页数据 + 总数 + 当前页码 + 每页条数 */
export interface Page<T> {
  /** 当前页的数据条目 */
  items: T[]
  /** 符合条件的总条数（用于算总页数） */
  total: number
  /** 当前页码，从 1 开始 */
  page: number
  /** 每页条数 */
  size: number
}

/** 对应后端 GET /scan/files/stream 推送的每个 "files" SSE 事件，字段均为 camelCase，可直接当 FileEntry 用 */
export interface ScanFileChunk {
  /** 本批新增的文件条目（增量推送，不是全量） */
  items: FileEntry[]
  /** 本批第一条在全量结果中的下标，用于续传（from_index）时去重 */
  fromIndex: number
  /** 截至目前累计扫描的文件数 */
  scanned: number
  /** 截至目前累计字节数（原始值） */
  totalBytes: number
  /** 累计字节数的人类可读文本，如 '1.2 GB' */
  totalBytesHuman: string
  /** 任务当前状态，与 ScanTaskInfo.status 同义 */
  state: ScanTaskInfo['status']
  /** 失败原因；非失败时为 null */
  error: string | null
}

/** 对应后端 GET /scan/stream 推送的进度事件（progress / end），描述任务整体进展 */
export interface ScanProgress {
  /** 任务唯一标识，用于在任务列表里定位到要原地刷新的那一行 */
  task_id: string
  /** 被扫描的文件夹绝对路径 */
  path: string
  /** 任务当前状态，与 ScanTaskInfo.status 同义 */
  state: ScanTaskInfo['status']
  /** 已扫描到的文件数量 */
  scanned: number
  /** 已扫描文件的总字节数（原始值） */
  total_bytes: number
  /** 总字节数的人类可读文本，如 '1.2 GB' */
  total_bytes_human: string
  /** 被跳过的文件/目录数量 */
  skipped: number
  /** 已耗时秒数 */
  elapsed: number
  /** 失败原因；非失败时为 null */
  error: string | null
}

/**
 * 对应后端 GET /scan/pages:分页查询扫描任务历史
 *
 * @param pageSize 每页条数，默认 10
 * @param pageNum 页码，从 1 开始，默认第 1 页
 */
export function scan_logs(pageSize = 10, pageNum = 1): Promise<Page<ScanTaskInfo>> {
  return get<Page<ScanTaskInfo>>('/scan/pages', { page_size: pageSize, page_num: pageNum })
}

/**
 * 对应后端 POST /scan/start:发起扫描，返回 task_id
 *
 * @param path 要扫描的文件夹绝对路径（来自桌面端原生选择框）
 * @returns 后端新建的 task_id，前端拿它去订阅 SSE 和拼结果页地址
 */
export async function scan_start(path:string): Promise<string> {
  return post<string>('/scan/start', { path: path })
}

/**
 * 对应后端 GET /scan/stream:订阅任务进度(SSE)，返回可供 EventSource 使用的完整地址
 *
 * @param taskId 要订阅的任务 id
 */
export function scan_stream_url(taskId: string): string {
  return buildUrl(`/scan/stream?task_id=${encodeURIComponent(taskId)}`)
}

/**
 * 对应后端 GET /scan/files/stream:订阅扫描到的文件(SSE，增量推送)，返回可供 EventSource 使用的完整地址
 *
 * @param taskId 要订阅的任务 id
 * @param fromIndex 从全量结果的第几条开始推，默认 0；断线重连时传已收到的条数即可续传
 */
export function scan_files_stream_url(taskId: string, fromIndex = 0): string {
  return buildUrl(
    `/scan/files/stream?task_id=${encodeURIComponent(taskId)}&from_index=${fromIndex}`,
  )
}

/** 对应后端 POST /rag/documents 返回的入库结果 */
export interface IndexResult {
  /** 文档在库里的自增 id */
  doc_id: number
  /** 入库来源（这里是本地文件绝对路径） */
  source: string
  /** 本次入库动作：created=新建，updated=有变化重新入库，skipped=内容未变直接跳过 */
  action: 'created' | 'updated' | 'skipped'
  /** 该文档当前在库里的切片总数 */
  total_chunks: number
  /** 本次新写入的切片数；skipped 时为 0 */
  new_chunks: number
}

/**
 * 对应后端 POST /rag/documents:将本地文件按路径入库(切片 + 向量化)
 *
 * @param path 文件绝对路径（文件夹或不支持的类型后端会报错）
 * @returns 入库结果，含动作与切片数量，可用于提示「新增/更新/跳过」
 */
export function upload_file(path: string): Promise<IndexResult> {
  return post<IndexResult>('/rag/documents', { path: path })
}

/** 对应后端 GET /rag/documents:已导入文档历史(一条即一个入库过的文件) */
export interface DocumentInfo {
  /** 文档在库里的自增 id，删除/勾选对话范围时用 */
  id: number
  /** 展示用文件名 */
  name: string
  /** 文件来源绝对路径 */
  source: string
  /** 文件字节数（原始值，展示前需格式化） */
  file_size: number
  /** 首次导入时间（UTC，SQLite CURRENT_TIMESTAMP，展示前要补 Z 转本地时区） */
  created_at: string
  /** 最近一次重新入库时间（UTC，同上） */
  updated_at: string
  /** 该文档在库里的切片（chunk）数量，反映检索粒度 */
  chunks: number
}

/**
 * 对应后端 GET /rag/documents:分页查询已导入文档
 *
 * 不传 limit：每页多少条由后端契约表决定（默认 50、上限 200），
 * 前端只负责翻页（offset）。
 *
 * @param offset 跳过的条数，默认 0
 */
export function list_documents(offset = 0): Promise<DocumentInfo[]> {
  return get<DocumentInfo[]>('/rag/documents', { offset })
}

/**
 * 对应后端 DELETE /rag/documents/{doc_id}:移除导入历史
 *
 * @param docId 要移除的文档 id
 * @returns deleted=实际被删掉的记录数（0 表示该 id 已不存在）
 */
export function delete_document(docId: number): Promise<{ deleted: number }> {
  return del<{ deleted: number }>(`/rag/documents/${docId}`)
}

/**
 * 对应后端 POST /rag/documents/batch-delete:批量清空导入历史
 *
 * @param ids 要批量删除的文档 id 数组
 * @returns deleted=实际被删掉的记录数
 */
export function batch_delete_documents(ids: number[]): Promise<{ deleted: number }> {
  return post<{ deleted: number }>('/rag/documents/batch-delete', { ids })
}

/**
 * 保存工作空间文件夹地址（覆盖式）
 * @param path 文件夹地址数组
 */
export function save_workspace(path: string[]): Promise<string[]> {
  return put<string[]>('/settings/workspace', { paths: path })
}
