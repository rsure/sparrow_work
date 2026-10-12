import { get } from './request' // 通用请求封装：GET 查列表，自动解开统一响应外壳

/** 一条审计记录，对应后端 GET /api/audit 返回的元素（app/entity/audit_log.py） */
export interface AuditLogEntry {
  /** 记录主键 */
  id: number
  /** 所属会话 id */
  session_id: string
  /** 工具名，如 file_ops / run_command / write_file */
  tool: string
  /** 操作类型：read / write / exec / net */
  kind: string
  /** 目标描述（文件路径、命令行、URL） */
  target: string
  /** 动作说明（确认弹窗里那段话） */
  detail: string
  /** 裁决等级：allow / ask / deny */
  level: string
  /** 用户选择：approved / rejected / none */
  decision: string
  /** 执行结果：ok / fail / skipped */
  outcome: string
  /** 工具返回文本摘要（截断保存） */
  output_digest: string
  /** 记录时间（后端已格式化为 'YYYY-MM-DD HH:MM:SS'） */
  created_at: string
}

/**
 * 查询工具调用审计记录（按时间倒序）。
 *
 * @param params 可选过滤：session_id 只看某个会话、tool 只看某个工具、limit 最多返回多少条
 */
export function fetch_audit_logs(params?: {
  session_id?: string
  tool?: string
  limit?: number
}): Promise<AuditLogEntry[]> {
  // 显式声明成 Record，避免把可选字段对象直接塞给 get() 时触发索引签名缺失的报错
  const query: Record<string, string | number | undefined> = {
    session_id: params?.session_id,
    tool: params?.tool,
    limit: params?.limit,
  }
  return get<AuditLogEntry[]>('/audit', query)
}
