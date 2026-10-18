/**
 * composables/useDebouncedRef.ts 的单元测试 —— 防抖 ref 的「延迟生效」语义。
 *
 * 为什么重要：搜索框与文件列表过滤都建立在它之上。如果它退化成「写入立刻生效」，
 * 现象是每敲一个字就请求一次接口 / 重排一次上千行列表 —— 卡顿但不会报错，
 * 在验收时极易被放过；反过来，如果它永远不生效，搜索框看起来「没反应」。
 * 所以必须用假定时器把「199ms 还没变、200ms 变了」这个边界钉死。
 */
// Vitest：假定时器 vi.useFakeTimers 让 200ms 的等待在测试里瞬间走完
import { afterEach, describe, expect, it, vi } from 'vitest'
// Vue：effectScope 模拟组件作用域（onScopeDispose 要在这里注册），nextTick 等 watcher 刷新，watch 验证响应式通知
import { effectScope, nextTick, watch, type EffectScope, type Ref } from 'vue'
// 被测对象：防抖 ref
import { useDebouncedRef } from '@/composables/useDebouncedRef'

/** 本文件创建过的所有作用域：用例结束统一停掉，等于模拟组件卸载 */
const scopes: EffectScope[] = []

/**
 * 在独立的 effectScope 里创建防抖 ref。
 *
 * 为什么必须包一层：useDebouncedRef 内部用 onScopeDispose 清理定时器，
 * 没有活跃作用域时会打印告警，而且「作用域销毁」这条路径也就测不到了。
 *
 * @param initial 初始值
 * @param delay 防抖毫秒数，默认与被测实现一致（200）
 * @returns 防抖 ref
 */
function createDebounced<T>(initial: T, delay = 200): Ref<T> {
  /** 每个用例自己的作用域，便于单独销毁 */
  const scope = effectScope()
  scopes.push(scope)
  /** 在作用域内创建，onScopeDispose 的回调才会挂到它上面 */
  const result = scope.run(() => useDebouncedRef(initial, delay))
  if (result === undefined) throw new Error('在 effectScope 里创建防抖 ref 失败')
  return result
}

// 每个用例用假定时器；结束后恢复真实定时器并销毁作用域
afterEach(() => {
  vi.useRealTimers()
  // 停掉作用域，同时触发 composable 里的定时器清理
  for (const scope of scopes.splice(0)) scope.stop()
})

describe('useDebouncedRef', () => {
  it('写入后立刻读到的仍是旧值，delay 到期才变成新值', () => {
    vi.useFakeTimers()
    const value = createDebounced('')

    value.value = '目录'
    // 防抖窗口内：输入框已经显示「目录」，但参与过滤的值还停在旧值
    expect(value.value).toBe('')

    // 差 1ms 到期时也不能变：必须完整等满 delay
    vi.advanceTimersByTime(199)
    expect(value.value).toBe('')

    vi.advanceTimersByTime(1)
    expect(value.value).toBe('目录')
  })

  it('连续多次写入只保留最后一次的值', () => {
    vi.useFakeTimers()
    const value = createDebounced('')

    value.value = 'D'
    value.value = 'D:'
    value.value = 'D:/docs'

    // 每次写入都会重置计时器，所以此刻还什么都没生效
    vi.advanceTimersByTime(199)
    expect(value.value).toBe('')

    vi.advanceTimersByTime(1)
    // 只有最后一个值落下来，中间值全部丢弃（正是搜索框需要的行为）
    expect(value.value).toBe('D:/docs')
  })

  it('delay 可以自定义', () => {
    vi.useFakeTimers()
    const value = createDebounced('', 50)

    value.value = 'x'
    vi.advanceTimersByTime(49)
    expect(value.value).toBe('')

    vi.advanceTimersByTime(1)
    expect(value.value).toBe('x')
  })

  it('作用域销毁后，未到期的写入不会再落值', () => {
    vi.useFakeTimers()
    const value = createDebounced('旧值')

    value.value = '新值'
    // 模拟组件卸载：onScopeDispose 里应当清掉定时器
    scopes.splice(0).forEach((scope) => scope.stop())

    vi.advanceTimersByTime(5000)
    // 定时器被清掉了，所以值永远停在旧值（不会出现「组件已销毁还在更新」）
    expect(value.value).toBe('旧值')
  })

  it('到期后会通知依赖（watch 能收到新值）', async () => {
    vi.useFakeTimers()
    const value = createDebounced('')
    /** 记录 watch 收到的值，验证「真的触发了响应式更新」而不只是内部变量变了 */
    const seen: string[] = []
    watch(value, (next) => seen.push(next))

    value.value = 'abc'
    vi.advanceTimersByTime(199)
    await nextTick()
    // 还没到期：watcher 一次都不该被调用
    expect(seen).toEqual([])

    vi.advanceTimersByTime(1)
    await nextTick()
    expect(seen).toEqual(['abc'])
  })
})
