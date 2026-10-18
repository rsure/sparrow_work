/**
 * services/http.ts 的单元测试 —— 验证「后端地址到底是怎么拼出来的」。
 *
 * 为什么要测它：所有 services/*.ts 的请求都经过 buildUrl，地址一旦拼错，
 * 在浏览器里只表现为一条红色网络请求（404 / 被 vite 代理拦掉），很难一眼看出是拼接问题。
 * 而这段逻辑又高度依赖运行环境（浏览器 dev / Electron 注入端口 / 打包后 file://），
 * 恰恰是「改完在一种环境下好了、另一种环境挂了」的典型地带。
 */
// Vitest：describe 分组、it 单个用例、expect 断言、vi 提供环境变量打桩与模块重载
import { afterEach, describe, expect, it, vi } from 'vitest'
// 项目配置：后端默认端口，用于验证「打包后 file:// 直连哪个端口」的兜底逻辑
import { API_PORT } from '@/config'

/**
 * 加载一份「全新的」http 模块。
 *
 * 为什么必须重新加载：API_BASE_URL 是模块加载时算好并缓存的常量。
 * 用例改完 import.meta.env 或 window.desktop 之后，只有重新 import 才能看到新结果。
 *
 * @returns 重新加载后的模块命名空间
 */
async function loadHttpModule(): Promise<typeof import('@/services/http')> {
  vi.resetModules()
  return import('@/services/http')
}

/**
 * 构造一个完整的 Electron 注入接口替身（window.desktop）。
 *
 * @param apiPort 后端实际监听端口，是本函数唯一需要变化的字段
 * @returns 满足 DesktopApi 类型的对象
 */
function makeDesktop(apiPort: number): DesktopApi {
  return {
    // 标识「跑在桌面壳里」
    isDesktop: true,
    // 平台：测试里固定 Windows，对地址拼接没有影响
    platform: 'win32',
    // 后端端口：这才是被测代码真正读取的字段
    apiPort,
    // 运行时版本号：仅展示用，给占位值即可
    versions: { electron: '33.0.0', chrome: '130.0.0', node: '20.0.0' },
    // 选文件夹能力：测试用不到，返回「用户取消」
    selectFolder: async () => null,
    // 在文件管理器中定位：测试用不到，空实现
    showItemInFolder: async () => {},
    // 用系统程序打开：测试用不到，返回空串表示成功
    openPath: async () => '',
    // 应用版本号：测试用不到，给个固定值
    getAppVersion: async () => '0.1.0',
    // 自动更新能力：测试用不到，全部给空实现（onState 返回一个取消函数）
    updates: {
      getState: async () => ({ status: 'idle', version: null, percent: 0, message: '', checked_at: null }),
      check: async () => ({ status: 'idle', version: null, percent: 0, message: '', checked_at: null }),
      install: async () => {},
      onState: () => () => {},
    },
  }
}

/** 把 window.desktop 换成指定替身，模拟 Electron 环境 */
function stubDesktop(apiPort: number): void {
  window.desktop = makeDesktop(apiPort)
}

// 每个用例都会改环境变量 / 全局对象 / window.desktop，结束后必须全部还原
afterEach(() => {
  // 还原 vi.stubEnv 改过的环境变量
  vi.unstubAllEnvs()
  // 还原 vi.stubGlobal 顶掉的全局对象（例如用例里替换掉的 window）
  vi.unstubAllGlobals()
  // 还原注入的桌面接口
  delete window.desktop
})

