/**
 * 后端地址解析（优先级从高到低）：
 * 1. `VITE_API_BASE_URL` —— 显式配置，构建时注入
 * 2. `window.desktop.apiPort` —— Electron preload 注入的真实端口（主进程可用 APP_PORT 覆盖）
 * 3. 运行在 `file://`（Electron 打包后）—— 直连本机默认端口
 * 4. 其它（浏览器 dev/preview）—— 使用相对路径 /api，交给 vite 代理
 */
import { API_PORT } from '@/config' // 全局配置：后端默认端口，打包后 file:// 直连时作为兜底端口

// 当前页面是否以 file:// 协议加载（Electron 打包后的形态）：是则没有同源代理，只能绝对地址直连后端
const isFileProtocol = typeof window !== 'undefined' && window.location.protocol === 'file:'

/**
 * 按「构建期配置 → Electron 注入端口 → file:// 兜底端口 → 相对路径」的优先级推算后端基地址。
 * 只在模块加载时执行一次，结果缓存到下面的 API_BASE_URL。
 */
function resolveApiBaseUrl(): string {
  // 最高优先级：构建时注入的显式地址，通常用于连接非本机后端
  const configured = import.meta.env.VITE_API_BASE_URL?.trim()
  if (configured) return configured

  // 次优先级：Electron preload 注入的真实端口（主进程可能用 APP_PORT 覆盖默认值）
  const injectedPort = typeof window !== 'undefined' ? window.desktop?.apiPort : undefined
  if (injectedPort) return `http://127.0.0.1:${injectedPort}`

  // 兜底：打包后 file:// 页面直连本机默认端口；浏览器环境返回空串，走 vite 代理的相对路径请求
  return isFileProtocol ? `http://127.0.0.1:${API_PORT}` : ''
}

// 后端服务基地址（不含 /api 前缀）。浏览器开发态为空串，表示所有请求都走同源相对路径
export const API_BASE_URL: string = resolveApiBaseUrl()

// 所有接口的统一前缀，与后端注册路由时使用的 /api 前缀保持一致
export const API_PREFIX = '/api'

/**
 * 拼接完整接口地址：把「基地址 + /api 前缀 + 接口路径」组装成可直接请求的 URL。
 *
 * @param path 接口路径，带不带前导 `/` 都行（如 `'health'` 或 `'/health'`）
 * @returns 形如 `http://127.0.0.1:8000/api/health` 的完整地址，可交给 fetch / EventSource 使用
 */
export function buildUrl(path: string): string {
  // 统一补上前导斜杠，避免调用方传来的 'health' 拼出 '/apihealth'
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${API_PREFIX}${normalized}`
}

/**
 * 发一个"裸 JSON"请求：后端直接返回业务对象、不套 { code, message, data } 外壳时用它。
 *
 * 项目里有两类接口风格：走 `services/request.ts` 的统一外壳（多数 /api/*），
 * 以及直接返回裸 JSON 的「Agent 运行时」接口（/chat/*、/trace/*、/commands ——
 * 它们的数据形状每次都不一样，硬套外壳反而多一层）。本函数服务后者。
 *
 * @param path 接口路径（不含 /api 前缀），如 '/commands'
 * @param init 额外 fetch 配置（method / headers / body / signal）
 * @returns 后端返回的裸 JSON，调用方自己声明期望类型 T
 * @throws Error HTTP 非 2xx 时抛错，文案里带状态码，便于界面上直接展示
 */
export async function fetchRawJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(buildUrl(path), init)
  if (!res.ok) throw new Error(`请求失败：HTTP ${res.status}`)
  return (await res.json()) as T
}
