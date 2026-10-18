/**
 * components/FilePathChip.vue 的组件测试 —— 回答里那段可点击的「文件胶囊」。
 *
 * 为什么重要：这个组件承担了三件容易出错的判断，而且都是「环境相关」的：
 *   1. 文件已不存在（missing）时不能去预览，只能提示；
 *   2. 不能预览的文件（二进制/文件夹）点击后应当打开所在文件夹，而不是什么都不做；
 *   3. 浏览器调试模式下没有 window.desktop，所有「打开」类动作都必须给出人话提示，
 *      否则用户点了没反应，只会以为是 bug。
 * 这些分支在真实桌面应用里很难逐个复现，用桩替换 window.desktop 正好覆盖。
 */
// Vitest：用例组织、mock、断言
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
// Vue Test Utils：mount 挂载、flushPromises 等异步动作跑完
import { flushPromises, mount } from '@vue/test-utils'
// Vue：defineComponent + h 手写两个 UI 替身（用渲染函数，避免依赖运行时模板编译器）
import { defineComponent, h, type PropType } from 'vue'
// 被测组件：文件路径胶囊
import FilePathChip from '@/components/FilePathChip.vue'
// Vant 轻提示：已被 vi.mock 换成假的，用来断言提示文案
import { showToast } from 'vant'
// 类型：对话文件条目
import type { ChatFileRef } from '@/services/chat'

// 换掉整个 vant 模块：测试只关心「提示了什么文案」，不关心 Toast 长什么样
vi.mock('vant', () => ({ showToast: vi.fn() }))

/** 假提示函数的类型化引用 */
const toast = vi.mocked(showToast)

/**
 * van-icon 的替身：把图标名写进 class，断言「选的是哪个图标」时不用猜 Vant 内部实现。
 */
const IconStub = defineComponent({
  name: 'IconStub',
  props: {
    /** 图标名，如 photo-o / warning-o / ellipsis */
    name: { type: String, default: '' },
  },
  setup(props) {
    return () => h('i', { class: ['icon-stub', `icon-${props.name}`] })
  },
})

/**
 * van-popover 的替身：保留 #reference 插槽，并暴露 select 事件，
 * 测试里可以直接 $emit('select', action) 模拟用户点了某个菜单项。
 */
const PopoverStub = defineComponent({
  name: 'PopoverStub',
  props: {
    /** 是否展开（v-model:show 绑定的值） */
    show: { type: Boolean, default: false },
    /** 菜单项数组，元素形如 { text: '用系统程序打开' } */
    actions: { type: Array as PropType<Array<{ text: string }>>, default: () => [] },
    /** 弹出位置 */
    placement: { type: String, default: 'bottom-start' },
  },
  emits: ['select', 'update:show'],
  setup(_props, { slots }) {
    // 用渲染函数而不是模板字符串：项目用的是运行时版 Vue，不支持运行时编译模板
    return () => h('div', { class: 'popover-stub' }, slots.reference?.())
  },
})

/** 公共挂载选项：把两个 Vant 组件替换成上面的替身 */
const MOUNT_OPTIONS = {
  global: { stubs: { 'van-icon': IconStub, 'van-popover': PopoverStub } },
}

/**
 * 造一个文件条目：默认是「可预览的 Markdown 文件」。
 *
 * @param overrides 需要覆盖的字段
 * @returns 文件条目
 */
function makeFile(overrides: Partial<ChatFileRef> = {}): ChatFileRef {
  return {
    // 绝对路径：打开文件夹 / 用系统程序打开时传给 Electron
    path: 'D:/docs/a.md',
    // 文件名：胶囊上显示的文字
    name: 'a.md',
    // 文件大类：决定前置图标
    kind: 'text',
    // 是否可预览：true 时点击走预览
    previewable: true,
    // 字节数：仅展示
    size: 2048,
    // 人类可读大小：tooltip 里展示
    size_text: '2.0 KB',
    // 不可预览的原因：可预览时为空
    reason: '',
    // MIME 类型
    mime: 'text/markdown',
    ...overrides,
  }
}

