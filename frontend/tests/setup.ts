/**
 * 测试环境准备文件 —— vitest.config.ts 的 setupFiles 指向它，每个测试文件运行前都会先执行。
 *
 * 为什么需要它：
 *   项目真实运行在浏览器 / Electron 里，可以随便用 matchMedia、ResizeObserver 这些浏览器 API；
 *   而 jsdom 只实现了 DOM 规范的一部分，上面这些是缺的。缺了之后被测代码往往在某个角落抛一个
 *   TypeError，报错信息还指不到根因。所以在这里**一次性**补齐，而不是让每个测试文件各写一遍。
 *
 * 原则：只在缺失时补，绝不覆盖 jsdom 已有的真实实现 —— 否则测试就不再反映真实行为了。
 */
// Node 内置的文本编解码器：jsdom 不提供 TextEncoder/TextDecoder，而流式解析（request.ts 的 sse/stream）要用
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'node:util'

/**
 * 把一个可能缺失的全局属性补齐（已存在就原样保留）。
 *
 * 为什么要同时写到 window 和 globalThis：jsdom 环境里 `window` 与 `globalThis` 并不是同一个对象，
 * 被测代码有的写 `window.matchMedia(...)`、有的直接写全局的 `TextDecoder`，两边都补才都覆盖得到。
 *
 * @param name 全局属性名，如 'ResizeObserver'
 * @param value 缺失时要安装的实现
 */
function installGlobalIfMissing(name: string, value: unknown): void {
  /** 需要检查/安装的目标对象：浏览器侧的 window（jsdom 提供）加上 Node 侧的 globalThis */
  const targets: object[] = [globalThis]
  if (typeof window !== 'undefined' && (window as unknown as object) !== globalThis) targets.push(window)
  for (const target of targets) {
    const holder = target as unknown as Record<string, unknown>
    if (holder[name] !== undefined) continue
    // 用 defineProperty 而不是直接赋值：部分全局属性在 jsdom 里是只读的访问器
    Object.defineProperty(target, name, { value, configurable: true, writable: true })
  }
}

/**
 * 造一个最小可用的 matchMedia 返回值。
 *
 * 为什么需要：jsdom 没实现 window.matchMedia，而 Vant 的若干组件（以及系统深色模式判断）
 * 挂载时会调用它；只要没有就会直接抛错，测试完全跑不起来。
 *
 * @param query 媒体查询字符串，如 '(prefers-color-scheme: dark)'
 * @returns 只实现了「测试用得到的成员」的 MediaQueryList
 */
function createMatchMedia(query: string): MediaQueryList {
  /** 简化的媒体查询对象：matches 一律为 false（jsdom 无法真正计算媒体查询） */
  const mql = {
    /** 是否匹配：统一给 false，代表「默认亮色、非移动端」 */
    matches: false,
    /** 原始查询串，原样存下方便断言 */
    media: query,
    /** onchange 回调占位，被测代码可以赋值 */
    onchange: null,
    /** 新增监听器（ES2015 写法）：测试里不需要真的回调，空实现 */
    addEventListener: (): void => {},
    /** 移除监听器 */
    removeEventListener: (): void => {},
    /** 旧式新增监听器（Safari 老版本 API），保留以免被测代码用之时报错 */
    addListener: (): void => {},
    /** 旧式移除监听器 */
    removeListener: (): void => {},
    /** 事件派发占位：默认返回 false 表示没有取消默认行为 */
    dispatchEvent: (): boolean => false,
  }
  // 类型断言的原因：上面的对象只实现了 MediaQueryList 的一部分成员，而且没有 EventTarget 的完整接口
  return mql as unknown as MediaQueryList
}

/**
 * 最小可用的 ResizeObserver 替身。
 *
 * 为什么需要：Vant 的 List / Popover 之类组件在挂载时会 `new ResizeObserver(...)`，
 * jsdom 没有这个构造器，组件挂载会直接失败。测试里不需要真的监听尺寸变化，空实现足够。
 */
class ResizeObserverStub {
  /** 开始观察某个元素（收集但什么都不做） */
  observe(): void {}

  /** 停止观察某个元素 */
  unobserve(): void {}

  /** 断开全部观察 */
  disconnect(): void {}
}

// 文本编解码：流式解析拿到的二进制分片要靠它还原成字符串
installGlobalIfMissing('TextEncoder', NodeTextEncoder)
installGlobalIfMissing('TextDecoder', NodeTextDecoder)
// 媒体查询：系统明暗偏好判断会用到
installGlobalIfMissing('matchMedia', createMatchMedia)
// 尺寸监听：Vant 的弹出层 / 列表组件会用到
installGlobalIfMissing('ResizeObserver', ResizeObserverStub)

// jsdom 没有实现 scrollIntoView，而弹出层定位常常调用它；补一个空实现避免挂载时报错
if (typeof Element.prototype.scrollIntoView !== 'function') {
  /** 让元素滚动到可视区域：测试里不需要真的滚动，空实现即可 */
  Element.prototype.scrollIntoView = function scrollIntoView(): void {}
}
