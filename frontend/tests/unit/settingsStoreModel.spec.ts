/**
 * stores/settings.ts 里 selectModel 的单元测试：选模型 + 必要时自动登记自定义模型。
 *
 * 为什么要单测它：
 *   1. 这是「用户手写一个清单里还没有的模型名」唯一能走通的路径。内置供应商的后端只接受
 *      预置清单里的名字（会报错，而不是静默换成别的模型），所以漏掉 llm.custom_models 这一笔，
 *      用户在对话页选完模型、一发消息才失败——现场很难看出是登记漏了。
 *   2. 反过来，重复登记会让设置页的「自定义模型」列表越积越长，同样是静默的坏结果。
 *   两个方向都不会抛错，只会在用户那边表现成「怎么又不行了」，所以这里把请求体逐字钉住。
 */
// Vitest：describe/it/expect 断言，vi 用来替换全局 fetch，type Mock 给假 fetch 标类型
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
// Pinia：每个用例换一个干净的 store 实例，避免用例之间互相看到对方的设置值
import { createPinia, setActivePinia } from 'pinia'
// 被测对象：默认窗口常量 + 设置 store
import { DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW, useSettingsStore } from '@/stores/settings'

/** fetch 替身的类型：既当 fetch 用，又带 mock.calls 调用记录供断言 */
type FetchStub = Mock<(url: string, init?: RequestInit) => Promise<unknown>>

/**
 * 用假 fetch 顶掉全局 fetch。
 *
 * @param impl 假 fetch 的实现；默认返回「保存成功」的响应
 * @returns 假 fetch，供用例断言「请求长什么样」
 */
function installFetch(impl: (url: string, init?: RequestInit) => Promise<unknown>): FetchStub {
  const stub = vi.fn(impl)
  vi.stubGlobal('fetch', stub)
  return stub
}

/**
 * 造一个 PUT /api/settings 的成功响应：后端回的是「保存后全部设置项的当前值」。
 *
 * @param values 响应里的键值表（store 会整体替换 this.values）
 * @returns 能当 Response 用的对象（被测代码只用到 ok / status / json）
 */
function savedResponse(values: Record<string, unknown>): Response {
  return { ok: true, status: 200, json: async () => ({ values }) } as unknown as Response
}

/**
 * 取出假 fetch 第一次调用里发出去的请求体，并解析成 { values: {...} }。
 *
 * @param stub 假 fetch
 * @returns 请求体；用例断言「哪些键被一起写下去」时用它
 */
function firstPatch(stub: FetchStub): Record<string, unknown> {
  const body = stub.mock.calls[0]?.[1]?.body
  return (JSON.parse(String(body)) as { values: Record<string, unknown> }).values
}

beforeEach(() => {
  // 每个用例一个全新 store，state 不会从上一个用例漏过来
  setActivePinia(createPinia())
})

afterEach(() => {
  // 全局 fetch 是同进程共享的，用例结束必须还原
  vi.unstubAllGlobals()
})

describe('selectModel', () => {
  it('清单里已有的模型：只写供应商和模型名，不碰自定义模型', async () => {
    const stub = installFetch(async () => savedResponse({
      'llm.provider': 'deepseek',
      'llm.model': 'deepseek-flash',
    }))
    const store = useSettingsStore()

    const result = await store.selectModel('deepseek', 'deepseek-flash', ['deepseek-flash', 'deepseek-v4-pro'], false)

    expect(result).toEqual({ registered: false })
    expect(stub.mock.calls[0][0]).toBe('/api/settings')
    expect(stub.mock.calls[0][1]?.method).toBe('PUT')
    // 没有多余键：多写一个 llm.custom_models 就会把用户手写的清单整体覆盖掉
    expect(firstPatch(stub)).toEqual({ 'llm.provider': 'deepseek', 'llm.model': 'deepseek-flash' })
  })

  it('清单外的模型名（内置供应商）：追加一条自定义模型，窗口用保守默认值', async () => {
    const stub = installFetch(async () => savedResponse({ 'llm.provider': 'deepseek' }))
    const store = useSettingsStore()

    const result = await store.selectModel('deepseek', 'deepseek-flash-1017', ['deepseek-flash'], false)

    expect(result).toEqual({ registered: true })
    const patch = firstPatch(stub)
    expect(patch['llm.model']).toBe('deepseek-flash-1017')
    expect(patch['llm.custom_models']).toEqual([
      {
        provider: 'deepseek',
        model: 'deepseek-flash-1017',
        label: 'deepseek-flash-1017',
        context_window: DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW,
        supports_tools: true,
      },
    ])
  })

  it('已经登记过的同名模型：不重复追加，保留用户自己填的窗口与单价', async () => {
    const existing = {
      provider: 'deepseek',
      model: 'deepseek-flash-1017',
      label: '我的 Flash',
      context_window: 1_000_000,
      price_in: 2,
      price_out: 8,
    }
    const stub = installFetch(async () => savedResponse({ 'llm.provider': 'deepseek' }))
    const store = useSettingsStore()
    // 模拟设置里此前已经登记过这一条
    store.$patch({ values: { 'llm.custom_models': [existing] } })

    const result = await store.selectModel('deepseek', 'deepseek-flash-1017', [], false)

    expect(result).toEqual({ registered: false })
    expect(firstPatch(stub)).toEqual({
      'llm.provider': 'deepseek',
      'llm.model': 'deepseek-flash-1017',
    })
  })

  it('自定义端点：后端本来就接受任意模型名，不需要登记', async () => {
    const stub = installFetch(async () => savedResponse({ 'llm.provider': 'custom-myapi' }))
    const store = useSettingsStore()

    const result = await store.selectModel('custom-myapi', 'whatever-v9', [], true)

    expect(result).toEqual({ registered: false })
    expect(firstPatch(stub)).toEqual({ 'llm.provider': 'custom-myapi', 'llm.model': 'whatever-v9' })
  })

  it('模型名是空白：一个键都不写（半套配置比不改更危险）', async () => {
    const stub = installFetch(async () => savedResponse({}))
    const store = useSettingsStore()

    const result = await store.selectModel('deepseek', '   ', [], false)

    expect(result).toEqual({ registered: false })
    expect(stub).not.toHaveBeenCalled()
  })
})
