/**
 * services/memory.ts 里「整理记忆 / 重建向量」两个维护接口的单元测试（MEM 增强）。
 *
 * 为什么单测这两个函数：
 *   它们是整条记忆链路里唯一"由用户手动触发、且会真的删数据/重算数据"的入口。
 *   请求体字段（workspace_id / force）写错不会有任何报错——后端会用默认值照样执行，
 *   于是"我以为在重建整个工作区"和"其实只重建了当前工作区"就混过去了。
 *   所以这里把 URL 与请求体逐字钉住。
 */
// Vitest：describe/it/expect 断言，vi 用来替换全局 fetch，type Mock 给假 fetch 标类型
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
// 被测对象：整理 / 重建向量
import { pruneMemories, reindexMemories } from '@/services/memory'

/** fetch 替身的类型：既当 fetch 用，又带 mock.calls 调用记录供断言 */
type FetchStub = Mock<(url: string, init?: RequestInit) => Promise<unknown>>

/**
 * 用假 fetch 顶掉全局 fetch。
 *
 * @param impl 假 fetch 的实现；需要模拟失败时返回 ok=false 的响应
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
 * @param options ok 默认 true、status 默认 200；失败用例改这两个
 * @returns 能当 Response 用的对象
 */
function jsonResponse(body: unknown, options: { ok?: boolean; status?: number } = {}): Response {
  const { ok = true, status = 200 } = options
  return { ok, status, json: async () => body } as unknown as Response
}

/** 每个用例结束后恢复全局 fetch，避免影响其它测试文件（同进程共享全局） */
afterEach(() => vi.unstubAllGlobals())

describe('pruneMemories', () => {
  it('不传工作区时显式发 workspace_id: null（让后端按当前工作区整理）', async () => {
    const body = {
      workspace_id: '',
      removed: 3,
      removed_expired: 2,
      removed_overflow: 1,
      total: 12,
    }
    const stub = installFetch(async () => jsonResponse(body))

    const result = await pruneMemories()

    expect(result).toEqual(body)
    expect(stub.mock.calls[0][0]).toBe('/api/memory/prune')
    expect(stub.mock.calls[0][1]?.method).toBe('POST')
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({ workspace_id: null })
  })

  it('指定工作区时把 id 放进请求体', async () => {
    const stub = installFetch(async () =>
      jsonResponse({
        workspace_id: 'w1',
        removed: 0,
        removed_expired: 0,
        removed_overflow: 0,
        total: 0,
      }),
    )

    await pruneMemories('w1')

    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({ workspace_id: 'w1' })
  })
})

describe('reindexMemories', () => {
  it('默认只补缺失/维度不符的向量（force=false）', async () => {
    const body = {
      workspace_id: 'w1',
      total: 10,
      updated: 4,
      skipped: 6,
      dim: 512,
      embedding: 'local',
    }
    const stub = installFetch(async () => jsonResponse(body))

    const result = await reindexMemories('w1')

    expect(result).toEqual(body)
    expect(stub.mock.calls[0][0]).toBe('/api/memory/reindex')
    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({
      workspace_id: 'w1',
      force: false,
    })
  })

  it('force=true 时把标志一起发出去（全量重算）', async () => {
    const stub = installFetch(async () =>
      jsonResponse({
        workspace_id: '',
        total: 2,
        updated: 2,
        skipped: 0,
        dim: 1536,
        embedding: 'remote:text-embedding-3-small',
      }),
    )

    await reindexMemories(undefined, true)

    expect(JSON.parse(String(stub.mock.calls[0][1]?.body))).toEqual({
      workspace_id: null,
      force: true,
    })
  })

  it('后端报错时抛出带状态码的 Error（上层好提示「重建失败」）', async () => {
    installFetch(async () => jsonResponse({}, { ok: false, status: 500 }))

    await expect(reindexMemories()).rejects.toThrow('HTTP 500')
  })
})
