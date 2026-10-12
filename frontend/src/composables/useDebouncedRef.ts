// composables/useDebouncedRef.ts
/**
 * 模块说明：提供一个「防抖 ref」——写入后要等 delay 毫秒才真正生效。
 * 典型场景是搜索框：用户每敲一个字就更新 ref，但只有停顿下来之后才触发过滤/请求，避免频繁计算。
 * 注意它是「延迟生效」而不是「延迟执行回调」：读取时拿到的仍是旧值，到期后才变成新值。
 */
// Vue 响应式工具：customRef 让我们自己掌控依赖收集(track)与派发更新(trigger)的时机；
// onScopeDispose 在所在组件/作用域销毁时执行清理，防止定时器泄漏
import { customRef, onScopeDispose } from 'vue'

/** 防抖 ref：写入后 delay 毫秒才真正生效。用于搜索框。 */
export function useDebouncedRef<T>(initial: T, delay = 200) {
  // 当前挂起的定时器句柄；undefined 表示没有待生效的写入
  let timer: ReturnType<typeof setTimeout> | undefined
  // 真正被读到的值：只有定时器到期才会被替换成最新写入值
  let value = initial

  // 作用域销毁（组件卸载）时清掉未到期的定时器，避免回调在组件已销毁后触发更新
  onScopeDispose(() => {
    if (timer !== undefined) clearTimeout(timer)
  })

  // customRef 接收 track/trigger 两个回调：get 里调 track 建立依赖，set 里调 trigger 通知刷新
  return customRef<T>((track, trigger) => ({
    /** 读取时收集依赖并返回「已生效」的旧值（新值可能还在防抖窗口里） */
    get() {
      track()
      return value
    },
    /** 写入时不立即生效：先取消上一个待生效任务，再 delay 毫秒后落值并触发依赖更新 */
    set(newValue: T) {
      if (timer !== undefined) clearTimeout(timer)
      timer = setTimeout(() => {
        value = newValue
        trigger()
      }, delay)
    },
  }))
}
