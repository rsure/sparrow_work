/**
 * services/request.ts 的单元测试 —— 四种调用方式（JSON / SSE / NDJSON / 增删改）+ 三类失败路径。
 *
 * 为什么最值得先测这里：
 *   1. 它是整个前端访问后端的唯一出口，任何一处判断写错，所有页面一起坏；
 *   2. 流式解析（sse / stream）的价值全在「网络分片切在半个字段中间」时还能正确还原，
 *      而这种情况在真实网络里偶发、极难复现 —— 用可控的假分片正好能稳定覆盖；
 *   3. 这里的「失败」有四种（连不上、HTTP 非 2xx、业务码非 0、响应没有可读流），
 *      它们在 UI 上表现不同，必须逐条钉住，否则会把「后端没启动」显示成「参数不合法」。
 */
// Vitest：describe/it/expect 断言，vi 用来替换全局 fetch 与控制定时器，type Mock 给假 fetch 标类型
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
// 被测对象：统一请求出口。request/get/post/put/del 是普通 JSON 请求，sse/stream 是两种流式协议
import { ApiError, del, get, post, put, request, sse, stream } from '@/services/request'

/** fetch 替身的类型：既能当成 fetch 用，又带 mock.calls 调用记录供断言 */
type FetchStub = Mock<(url: string, init?: RequestInit) => Promise<unknown>>

/** 测试用的 NDJSON 消息结构：只声明用例里会读到的字段，其余字段用索引签名兜住 */
interface TestMessage {
  /** 流式返回的文本增量 */
  text?: string
  /** 后端标记「本轮结束」：收到它就该停止读取 */
  complete?: boolean
  /** 用例不关心、但后端可能带上的其它字段 */
  [key: string]: unknown
}

/**
 * 用一个假 fetch 顶掉全局 fetch。
 *
 * @param impl 假 fetch 的实现（返回假响应，或直接拒绝以模拟「后端没启动」）
 * @returns 这个假 fetch，供用例断言「请求长什么样」
 */
function installFetch(impl: (url: string, init?: RequestInit) => Promise<unknown>): FetchStub {
  const stub = vi.fn(impl)
  // 替换全局 fetch：被测代码内部调用的是全局 fetch，替换后就会打到我们这里
  vi.stubGlobal('fetch', stub)
  return stub
}

/**
 * 造一个 JSON 响应替身。request 只用到 ok / status / json 三样，不必造真的 Response。
 *
 * @param body 响应体（会被 json() 原样返回）
 * @param options ok 默认 true，status 默认 200；用例要模拟 5xx 时改这两个
 * @returns 能当 Response 用的对象
 */
function jsonResponse(body: unknown, options: { ok?: boolean; status?: number } = {}): Response {
  const { ok = true, status = 200 } = options
  // 断言成 Response：这里只实现被测代码用到的成员，不是完整的 Response
  return { ok, status, json: async () => body } as unknown as Response
}

/**
 * 造一个带「可读流」的响应替身，用来测 sse / stream 的分片解析。
 *
 * @param chunks 依次读出的分片；字符串会按 UTF-8 编码，传 Uint8Array 可以精确控制切字节的位置
 * @param options ok/status 控制失败路径；withBody=false 用来模拟「响应没有 body」
 * @returns response 假响应；cancelCalls 读取底层的 cancel 被调用了几次（验证流的提前终止）
 */
function streamResponse(
  chunks: Array<string | Uint8Array>,
  options: { ok?: boolean; status?: number; withBody?: boolean } = {},
): { response: Response; cancelCalls: () => number } {
  const { ok = true, status = 200, withBody = true } = options
  // 编码器：把字符串分片转成字节，模拟网络上真正传的东西
  const encoder = new TextEncoder()
  /** 待读分片队列：read() 每次弹一个，弹空后再 read() 就返回 done */
  const queue = chunks.map((chunk) => (typeof chunk === 'string' ? encoder.encode(chunk) : chunk))
  /** 被测代码主动取消流时会被调用（stream 收到 complete 就取消） */
  const cancel = vi.fn(async () => {})
  /** 释放 reader 的锁（被测代码在 finally 里调用） */
  const releaseLock = vi.fn()
  /** 假的可读流：只要实现 getReader().read() 这一套就够被测代码用了 */
  const body = withBody
    ? {
        getReader: () => ({
          read: async () =>
            queue.length > 0
              ? { done: false, value: queue.shift() as Uint8Array }
              : { done: true, value: undefined },
          cancel,
          releaseLock,
        }),
      }
    : null
  return { response: { ok, status, body } as unknown as Response, cancelCalls: () => cancel.mock.calls.length }
}

