/**
 * composables/useTheme.ts —— 把主题 store 接到应用生命周期上（UX-2）。
 *
 * 职责边界：
 *   - `stores/theme.ts` 负责"算出该用哪些颜色"；
 *   - 本 composable 负责"什么时候把颜色写到 DOM 上"（挂载时立即应用、设置变更时重新应用）。
 *
 * 为什么不用 CSS 里的 prefers-color-scheme 直接搞定：
 *   用户可以在设置里显式选深/浅，优先级必须高于系统偏好；只有 `system` 时才跟随系统。
 *   这种"三态"语义 CSS 表达不了，必须由 JS 参与判定。
 */
// Vue：watch 监听 token 变化，onMounted/onBeforeUnmount 管理监听器生命周期
import { onBeforeUnmount, onMounted, watch } from 'vue'
// 主题 store：token 的派算层
import { useThemeStore } from '@/stores/theme'

/**
 * 安装主题：组件挂载后立即应用一次，之后 token 变化就重新应用。
 *
 * 在 `AppShell` 里调用一次即可（全站只需要一个写入点）。
 *
 * @returns 主题 store 实例，调用方可直接读 isDark / presets / 调 toggleMode
 */
export function useTheme() {
  const theme = useThemeStore()

  // token 是 computed 出来的对象，每次变化都会生成新引用；deep 比对避免"内容没变也重写 DOM"
  const stop = watch(
    () => [theme.tokens, theme.radius, theme.fontSize],
    () => theme.apply(),
    { deep: true },
  )

  onMounted(() => {
    // 先读系统明暗（system 模式要用），再应用一次，避免首屏闪一下默认色
    theme.init()
    theme.apply()
  })

  onBeforeUnmount(stop)

  return theme
}
