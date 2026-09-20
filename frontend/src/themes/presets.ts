/**
 * themes/presets.ts —— 内置主题预设（UX-2）。
 *
 * 一个预设 = 一组"在基础色板上做少量覆盖"的配色。
 * 这样新增主题只需要写几条差异色，不必把 14 个 token 全部抄一遍。
 *
 * 与后端的关系：
 *   用户选中的预设 id 存在设置键 `theme.preset`（见 backend/app/services/ui_settings_defs.py）；
 *   前端不缓存用户选择，每次都从设置值推导，避免"设置页改了、顶栏没跟上"。
 */
// 类型：基础色板与 token 类型
import { BASE_DARK, BASE_LIGHT, type ThemeTokens } from './tokens'

/** 单个主题预设的定义 */
export interface ThemePreset {
  /** 预设 id：写进设置键 `theme.preset` 的值 */
  id: string
  /** 展示名（顶栏主题菜单与设置页下拉里显示） */
  label: string
  /** 一句话说明（让人知道这个预设适合什么场景） */
  description: string
  /** 深色模式下覆盖的 token（未列出的沿用 BASE_DARK） */
  dark?: Partial<ThemeTokens>
  /** 浅色模式下覆盖的 token（未列出的沿用 BASE_LIGHT） */
  light?: Partial<ThemeTokens>
}

/** 全部预设置：键是 id，顺序即展示顺序 */
export const THEME_PRESETS: Record<string, ThemePreset> = {
  slate: {
    id: 'slate',
    label: '蓝灰',
    description: '默认配色：深蓝底 + 亮蓝主色，长时间阅读不刺眼',
  },
  midnight: {
    id: 'midnight',
    label: '午夜',
    description: '更深的底色与偏紫的主色，适合夜间',
    dark: {
      'color-bg': '#07070d',
      'color-bg-glow': '#1b1b2f',
      'color-surface': '#101020',
      'color-surface-2': '#1a1a2e',
      'color-border': '#2a2a44',
      'color-primary': '#a78bfa',
      'color-primary-weak': 'rgba(167, 139, 250, 0.14)',
      'code-bg': '#0b0b16',
      'code-border': '#25253d',
    },
    light: {
      'color-primary': '#6d4dd6',
      'color-primary-weak': 'rgba(109, 77, 214, 0.12)',
    },
  },
  paper: {
    id: 'paper',
    label: '纸白',
    description: '暖白纸感，适合白天与投影环境',
    dark: {
      'color-bg': '#14120f',
      'color-bg-glow': '#2a251d',
      'color-surface': '#1c1915',
      'color-surface-2': '#272219',
      'color-border': '#3a3327',
      'color-primary': '#d9a441',
      'color-primary-weak': 'rgba(217, 164, 65, 0.14)',
      'code-bg': '#12100d',
      'code-border': '#302a20',
    },
    light: {
      'color-bg': '#fbf8f2',
      'color-bg-glow': '#ffffff',
      'color-surface': '#fffdf8',
      'color-surface-2': '#f4efe4',
      'color-border': '#e5ddcc',
      'color-primary': '#a8701a',
      'color-primary-weak': 'rgba(168, 112, 26, 0.12)',
      'code-bg': '#f8f4ea',
      'code-border': '#e8dfcd',
    },
  },
  nord: {
    id: 'nord',
    label: '北欧',
    description: '低饱和冷色，接近北欧极简风',
    dark: {
      'color-bg': '#2e3440',
      'color-bg-glow': '#3b4252',
      'color-surface': '#333a47',
      'color-surface-2': '#3b4252',
      'color-border': '#4c566a',
      'color-primary': '#88c0d0',
      'color-primary-weak': 'rgba(136, 192, 208, 0.14)',
      'code-bg': '#2b313c',
      'code-border': '#434c5e',
    },
    light: {
      'color-bg': '#eceff4',
      'color-bg-glow': '#ffffff',
      'color-surface': '#ffffff',
      'color-surface-2': '#e5e9f0',
      'color-border': '#d8dee9',
      'color-primary': '#5e81ac',
      'color-primary-weak': 'rgba(94, 129, 172, 0.12)',
      'code-bg': '#f2f4f8',
      'code-border': '#dde3ec',
    },
  },
}

/** 预设 id 列表（按展示顺序），设置页与顶栏菜单都用它 */
export const PRESET_IDS: string[] = Object.keys(THEME_PRESETS)

/**
 * 合成最终 token：基础色板 → 预设覆盖 → 用户自定义覆盖。
 *
 * 为什么是这个顺序：越靠后优先级越高。`theme.custom` 是高级逃生口，
 * 用户想覆盖任何一项都能盖住预设（但主色仍会被 `theme.accent` 再盖一次，见 useTheme）。
 *
 * @param mode 解析后的明暗模式（system 必须已经在调用前解析成 dark/light）
 * @param presetId 预设 id；不存在时回落到 slate
 * @param custom 用户自定义 token 覆盖（键可以带 `--` 前缀，也可以不带）
 * @returns 完整的 token 表
 */
export function resolveTokens(
  mode: 'dark' | 'light',
  presetId: string,
  custom: Record<string, string> = {},
): ThemeTokens {
  const base = mode === 'dark' ? BASE_DARK : BASE_LIGHT
  const preset = THEME_PRESETS[presetId] ?? THEME_PRESETS.slate
  const presetLayer = (mode === 'dark' ? preset.dark : preset.light) ?? {}
  const merged: ThemeTokens = { ...base, ...presetLayer }

  // 自定义覆盖：允许用户写成 "--color-bg" 或 "color-bg" 两种键，统一去掉前缀再合并
  for (const [rawKey, value] of Object.entries(custom ?? {})) {
    const key = rawKey.startsWith('--') ? rawKey.slice(2) : rawKey
    if (key in merged && typeof value === 'string') {
      merged[key as keyof ThemeTokens] = value
    }
  }
  return merged
}
