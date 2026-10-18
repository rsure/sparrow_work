/**
 * services/chat.ts 里「执行中插话 / 取消工具」两个端点的单元测试（ARCH-6）。
 *
 * 为什么单独测这两个函数：
 *   它们是前端唯一"用 HTTP 控制正在跑的 Agent"的入口，失败原因是**给人看的**
 *   （开关关了、没有活跃流、工具已经在跑）。如果错误路径写成"请求失败：HTTP 400"，
 *   用户只知道坏了、不知道为什么——所以这里逐条钉住后端 detail 是否被透出。
 */
// Vitest：describe/it/expect 断言，vi 用来替换全局 fetch，type Mock 给假 fetch 标类型
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
// 被测对象：插话与取消工具；以及它们返回体的字段名（后端改名时这里会先红）
import { cancel_tool, steer_chat } from '@/services/chat'

/** fetch 替身的类型：既当 fetch 用，又带 mock.calls 调用记录供断言 */
type FetchStub = Mock<(url: string, init?: RequestInit) => Promise<unknown>>

/**
 * 用假 fetch 顶掉全局 fetch。
 *
 * @param impl 假 fetch 的实现；需要模拟失败时直接返回 ok=false 的响应
 * @returns 假 fetch，供用例断言"请求长什么样"
 */
function installFetch(impl: (url: string, init?: RequestInit) => Promise<unknown>): FetchStub {
  const stub = vi.fn(impl)
  vi.stubGlobal('fetch', stub)
  return stub
}

/**
 * 造一个 JSON 响应替身：被测代码只用到 ok / status / json 三样。
 *
 * @param body 响应体（json() 原样返回）
 * @param options ok 默认 true、status 默认 200；4xx/5xx 用例改这两个
 * @returns 能当 Response 用的对象
 */
function jsonResponse(body: unknown, options: { ok?: boolean; status?: number } = {}): Response {
  const { ok = true, status = 200 } = options
  return { ok, status, json: async () => body } as unknown as Response
}

/** 每个用例结束后恢复全局 fetch，避免影响其它测试文件（同进程共享全局） */
afterEach(() => vi.unstubAllGlobals())

describe('steer_chat', () => {
  it('把正文发给 /chat/{id}/steer，并返回排队条数', async () => {
    const stub = installFetch(async () =>
      jsonResponse({
        session_id: 'abc',
        steer_id: 'steer-1',
        content: '只改 src 目录',
        queued: true,
        pending: 2,
      }),
    )

    const result = await steer_chat('abc', '只改 src 目录')

    expect(result.pending).toBe(2)
    expect(result.steer_id).toBe('steer-1')
    const [url, init] = stub.mock.calls[0]
    expect(String(url)).toContain('/chat/abc/steer')
    expect(init?.method).toBe('POST')
    // 正文必须原样放在请求体里：插话是"用户原话"，任何转换都会让模型读错
    expect(JSON.parse(String(init?.body))).toEqual({ content: '只改 src 目录' })
  })

  it('会话 id 会被 URL 编码：id 里出现斜杠也不会把路径拼坏', async () => {
    const stub = installFetch(async () => jsonResponse({ session_id: 'a/b', steer_id: 's', content: 'x', queued: true, pending: 1 }))

    await steer_chat('a/b', 'x')

    // 未编码时会变成 /chat/a/b/steer，后端会把它当成另一个会话
    expect(String(stub.mock.calls[0][0])).toContain('/chat/a%2Fb/steer')
  })

  it('失败时把后端的 detail 当异常信息抛出来，而不是只说 HTTP 400', async () => {
    installFetch(async () => jsonResponse({ detail: '插话功能已在设置里关闭（agent.steering_enabled）' }, { ok: false, status: 400 }))

    // 用 rejects 断言：文案要能被用户读懂，这也是 store 里直接 showToast 的内容
    await expect(steer_chat('abc', '你好')).rejects.toThrow('agent.steering_enabled')
  })

  it('后端没给 detail 时退回状态码文案（不能抛 undefined）', async () => {
    installFetch(async () => jsonResponse({}, { ok: false, status: 409 }))

    await expect(steer_chat('abc', '你好')).rejects.toThrow('HTTP 409')
  })

  it('响应体不是 JSON 时也不掩盖真实错误', async () => {
    // 例如网关返回了一段 HTML：json() 会抛错，但用户该看到的是 HTTP 状态
    installFetch(async () => ({ ok: false, status: 502, json: async () => { throw new Error('bad json') } }) as unknown as Response)

    await expect(steer_chat('abc', '你好')).rejects.toThrow('HTTP 502')
  })
})

describe('cancel_tool', () => {
  it('带上工具名调用 /chat/{id}/tool-cancel', async () => {
    const stub = installFetch(async () =>
      jsonResponse({ session_id: 'abc', cancelled: true, tool: 'write_file' }),
    )

    const result = await cancel_tool('abc', 'write_file')

    expect(result.cancelled).toBe(true)
    const [url, init] = stub.mock.calls[0]
    expect(String(url)).toContain('/chat/abc/tool-cancel')
    expect(JSON.parse(String(init?.body))).toEqual({ tool: 'write_file' })
  })

  it('不传工具名时发空串：后端据此取消"下一个工具"，不管它是什么', async () => {
    const stub = installFetch(async () =>
      jsonResponse({ session_id: 'abc', cancelled: true, tool: '(下一个工具)' }),
    )

    await cancel_tool('abc')

    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({ tool: '' })
  })

  it('工具已经跑起来时，把后端的拒绝原因原样交给调用方', async () => {
    installFetch(async () =>
      jsonResponse(
        { detail: '工具 run_command 已经开始执行，无法中途取消；如需立即结束请点「终止」' },
        { ok: false, status: 409 },
      ),
    )

    await expect(cancel_tool('abc', 'run_command')).rejects.toThrow('无法中途取消')
  })
})
