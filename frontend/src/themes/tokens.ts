/**
 * themes/tokens.ts —— 主题 token 的类型定义与基础色板（UX-2）。
 *
 * 为什么要有这一层：
 *   改造前颜色散落在 `styles/main.css` 与各组件里，换个主题要改几十处。
 *   现在把"界面需要的语义色"收敛成一组 token，组件只写 `var(--color-text)` 这类语义名，
 *   具体色值由主题层在运行时写到 `document.documentElement.style` 上。
 *
 * 命名约定（重要）：
 *   token 名**不带** `--` 前缀（如 `color-bg`），写 CSS 变量时才拼成 `--color-bg`。
 *   这样 token 对象可以直接当普通字典遍历，不用到处做字符串裁剪。
 */

/** 主题 token 集合：键是语义名，值是 CSS 颜色/尺寸字符串 */
export interface ThemeTokens {
  /** 页面底色（最底层背景） */
  'color-bg': string
  /** 页面顶部的柔光色（径向渐变的圆心色），让纯色背景有层次 */
  'color-bg-glow': string
  /** 卡片/面板背景色 */
  'color-surface': string
  /** 二级背景（输入框、代码块外层、hover 态） */
  'color-surface-2': string
  /** 描边色：卡片、分割线、输入框边框 */
  'color-border': string
  /** 正文文字色 */
  'color-text': string
  /** 次要文字色（说明、占位、禁用态） */
  'color-text-muted': string
  /** 主题色（主按钮、链接、选中态） */
  'color-primary': string
  /** 主题色上的文字色（保证按钮文字与主色有足够对比度） */
  'color-on-primary': string
  /** 主题色的弱化底（选中行背景、焦点环），通常带透明度 */
  'color-primary-weak': string
  /** 成功色（健康、完成） */
  'color-success': string
  /** 危险色（报错、删除） */
  'color-danger': string
  /** 警告色（等待确认、熔断提示） */
  'color-warning': string
  /** 代码块背景 */
  'code-bg': string
  /** 代码块描边 */
  'code-border': string
}

/** 深色基础色板：所有深色预设都从这里起步，只覆盖差异项 */
export const BASE_DARK: ThemeTokens = {
  'color-bg': '#0b1120',
  'color-bg-glow': '#1e293b',
  'color-surface': '#111827',
  'color-surface-2': '#1f2937',
  'color-border': '#273449',
  'color-text': '#e5e7eb',
  'color-text-muted': '#94a3b8',
  'color-primary': '#38bdf8',
  'color-on-primary': '#04121f',
  'color-primary-weak': 'rgba(56, 189, 248, 0.12)',
  'color-success': '#34d399',
  'color-danger': '#f87171',
  'color-warning': '#fbbf24',
  'code-bg': '#0d1526',
  'code-border': '#22304a',
}

/** 浅色基础色板：白底 + 深灰字，保证同一套组件在浅色下依然可读 */
export const BASE_LIGHT: ThemeTokens = {
  'color-bg': '#f6f7fb',
  'color-bg-glow': '#ffffff',
  'color-surface': '#ffffff',
  'color-surface-2': '#f1f3f8',
  'color-border': '#dde2ec',
  'color-text': '#1f2430',
  'color-text-muted': '#65708a',
  'color-primary': '#0f7bd4',
  'color-on-primary': '#ffffff',
  'color-primary-weak': 'rgba(15, 123, 212, 0.12)',
  'color-success': '#0f9d58',
  'color-danger': '#d93025',
  'color-warning': '#b26a00',
  'code-bg': '#f7f8fb',
  'code-border': '#e1e6ef',
}

/** 代码高亮主题的可选值（与后端 `theme.code_theme` 的 options 保持一致） */
export type CodeTheme = 'auto' | 'github-dark' | 'github'

/** 主题模式的可选值（与后端 `theme.mode` 的 options 保持一致） */
export type ThemeMode = 'dark' | 'light' | 'system'