/**
 * 造一份「还没检查过」的更新状态，给下面的 desktop 替身复用。
 *
 * @returns 更新状态快照（status=idle）
 */
function idleUpdateState(): DesktopUpdateState {
  return { status: 'idle', version: null, percent: 0, message: '', checked_at: null }
}

/**
 * 造一个桌面环境 API（window.desktop）：默认所有能力都可用。
 *
 * @param overrides 需要覆盖的能力（例如让 openPath 返回错误串）
 * @returns 满足 DesktopApi 接口的对象
 */
function makeDesktop(overrides: Partial<DesktopApi> = {}): DesktopApi {
  return {
    // 是否桌面环境：true 才会渲染「⋯」菜单
    isDesktop: true,
    // 操作系统平台
    platform: 'win32',
    // preload 注入的后端端口
    apiPort: 8000,
    // 运行时版本号（关于页展示）
    versions: { electron: '33.0.0', chrome: '130.0.0', node: '20.0.0' },
    // 选择文件夹：本组件不调用，给个空实现
    selectFolder: vi.fn(async () => null),
    // 在文件管理器中定位文件
    showItemInFolder: vi.fn(async () => undefined),
    // 用系统默认程序打开文件；返回空串表示成功
    openPath: vi.fn(async () => ''),
    // 应用版本号：本组件不调用，给个固定值
    getAppVersion: vi.fn(async () => '0.1.0'),
    // 自动更新能力：本组件不调用，四个方法都给空实现（onState 返回取消函数）
    updates: {
      getState: vi.fn(async () => idleUpdateState()),
      check: vi.fn(async () => idleUpdateState()),
      install: vi.fn(async () => undefined),
      onState: vi.fn(() => () => undefined),
    },
    ...overrides,
  }
}

/**
 * 把假的桌面 API 挂到 window 上（模拟 Electron preload 注入）。
 *
 * @param desktop 桌面 API
 */
function stubDesktop(desktop: DesktopApi): void {
  Object.defineProperty(window, 'desktop', { value: desktop, configurable: true, writable: true })
}

// 每个用例前清空提示记录
beforeEach(() => {
  toast.mockClear()
})

// 用例结束移除注入的桌面 API，恢复「浏览器调试模式」
afterEach(() => {
  delete (window as unknown as Record<string, unknown>).desktop
})

describe('FilePathChip：展示', () => {
  it('显示文件名，tooltip 里带上路径、大小与不可预览原因', () => {
    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ name: 'a.bin', path: 'D:/docs/a.bin', previewable: false, reason: '二进制文件不支持预览' }) },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('.file-chip__name').text()).toBe('a.bin')
    // 三段用 ' · ' 连接，鼠标悬停时一次说清「这是哪个文件、多大、为什么点不开」
    expect(wrapper.find('.file-chip').attributes('title')).toBe(
      'D:/docs/a.bin · 2.0 KB · 二进制文件不支持预览',
    )
    // 不可预览且不是缺失文件：给一个「仅文件夹」徽标（二进制/目录都属于这种情况）
    expect(wrapper.find('.file-chip__badge').text()).toBe('仅文件夹')
  })

  it('可预览时不显示「仅文件夹」徽标', () => {
    const wrapper = mount(FilePathChip, { props: { file: makeFile() }, ...MOUNT_OPTIONS })

    expect(wrapper.find('.file-chip__badge').exists()).toBe(false)
  })

  it('图标随文件类别变化', () => {
    const image = mount(FilePathChip, {
      props: { file: makeFile({ kind: 'image' }) },
      ...MOUNT_OPTIONS,
    })
    expect(image.find('.icon-stub').classes()).toContain('icon-photo-o')

    const missing = mount(FilePathChip, {
      props: { file: makeFile({ kind: 'missing' }) },
      ...MOUNT_OPTIONS,
    })
    expect(missing.find('.icon-stub').classes()).toContain('icon-warning-o')
  })
})

