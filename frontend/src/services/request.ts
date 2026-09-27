import { buildUrl } from './http' // 只负责拼地址：本模块所有请求（含流式）都经它得到后端完整 URL

/** 统一响应外壳，对应后端 app/schemas/common.py 的 ApiResponse */
export interface ApiResponse<T> {
  /** 业务状态码：0=成功；非 0 为业务失败，会被 request 转成 ApiError 抛出 */
  code: number
  /** 后端给的提示文案，失败时可直接展示给用户 */
  message: string
  /** 真正的业务数据；失败时为 null */
  data: T | null
}

/** 请求异常：把 HTTP 错误与业务错误统一成一种异常 */
export class ApiError extends Error {
  /** HTTP 状态码，如 404/500；请求根本没发出去（连不上后端）时为 undefined */
  readonly status?: number
  /** 后端业务状态码；在 HTTP 层就失败时为 undefined，用来区分「网络错」和「业务错」 */
  readonly code?: number

  /**
   * @param message 面向用户的错误说明
   * @param options status=HTTP 状态码，code=业务状态码，两者都可缺省
   */
  constructor(message: string, options: { status?: number; code?: number } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
  }
}

/**
 * 极简请求封装：解析 { code, message, data } 外壳。
 * 业务变复杂后可以换成 axios，调用方签名保持不变。
 *
 * @param path 接口路径（不含 /api 前缀），如 '/health'
 * @param init fetch 的第二个参数，可覆盖 method / headers / body / signal 等
 * @returns 外壳里的 data 字段；连不上后端、HTTP 非 2xx、业务码非 0 三种情况都会抛 ApiError
 */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = buildUrl(path)
  let response: Response

  try {
    // 默认声明接受 JSON，调用方传入的 headers 优先级更高（放在展开的 init 之前）
    response = await fetch(url, {
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
      ...init,
    })
  } catch (error) {
    // fetch 本身抛错说明请求没发出去：后端没启动或端口不通
    throw new ApiError(`无法连接后端服务：${String(error)}`)
  }

  if (!response.ok) {
    // HTTP 层失败：后端返回了 4xx/5xx，此时响应体不保证是统一外壳，不再解析
    throw new ApiError(`请求失败：HTTP ${response.status}`, { status: response.status })
  }

  // HTTP 成功，还要再看业务码：code 非 0 表示业务处理失败
  const body = (await response.json()) as ApiResponse<T>
  if (body.code !== 0) {
    throw new ApiError(body.message || '业务处理失败', { code: body.code })
  }
  return body.data as T
}

/**
 * GET 请求：query 对象自动拼接到 URL，undefined/null 值会被忽略。
 * 场景：读取型接口，如分页查询扫描历史、拉取已导入文档列表。
 *
 * @param path 接口路径，如 '/scan/pages'
 * @param query 查询参数键值对；值为 undefined/null 的键不会出现在 URL 上
 * @param init 其它 fetch 配置（例如 signal 用于中途取消请求）
 */
export function get<T>(
  path: string,
  query?: Record<string, string | number | boolean | undefined | null>,
  init: RequestInit = {},
): Promise<T> {
  let fullPath = path
  if (query) {
    // URLSearchParams 会自动做 URL 编码，避免文件名/路径里的特殊字符破坏地址
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params.append(key, String(value))
    }
    const qs = params.toString()
    // path 里已有 '?' 时用 '&' 接续，否则用 '?' 起头
    if (qs) fullPath = `${path}${path.includes('?') ? '&' : '?'}${qs}`
  }
  return request<T>(fullPath, { ...init, method: 'GET' })
}

/**
 * POST 请求：body 对象自动 JSON.stringify，并补上 Content-Type。
 * 场景：有副作用的写操作，如发起扫描、文档入库、批量删除。
 *
 * @param path 接口路径，如 '/scan/start'
 * @param body 要发送的对象（undefined 表示不带请求体）
 * @param init 其它 fetch 配置
 */