describe('API 地址拼接', () => {
  it('浏览器开发态：基地址为空串，请求走 vite 代理的相对路径', async () => {
    const http = await loadHttpModule()

    // 没有显式配置、没有 Electron 注入端口 → 基地址是空串
    expect(http.API_BASE_URL).toBe('')
    // /api 前缀是固定的，与后端注册路由时的前缀保持一致
    expect(http.API_PREFIX).toBe('/api')
    // 带不带前导斜杠都应该拼出同一个地址
    expect(http.buildUrl('health')).toBe('/api/health')
    expect(http.buildUrl('/health')).toBe('/api/health')
  })

  it('路径为空串时也不会拼出非法地址', async () => {
    const http = await loadHttpModule()

    // 补前导斜杠后只剩 /api/，虽然没什么用，但至少不会拼成 /api
    expect(http.buildUrl('')).toBe('/api/')
  })

  it('接口路径里的查询串原样保留', async () => {
    const http = await loadHttpModule()

    // buildUrl 只负责前缀，不解析、不改写调用方给的查询参数
    expect(http.buildUrl('/scan/pages?page=1&size=20')).toBe('/api/scan/pages?page=1&size=20')
  })

  it('VITE_API_BASE_URL 优先级最高，且高于 Electron 注入端口', async () => {
    // 同时设置两种来源，验证「构建期显式配置」赢过「运行时注入」
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.example.test:9000')
    stubDesktop(8123)

    const http = await loadHttpModule()

    expect(http.API_BASE_URL).toBe('http://api.example.test:9000')
    expect(http.buildUrl('/health')).toBe('http://api.example.test:9000/api/health')
  })

  it('没有显式配置时使用 Electron 注入的 apiPort', async () => {
    stubDesktop(8123)

    const http = await loadHttpModule()

    // 端口必须来自注入值，而不是 config 里的默认 8000（主进程可以用 APP_PORT 覆盖默认端口）
    expect(http.API_BASE_URL).toBe('http://127.0.0.1:8123')
    expect(http.buildUrl('/health')).toBe('http://127.0.0.1:8123/api/health')
  })

  it('file:// 页面且没有注入端口时，兜底直连本机默认端口', async () => {
    // 模拟 Electron 打包后的形态：页面以 file:// 加载，且 preload 没有注入 desktop
    vi.stubGlobal('window', { location: { protocol: 'file:' } })

    const http = await loadHttpModule()

    expect(http.API_BASE_URL).toBe(`http://127.0.0.1:${API_PORT}`)
    expect(http.buildUrl('health')).toBe(`http://127.0.0.1:${API_PORT}/api/health`)
  })
})

/**
 * fetchRawJson 的测试 —— 它是「裸 JSON」接口（/commands、/trace/*）的唯一入口。
 *
 * 为什么要测：这条通路与 services/request.ts 的统一外壳是两套约定，
 * 一旦有人把「非 2xx 抛错」或「地址拼接」写漏，界面上只会表现为一片空白，
 * 而不会像统一外壳那样弹出后端给的错误文案，所以错误必须在这里抛得足够早。
 */
describe('fetchRawJson：裸 JSON 请求', () => {
  it('成功时返回解析后的 JSON，并按 buildUrl 拼接请求地址', async () => {
    const http = await loadHttpModule()
    // 记下调用参数，验证「地址是拼过的、不是调用方原样传的」
    const calls: Array<[string, RequestInit | undefined]> = []
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      calls.push([url, init])
      // 模拟后端 /commands 的真实返回：直接是业务对象，没有 code/message/data 外壳
      return { ok: true, status: 200, json: async () => ({ commands: [{ name: 'help' }] }) }
    })

    const data = await http.fetchRawJson<{ commands: Array<{ name: string }> }>('/commands')

    // 返回值是后端对象本身，没有被额外包一层
    expect(data.commands).toHaveLength(1)
    expect(data.commands[0].name).toBe('help')
    // 浏览器开发态基地址为空串，因此拼成 /api/commands
    expect(calls[0][0]).toBe('/api/commands')
  })

  it('把 init 原样透传给 fetch（方法、请求头都不得被吞掉）', async () => {
    const http = await loadHttpModule()
    // 用一个不会被真正发出的 signal，验证透传即可
    const controller = new AbortController()
    let seen: RequestInit | undefined
    vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
      seen = init
      return { ok: true, status: 200, json: async () => ({}) }
    })

    await http.fetchRawJson('/trace/sessions', {
      method: 'GET',
      headers: { 'X-Test': '1' },
      signal: controller.signal,
    })

    expect(seen?.method).toBe('GET')
    expect(seen?.headers).toEqual({ 'X-Test': '1' })
    expect(seen?.signal).toBe(controller.signal)
  })

  it('HTTP 非 2xx 时抛错，文案里带状态码', async () => {
    const http = await loadHttpModule()
    vi.stubGlobal('fetch', async () => ({
      ok: false,
      status: 500,
      json: async () => ({}),
    }))

    // 直接 expect 抛出对象：rejects.toThrow 比对错误消息，确保界面能展示「HTTP 500」
    await expect(http.fetchRawJson('/commands')).rejects.toThrow('请求失败：HTTP 500')
  })
})