/**
 * 执行一个「应当失败」的请求，把异常取回来断言。
 *
 * 为什么不用 rejects.toThrow：这次要断言的是自定义字段（code / status 的有无），
 * 取到异常对象再逐项检查，比方法链更直白。
 *
 * @param promise 预期会抛错的请求
 * @returns 捕获到的 ApiError
 */
async function catchError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    return error as ApiError
  }
  throw new Error('预期这次请求会抛错，但它成功了')
}

/**
 * 取出某次 fetch 调用的请求头（统一成普通对象便于断言）。
 *
 * @param stub 假 fetch
 * @param callIndex 第几次调用（默认第一次）
 * @returns 请求头键值对
 */
function headersOf(stub: FetchStub, callIndex = 0): Record<string, string> {
  const init = stub.mock.calls[callIndex]?.[1]
  return (init?.headers ?? {}) as Record<string, string>
}

// 每个用例都会替换全局 fetch，结束后必须还原，否则会影响下一个用例与其它测试文件
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request：普通 JSON 请求', () => {
  it('业务码为 0 时返回外壳里的 data', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: { status: 'ok' } }))

    const data = await request<{ status: string }>('/health')

    expect(data).toEqual({ status: 'ok' })
    // 地址要经过 buildUrl：所以第一段一定是 /api
    expect(stub.mock.calls[0]?.[0]).toBe('/api/health')
    // 默认声明「要 JSON」
    expect(headersOf(stub)).toEqual({ Accept: 'application/json' })
  })

  it('调用方显式传入的请求头优先级高于默认值', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await request('/health', { headers: { Accept: 'text/plain' } })

    // 默认的 Accept 被调用方覆盖，而不是两者共存
    expect(headersOf(stub).Accept).toBe('text/plain')
  })

  it('业务码非 0 时抛 ApiError，并带上后端的 code 与 message', async () => {
    installFetch(async () => jsonResponse({ code: 1001, message: '参数不合法', data: null }))

    const error = await catchError(request('/scan/start'))

    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('参数不合法')
    expect(error.code).toBe(1001)
    // HTTP 是通的，所以没有 HTTP 状态码
    expect(error.status).toBeUndefined()
  })

  it('业务码非 0 且后端没给 message 时用兜底文案', async () => {
    installFetch(async () => jsonResponse({ code: 500, message: '', data: null }))

    const error = await catchError(request('/scan/start'))

    expect(error.message).toBe('业务处理失败')
    expect(error.code).toBe(500)
  })

  it('HTTP 非 2xx 时抛 ApiError 并带上 status', async () => {
    installFetch(async () => jsonResponse({ detail: 'boom' }, { ok: false, status: 500 }))

    const error = await catchError(request('/scan/start'))

    expect(error.message).toBe('请求失败：HTTP 500')
    expect(error.status).toBe(500)
    // HTTP 层就失败了，拿不到业务码
    expect(error.code).toBeUndefined()
  })

  it('fetch 本身抛错（后端没启动）时给出可读提示', async () => {
    installFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    const error = await catchError(request('/health'))

    // 文案要能让用户看懂「是后端没起来」，而不是一串英文
    expect(error.message).toContain('无法连接后端服务')
    // 原始错误信息保留在文案里，方便排查
    expect(error.message).toContain('Failed to fetch')
    expect(error.status).toBeUndefined()
  })
})

