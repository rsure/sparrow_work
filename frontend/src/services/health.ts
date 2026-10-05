import { request } from './request' // 通用请求封装：这里用它发 GET 并自动解开 { code, message, data } 外壳
import type { HealthData } from './types' // 健康检查返回体的类型定义，作为 fetchHealth 的返回值类型

/**
 * 调用后端 controller：GET /api/health。
 * 场景：首页「检查健康状态」按钮，用来确认本地后端（Java 或 Python）是否已启动、
 * 版本与环境是否符合预期。
 *
 * @returns 后端健康快照；后端不可达或业务码非 0 时抛出 ApiError
 */
export function fetchHealth(): Promise<HealthData> {
  return request<HealthData>('/health')
}
