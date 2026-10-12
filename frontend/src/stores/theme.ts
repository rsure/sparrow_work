/**
 * stores/theme.ts —— 主题状态（UX-2）。
 *
 * 设计要点：
 *   1. **不自己存状态**：主题的权威值在后端设置表（`theme.*`），本 store 只是
 *      "把设置值翻译成 CSS 变量"的派算层。因此顶栏切换、设置页改值、别的窗口改值，
 *      只要走同一个 settings store，界面就会一起变，不会出现两份真相。
 *   2. **system 模式**：只有它需要本地状态（操作系统的偏好），用 matchMedia 监听。
 *   3. **apply() 是唯一写 DOM 的地方**：所有 token 都写到 documentElement.style 上，
 *      组件只读 CSS 变量，不读 store（这样组件样式可以直接写 var(--color-x)，无需引入 JS）。
 */
// Pinia：定义全局 store
import { defineStore } from 'pinia'
// 主题计算：预设合成与类型
import { resolveTokens, THEME_PRESETS } from '@/themes/presets'
// 设置 store：主题值的唯一权威来源，也是写回后端的通道
import { useSettingsStore } from '@/stores/settings'
// 类型：明暗模式与代码高亮主题
import type { ThemeMode } from '@/themes/tokens'
import type { ThemeTokens } from '@/themes/tokens'

/** 从设置 store 里读一个键的当前值，读不到时用默认值（后端不可达 / 尚未加载都不该让主题崩） */
function readSetting<T>(key: string, fallback: T): T {
  const settings = useSettingsStore()
  const value = settings.entries[key]?.value
  return (value === undefined || value === null ? fallback : value) as T
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    /** 操作系统是否偏好深色；仅 `theme.mode=system` 时参与判定 */
    systemDark: false,
    /** 是否已经装好 matchMedia 监听（避免重复注册） */
    watching: false,
  }),

  getters: {
    /** 用户选择的模式：dark / light / system（对应设置键 theme.mode） */
    mode(): ThemeMode {
      const raw = readSetting<string>('theme.mode', 'dark')
      return raw === 'light' || raw === 'system' ? raw : 'dark'
    },
    /** 实际生效的明暗（把 system 解析成 dark/light） */
    resolvedMode(state): 'dark' | 'light' {
      if (this.mode === 'system') return state.systemDark ? 'dark' : 'light'
      return this.mode
    },
    /** 当前是否深色（顶栏图标、代码高亮主题都用它） */
    isDark(): boolean {
      return this.resolvedMode === 'dark'
    },
    /** 预设 id（对应设置键 theme.preset） */
    presetId(): string {
      const id = readSetting<string>('theme.preset', 'slate')
      return THEME_PRESETS[id] ? id : 'slate'
    },
    /** 用户自定义主色（对应 theme.accent）；空串表示不覆盖预设 */
    accent(): string {
      return readSetting<string>('theme.accent', '')
    },
    /** 卡片圆角（px，对应 theme.radius） */
    radius(): number {
      return Number(readSetting<number>('theme.radius', 14)) || 0
    },
    /** 正文字号（px，对应 theme.font_size） */
    fontSize(): number {
      return Number(readSetting<number>('theme.font_size', 14)) || 14
    },
    /** 用户在 JSON 里逐项覆盖的 token（对应 theme.custom） */
    customTokens(): Record<string, string> {
      const raw = readSetting<unknown>('theme.custom', {})
      return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, string>) : {}
    },
    /** 最终 token 表：基础色板 → 预设 → 自定义 → 主色覆盖 */
    tokens(): ThemeTokens {
      const merged = resolveTokens(this.resolvedMode, this.presetId, this.customTokens)
      const accent = this.accent.trim()
      if (accent) {
        // 主色单列一个设置键：用户通常只想换个强调色，不该被迫编辑整段 JSON
        merged['color-primary'] = accent
        merged['color-primary-weak'] = hexToRgba(accent, 0.14) ?? merged['color-primary-weak']
      }
      return merged
    },
    /** 预设列表（供顶栏菜单与设置页展示） */
    presets() {
      return Object.values(THEME_PRESETS)
    },
  },

  actions: {
    /** 初始化：读取系统明暗偏好并开始监听（幂等，重复调用不会重复绑定） */
    init(): void {
      if (typeof window === 'undefined' || !window.matchMedia) return
      const query = window.matchMedia('(prefers-color-scheme: dark)')
      this.systemDark = query.matches
      if (this.watching) return
      query.addEventListener('change', (event) => {
        this.systemDark = event.matches
      })
      this.watching = true
    },

    /**
     * 把当前 token 写到根元素上（全站唯一的 DOM 写入点）。
     *
     * 为什么不写在组件里：主题是全局的，写在根元素上才能覆盖 Vant 弹层
     * （弹层挂在 body 末尾，不在组件树内），否则弹窗会保持旧配色。
     */
    apply(): void {
      const root = document.documentElement
      for (const [key, value] of Object.entries(this.tokens)) {
        root.style.setProperty(`--${key}`, value)
      }
      // 圆角与字号也走变量：组件里写 var(--radius) 就能跟随主题
      root.style.setProperty('--radius', `${this.radius}px`)
      root.style.setProperty('--font-size', `${this.fontSize}px`)
      // color-scheme 决定滚动条与原生表单控件的明暗，必须跟着主题走
      root.style.setProperty('color-scheme', this.resolvedMode)
      // 代码高亮需要知道"现在是深色还是浅色"来选配色（见 styles/main.css 的 .hljs-* 规则）
      root.dataset.theme = this.resolvedMode
      root.dataset.preset = this.presetId
    },

    /** 切换明暗：把 system 落到显式的 dark/light，方便用户"一键定下来" */
    async toggleMode(): Promise<void> {
      const settings = useSettingsStore()
      const next = this.isDark ? 'light' : 'dark'
      await settings.saveOne('theme.mode', next)
    },

    /** 设置明暗模式（dark / light / system） */
    async setMode(mode: ThemeMode): Promise<void> {
      await useSettingsStore().saveOne('theme.mode', mode)
    },

    /** 切换配色预设 */
    async setPreset(presetId: string): Promise<void> {
      await useSettingsStore().saveOne('theme.preset', presetId)
    },
  },
})

/**
 * 把 `#rrggbb` 转成带透明度的 rgba 字符串（主色的弱化底需要它）。
 *
 * @param hex 形如 "#38bdf8" 或 "#38bdf8ff" 的颜色
 * @param alpha 透明度（0~1）
 * @returns rgba(...)；颜色格式不认识时返回 null，调用方沿用预设值
 */
function hexToRgba(hex: string, alpha: number): string | null {
  const match = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(hex.trim())
  if (!match) return null
  const int = Number.parseInt(match[1], 16)
  const r = (int >> 16) & 255
  const g = (int >> 8) & 255
  const b = int & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