export function post<T>(path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  return request<T>(path, {
    ...init,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

/** PUT 请求：body 对象自动 JSON.stringify，并补上 Content-Type（用于覆盖式更新，如设置工作区） */
export function put<T>(path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  return request<T>(path, {
    ...init,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

/** DELETE 请求：用于删除资源（如移除已导入文档） */
export function del<T>(path: string, init: RequestInit = {}): Promise<T> {
  return request<T>(path, { ...init, method: 'DELETE' })
}

/**
 * SSE 流式请求：按 text/event-stream 规范读取事件帧，逐个回调 onEvent。
 *
 * 帧格式（以空行分隔，后端 app/controllers/chat_controller.py 的 _sse 生成）::
 *
 *     event: token
 *     data: {"text":"你","trace_id":"ab12","ts":1760000000.1}
 *
 * 与 NDJSON 的差别在于一帧有「事件名」，且可跨多行；所以这里以空行（\n\n）
 * 而不是换行符切分，再把 event: / data: 两类字段分别取出。
 * 多条 data: 行按规范用 \n 拼接后再整体 JSON.parse。
 *
 * @param path 接口路径，如 '/chat/stream'
 * @param onEvent 每解析出一帧就回调一次，参数为 (事件名, data 反序列化后的对象)
 * @param init 其它 fetch 配置；method/headers/body 由调用方给全（会被展开覆盖默认值）
 */
export async function sse(
  path: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  init: RequestInit = {},
): Promise<void> {
  const url = buildUrl(path)
  let response: Response

  try {
    // 默认声明接受 SSE 流；调用方传入的 headers 优先级更高
    response = await fetch(url, {
      ...init,
      headers: { Accept: 'text/event-stream', ...(init.headers ?? {}) },
    })
  } catch (error) {
    throw new ApiError(`无法连接后端服务：${String(error)}`)
  }

  if (!response.ok) {
    throw new ApiError(`请求失败：HTTP ${response.status}`, { status: response.status })
  }
  if (!response.body) {
    throw new ApiError('响应不包含可读流')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  // 帧缓冲区：网络分片可能把一帧切成两半，必须攒到空行才算一帧完整
  let buffer = ''

  /** 解析单帧文本（不含分隔空行），取出事件名与 data 负载后回调 */
  const dispatch = (raw: string): void => {
    let event = 'message' // SSE 规范：省略 event: 时默认事件名为 message
    const dataLines: string[] = []
    for (const line of raw.split('\n')) {
      if (line.startsWith(':')) continue // 注释行（常用作心跳），忽略
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (dataLines.length === 0) return // 只有注释/心跳的帧，没有负载
    const payload = dataLines.join('\n')
    try {
      onEvent(event, JSON.parse(payload) as Record<string, unknown>)
    } catch {
      // 后端偶发写出非 JSON 负载时不要打断整条流，按纯文本透传
      onEvent(event, { raw: payload })
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // stream: true 让解码器保留跨分片的半个多字节字符
      buffer += decoder.decode(value, { stream: true })
      // 兼容 \r\n：统一成 \n 后再按空行切帧
      buffer = buffer.replace(/\r\n/g, '\n')
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        if (frame.trim()) dispatch(frame)
      }
    }

    // 流结束但缓冲区仍剩最后一帧（末尾缺空行）时的兜底处理
    if (buffer.trim()) dispatch(buffer)
  } finally {
    // 无论正常结束还是中途抛错，都释放 reader，避免连接悬挂
    reader.releaseLock?.()
  }
}

/**
 * 流式请求：按行读取 NDJSON（每行一个 JSON 对象），逐条回调 onMessage。
 * 收到某条消息 complete === true 时结束读取（并 cancel 掉底层 reader）。
 * 传入 signal 可用于外部中途取消。
 *
 * @param path 接口路径，如 '/chat/stream'
 * @param onMessage 每解析出一行就回调一次，由调用方决定如何渲染
 * @param init 其它 fetch 配置；method/headers/body 由调用方给全（会被展开覆盖默认值）
 */
export async function stream<T extends { complete?: boolean }>(
  path: string,
  onMessage: (data: T) => void,
  init: RequestInit = {},
): Promise<void> {
  const url = buildUrl(path)
  let response: Response

  try {
    // 默认声明接受 NDJSON 流
    response = await fetch(url, {
      headers: { Accept: 'application/x-ndjson', ...(init.headers ?? {}) },
      ...init,
    })
  } catch (error) {
    throw new ApiError(`无法连接后端服务：${String(error)}`)
  }

  if (!response.ok) {
    throw new ApiError(`请求失败：HTTP ${response.status}`, { status: response.status })
  }
  if (!response.body) {
    // 理论上现代浏览器都有 body；保险起见给出明确错误，避免下面空指针
    throw new ApiError('响应不包含可读流')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  // 行缓冲区：网络分片可能把一行 JSON 切成两半，必须攒够换行符才能解析
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // stream: true 让解码器保留跨分片的半个多字节字符
      buffer += decoder.decode(value, { stream: true })
      let newlineIndex: number
      // 一次可能收到多行，循环把缓冲区里所有完整行都消费掉
      while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newlineIndex).trim()
        buffer = buffer.slice(newlineIndex + 1)
        if (!line) continue // 跳过心跳/空行

        const data = JSON.parse(line) as T
        onMessage(data)
        if (data.complete) {
          // 后端已标记结束：主动取消底层流，不再等待连接关闭
          await reader.cancel()
          return
        }
      }
    }

    // 流结束但仍剩最后一行（末尾没有换行符）时的兜底处理
    const last = buffer.trim()
    if (last) {
      const data = JSON.parse(last) as T
      onMessage(data)
    }
  } finally {
    // 无论正常结束还是中途抛错，都释放 reader，避免连接悬挂
    reader.releaseLock?.()
  }
}
