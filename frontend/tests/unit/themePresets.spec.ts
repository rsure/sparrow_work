/**
 * themes/presets.ts 的单元测试 —— 主题色板的三层合并（基础色板 → 预设覆盖 → 用户自定义）。
 *
 * 为什么重要：主题 token 最终会写成 document.documentElement 上的 CSS 变量。
 * 合并顺序一旦写反（比如先铺预设、再用基础色板盖一遍），界面就会出现
 * 「换了预设但主色没变」或者「自定义色被预设吃掉」——这种问题在浏览器里只能靠肉眼比色，
 * 很容易被当成「设计稿就这样」。所以用单元测试把优先级钉死。
 */
// Vitest：用例组织与断言
import { describe, expect, it } from 'vitest'
// 被测对象：预设清单与合并函数
import { PRESET_IDS, THEME_PRESETS, resolveTokens } from '@/themes/presets'
// 基础色板：用来断言「没有覆盖时的默认值」以及「合并不改写基础对象」
import { BASE_DARK, BASE_LIGHT, type ThemeTokens } from '@/themes/tokens'

describe('预设清单', () => {
  it('PRESET_IDS 的顺序与预设定义一致（设置页按这个顺序渲染）', () => {
    expect(PRESET_IDS).toEqual(['slate', 'midnight', 'paper', 'nord'])
    // 每个 id 都必须能在 THEME_PRESETS 里找到定义，否则设置页会渲染出空选项
    for (const id of PRESET_IDS) expect(THEME_PRESETS[id]).toBeDefined()
  })
})

describe('resolveTokens：三层合并', () => {
  it('slate 不含任何覆盖，深色下就等于基础深色色板', () => {
    expect(resolveTokens('dark', 'slate')).toEqual(BASE_DARK)
  })

  it('浅色模式从基础浅色色板起步', () => {
    expect(resolveTokens('light', 'slate')).toEqual(BASE_LIGHT)
  })

  it('未知预设 id 回落到 slate，而不是抛错或返回空对象', () => {
    // 设置项可能来自后端（用户手改过配置文件），拼错也必须能正常渲染
    expect(resolveTokens('dark', '不存在的预设')).toEqual(BASE_DARK)
  })

  it('每个预设声明的覆盖项都真的写进了结果', () => {
    for (const id of PRESET_IDS) {
      const preset = THEME_PRESETS[id]
      for (const mode of ['dark', 'light'] as const) {
        const resolved = resolveTokens(mode, id)
        for (const [key, value] of Object.entries(preset[mode] ?? {})) {
          // 预设里写了什么，结果里就必须是什么
          expect(resolved[key as keyof ThemeTokens]).toBe(value)
        }
      }
    }
  })

  it('预设会改变至少一个 token（否则换预设毫无效果）', () => {
    // midnight 是明显的紫色系深色主题，与基础蓝色板必然不同
    expect(resolveTokens('dark', 'midnight')).not.toEqual(BASE_DARK)
  })
})

describe('resolveTokens：用户自定义覆盖', () => {
  it('自定义值优先于预设值', () => {
    const resolved = resolveTokens('dark', 'midnight', { 'color-primary': '#123456' })

    expect(resolved['color-primary']).toBe('#123456')
  })

  it('自定义键写成 CSS 变量名（带 --）也能生效', () => {
    // theme store 里存的是用户填的 CSS 变量名，这里必须容忍 -- 前缀
    const resolved = resolveTokens('dark', 'slate', { '--color-bg': '#010203' })

    expect(resolved['color-bg']).toBe('#010203')
  })

  it('未知键与非字符串值会被忽略，不会污染结果', () => {
    /** 故意构造脏数据：一个不存在的 token 名 + 一个数字值（用户手改配置时可能出现） */
    const dirty = { 'not-a-token': '#fff', 'color-bg': 123 } as unknown as Record<string, string>

    const resolved = resolveTokens('dark', 'slate', dirty)

    // 未知键被丢弃：结果里不会多出字段
    expect(Object.keys(resolved)).not.toContain('not-a-token')
    // 非字符串值被忽略：color-bg 仍是基础色板的深色底
    expect(resolved['color-bg']).toBe(BASE_DARK['color-bg'])
  })

  it('每次调用都返回新对象，不会改写基础色板与预设', () => {
    const first = resolveTokens('dark', 'slate')
    // 故意破坏第一次的结果：不改写基础色板的话，再算一次应当还原
    first['color-bg'] = '#ff0000'

    expect(resolveTokens('dark', 'slate')['color-bg']).toBe(BASE_DARK['color-bg'])
    // 基础色板本身也必须没被改动（它是模块级常量，被改了会影响所有后续主题切换）
    expect(BASE_DARK['color-bg']).toBe('#0b1120')
  })
})