describe('FilePathChip：点击行为', () => {
  it('文件已不存在时只提示，不触发预览', async () => {
    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ kind: 'missing', previewable: false, reason: '文件已不存在' }) },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.file-chip').trigger('click')

    expect(toast).toHaveBeenCalledWith('文件已不存在或不可访问')
    expect(wrapper.emitted('preview')).toBeUndefined()
  })

  it('可预览文件点击后把原样的文件对象抛给父组件', async () => {
    const file = makeFile()
    const wrapper = mount(FilePathChip, { props: { file }, ...MOUNT_OPTIONS })

    await wrapper.find('.file-chip').trigger('click')

    expect(wrapper.emitted('preview')).toEqual([[file]])
    // 走的是预览分支，不应该弹任何提示
    expect(toast).not.toHaveBeenCalled()
  })

  it('浏览器调试模式下点不可预览文件，提示无法打开本地文件夹', async () => {
    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ kind: 'binary', previewable: false }) },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.file-chip').trigger('click')
    await flushPromises()

    expect(toast).toHaveBeenCalledWith('浏览器调试模式下无法打开本地文件夹，请在桌面应用里操作')
    expect(wrapper.emitted('preview')).toBeUndefined()
  })

  it('桌面环境下点不可预览文件，会在文件管理器中定位它', async () => {
    const desktop = makeDesktop()
    stubDesktop(desktop)

    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ path: 'D:/docs/a.bin', kind: 'binary', previewable: false }) },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.file-chip').trigger('click')
    await flushPromises()

    expect(desktop.showItemInFolder).toHaveBeenCalledWith('D:/docs/a.bin')
    expect(toast).not.toHaveBeenCalled()
  })
})

describe('FilePathChip：桌面环境菜单', () => {
  it('浏览器环境不渲染「⋯」菜单', () => {
    const wrapper = mount(FilePathChip, { props: { file: makeFile() }, ...MOUNT_OPTIONS })

    expect(wrapper.findComponent(PopoverStub).exists()).toBe(false)
  })

  it('桌面环境给出两个固定菜单项', () => {
    stubDesktop(makeDesktop())

    const wrapper = mount(FilePathChip, { props: { file: makeFile() }, ...MOUNT_OPTIONS })

    expect(wrapper.findComponent(PopoverStub).props('actions')).toEqual([
      { text: '用系统程序打开' },
      { text: '打开所在文件夹' },
    ])
  })

  it('「用系统程序打开」会把路径交给 Electron', async () => {
    const desktop = makeDesktop()
    stubDesktop(desktop)

    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ path: 'D:/docs/a.md' }) },
      ...MOUNT_OPTIONS,
    })

    wrapper.findComponent(PopoverStub).vm.$emit('select', { text: '用系统程序打开' })
    await flushPromises()

    expect(desktop.openPath).toHaveBeenCalledWith('D:/docs/a.md')
    // 成功时 Electron 返回空串，不该弹错误提示
    expect(toast).not.toHaveBeenCalled()
  })

  it('「用系统程序打开」失败时把 Electron 返回的错误提示给用户', async () => {
    const desktop = makeDesktop({ openPath: vi.fn(async () => '没有默认程序可以打开该文件') })
    stubDesktop(desktop)

    const wrapper = mount(FilePathChip, { props: { file: makeFile() }, ...MOUNT_OPTIONS })

    wrapper.findComponent(PopoverStub).vm.$emit('select', { text: '用系统程序打开' })
    await flushPromises()

    expect(toast).toHaveBeenCalledWith('打开失败：没有默认程序可以打开该文件')
  })

  it('「打开所在文件夹」走 showItemInFolder', async () => {
    const desktop = makeDesktop()
    stubDesktop(desktop)

    const wrapper = mount(FilePathChip, {
      props: { file: makeFile({ path: 'D:/docs/a.md' }) },
      ...MOUNT_OPTIONS,
    })

    wrapper.findComponent(PopoverStub).vm.$emit('select', { text: '打开所在文件夹' })
    await flushPromises()

    expect(desktop.showItemInFolder).toHaveBeenCalledWith('D:/docs/a.md')
  })
})
