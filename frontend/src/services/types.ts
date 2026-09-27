/** 健康检查数据类型，对应后端 app/schemas/health.py 的 HealthData */
export interface HealthData {
  /** 健康状态：ok=一切正常；degraded=服务降级（还能响应，但有依赖不可用） */
  status: 'ok' | 'degraded'
  /** 服务名，用来确认当前连接的是哪个后端进程 */
  service: string
  /** 后端服务版本号（如 '0.1.0'），排查问题时用于对齐前后端版本 */
  version: string
  /** 运行环境：development=开发态，production=生产态 */
  env: string
  /** 兼容字段：Python 后端返回解释器版本；Java 后端返回 'N/A' */
  python_version: string
  /** 后端运行的操作系统平台，如 'Windows' / 'Linux' / 'Darwin' */
  platform: string
  /** 后端进程本次已运行的秒数（单位：秒，由后端单调时钟计算，只增不减） */
  uptime_seconds: number
  /** 后端当前服务器时间，ISO 8601 字符串（是字符串不是 Date，展示前需自行格式化） */
  server_time: string
  /** 运行时类型：Java / Python；旧后端可能不返回该字段 */
  runtime?: string
  /** 运行时版本，如 '17.0.20.1' 或 '3.12.4'；旧后端可能不返回该字段 */
  runtime_version?: string
}