describe('get：查询参数拼接', () => {
  it('把 query 拼到地址上，并跳过 undefined / null', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: [] }))

    await get('/scan/pages', { page: 1, size: 20, keyword: '目录 a/b', skipped: undefined, empty: null })

    // URLSearchParams 会把空格编码成 +、斜杠编码成 %2F，中文按 UTF-8 百分号编码
    expect(stub.mock.calls[0]?.[0]).toBe('/api/scan/pages?page=1&size=20&keyword=%E7%9B%AE%E5%BD%95+a%2Fb')
    expect(stub.mock.calls[0]?.[1]?.method).toBe('GET')
  })

  it('路径里已经有 ? 时用 & 接续', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await get('/scan/pages?root=D%3A%2Fdocs', { page: 2 })

    expect(stub.mock.calls[0]?.[0]).toBe('/api/scan/pages?root=D%3A%2Fdocs&page=2')
  })

  it('query 全是 undefined / null 时地址上不出现问号', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await get('/scan/pages', { page: undefined, size: null })

    expect(stub.mock.calls[0]?.[0]).toBe('/api/scan/pages')
  })
})

describe('post / put / del：写操作', () => {
  it('post 补上 Content-Type 并把对象序列化成 JSON 字符串', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await post('/scan/start', { path: 'D:/docs' })

    const init = stub.mock.calls[0]?.[1]
    expect(init?.method).toBe('POST')
    expect(headersOf(stub)['Content-Type']).toBe('application/json')
    expect(init?.body).toBe(JSON.stringify({ path: 'D:/docs' }))
  })

  it('post 的 body 为 undefined 时不带请求体（但仍声明 JSON）', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await post('/scan/reset')

    expect(stub.mock.calls[0]?.[1]?.body).toBeUndefined()
    expect(headersOf(stub)['Content-Type']).toBe('application/json')
  })

  it('put 用 PUT 方法并序列化请求体', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await put('/settings', { theme: 'dark' })

    expect(stub.mock.calls[0]?.[1]?.method).toBe('PUT')
    expect(stub.mock.calls[0]?.[1]?.body).toBe(JSON.stringify({ theme: 'dark' }))
  })

  it('del 用 DELETE 方法且不带请求体', async () => {
    const stub = installFetch(async () => jsonResponse({ code: 0, message: 'ok', data: null }))

    await del('/file/doc-1')

    expect(stub.mock.calls[0]?.[1]?.method).toBe('DELETE')
    expect(stub.mock.calls[0]?.[1]?.body).toBeUndefined()
  })
})

describe('sse：按事件帧解析文本流', () => {
  it('按空行切帧，逐帧回调事件名与 data', async () => {
    const { response } = streamResponse([
      'event: token\ndata: {"text":"你"}\n\n',
      'event: token\ndata: {"text":"好"}\n\n',
    ])
    const stub = installFetch(async () => response)
    /** 收集每次回调：元素是 [事件名, 反序列化后的数据] */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([
      ['token', { text: '你' }],
      ['token', { text: '好' }],
    ])
    expect(headersOf(stub).Accept).toBe('text/event-stream')
  })

  it('一帧被网络分片切开时也能正确还原（含汉字被切在字节中间）', async () => {
    // 手工切成两块：第一块停在「你」这个三字节汉字的第一个字节之后
    const bytes = new TextEncoder().encode('data: {"text":"你好"}\n\n')
    const { response } = streamResponse([bytes.slice(0, 16), bytes.slice(16)])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    // 说明 TextDecoder 的 stream:true 生效了：解码器会保留半个字符等下一块补齐
    expect(events).toEqual([['message', { text: '你好' }]])
  })

  it('注释行（心跳帧）不产生回调', async () => {
    const { response } = streamResponse([': ping\n\n', 'data: {"text":"续"}\n\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toHaveLength(1)
    expect(events[0]?.[1]).toEqual({ text: '续' })
  })

  it('省略 event: 时事件名默认是 message', async () => {
    const { response } = streamResponse(['data: {"a":1}\n\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([['message', { a: 1 }]])
  })

  it('多条 data 行按 \\n 拼接后再整体解析', async () => {
    // 规范允许把一段 JSON 拆到多个 data: 行里（多行文本常用这种写法）
    const { response } = streamResponse(['data: {"a":\ndata: 1}\n\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([['message', { a: 1 }]])
  })

  it('非 JSON 负载不被吞掉，而是按纯文本透传', async () => {
    const { response } = streamResponse(['data: 你好\n\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([['message', { raw: '你好' }]])
  })

  it('流结束时末尾没有空行，最后一帧也会被处理', async () => {
    const { response } = streamResponse(['data: {"text":"尾"}\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([['message', { text: '尾' }]])
  })

  it('兼容 \\r\\n 换行（Windows 上的代理可能改写换行符）', async () => {
    const { response } = streamResponse(['event: token\r\ndata: {"text":"好"}\r\n\r\n'])
    installFetch(async () => response)
    /** 收到的帧 */
    const events: Array<[string, Record<string, unknown>]> = []

    await sse('/chat/stream', (event, data) => events.push([event, data]))

    expect(events).toEqual([['token', { text: '好' }]])
  })

  it('响应没有可读流时抛 ApiError', async () => {
    const { response } = streamResponse(['data: {"a":1}\n\n'], { withBody: false })
    installFetch(async () => response)

    const error = await catchError(sse('/chat/stream', () => {}))

    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('响应不包含可读流')
  })

  it('HTTP 非 2xx 时在读取流之前就抛错', async () => {
    const { response, cancelCalls } = streamResponse([], { ok: false, status: 502 })
    installFetch(async () => response)

    const error = await catchError(sse('/chat/stream', () => {}))

    expect(error.status).toBe(502)
    // 都没开始读流，自然也不会去 cancel
    expect(cancelCalls()).toBe(0)
  })
})

describe('stream：按行解析 NDJSON 流', () => {
  it('逐行解析并回调，请求头声明 NDJSON', async () => {
    const { response } = streamResponse(['{"text":"你"}\n{"text":"好"}\n'])
    const stub = installFetch(async () => response)
    /** 收到的每行对象 */
    const messages: TestMessage[] = []

    await stream('/chat/stream', (data) => messages.push(data))

    expect(messages).toEqual([{ text: '你' }, { text: '好' }])
    expect(headersOf(stub).Accept).toBe('application/x-ndjson')
  })

  it('收到 complete 后立刻停止读取并取消底层流', async () => {
    // 第三行永远不该被消费：complete 已经表示这一轮结束
    const { response, cancelCalls } = streamResponse([
      '{"text":"你"}\n{"complete":true}\n{"text":"不该出现"}\n',
    ])
    installFetch(async () => response)
    /** 收到的每行对象 */
    const messages: TestMessage[] = []

    await stream('/chat/stream', (data) => messages.push(data))

    expect(messages).toEqual([{ text: '你' }, { complete: true }])
    // 主动 cancel，不等后端关连接
    expect(cancelCalls()).toBe(1)
  })

  it('末尾没有换行符的最后一行也会被解析', async () => {
    const { response } = streamResponse(['{"text":"尾"}'])
    installFetch(async () => response)
    /** 收到的每行对象 */
    const messages: TestMessage[] = []

    await stream('/chat/stream', (data) => messages.push(data))

    expect(messages).toEqual([{ text: '尾' }])
  })

  it('空行与心跳行被跳过', async () => {
    const { response } = streamResponse(['\n\n{"text":"有"}\n\n'])
    installFetch(async () => response)
    /** 收到的每行对象 */
    const messages: TestMessage[] = []

    await stream('/chat/stream', (data) => messages.push(data))

    expect(messages).toEqual([{ text: '有' }])
  })

  it('响应没有可读流时抛 ApiError', async () => {
    const { response } = streamResponse([], { withBody: false })
    installFetch(async () => response)

    const error = await catchError(stream('/chat/stream', () => {}))

    expect(error.message).toBe('响应不包含可读流')
  })

  it('后端写出坏行时抛解析错误（不静默吞掉）', async () => {
    const { response } = streamResponse(['not-json\n'])
    installFetch(async () => response)

    const error = await catchError(stream('/chat/stream', () => {}))

    // 这里刻意断言「会抛错」：坏行说明协议对不上，静默跳过会让界面一直转圈
    expect(error).toBeInstanceOf(SyntaxError)
  })
})
