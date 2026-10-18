/**
 * components/MarkdownView.vue 的组件测试 —— Markdown 渲染、XSS 净化、代码块与文件胶囊。
 *
 * 为什么必须测：doc/23-体验层改造方案.md 里明确写着「未做自动化 XSS 用例（前端无测试基建）」。
 * 这个组件是**整条链路上唯一把后端文本当 HTML 插进页面的地方**（v-html），
 * 一旦 DOMPurify 被误删、被换成 dangerouslyUseHTMLString、或者 sanitize 的配置写错，
 * AI 输出里的一句恶意 HTML 就能在用户机器上执行脚本。人工点一遍很难覆盖所有攻击面，
 * 所以这里把常见的几种注入姿势都固化成用例。
 *
 * 测试策略：
 *   - 真实使用 markdown-it + highlight.js + DOMPurify（不打桩），测的才是上线时的真实行为；
 *   - 只把 Vant 的轻提示与 UI 组件替换掉（单元测试不关心弹窗长什么样）。
 */
// Vitest：用例组织、mock、假定时器
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
// Vue Test Utils：mount 挂载组件、flushPromises 等异步事件处理完
import { flushPromises, mount } from '@vue/test-utils'
// Vue：nextTick 等 DOM 更新
import { nextTick } from 'vue'
// 被测组件：Markdown 渲染器
import MarkdownView from '@/components/MarkdownView.vue'
// Vant 轻提示：下面用 vi.mock 换成了假的，这里引入的是假的实现，用来断言提示文案
import { showToast } from 'vant'
// 类型：对话文件条目
import type { ChatFileRef } from '@/services/chat'

// 把整个 vant 模块换掉：组件测试只需要能断言「提示了什么」，不需要真的弹 Toast
vi.mock('vant', () => ({ showToast: vi.fn() }))

/** 假提示函数的类型化引用，省去每处都写 vi.mocked */
const toast = vi.mocked(showToast)

/** 公共挂载选项：本项目在 main.ts 里全局注册 Vant 组件，测试里没有，用占位替身避免告警 */
const MOUNT_OPTIONS = { global: { stubs: { 'van-icon': true, 'van-popover': true } } }

/**
 * 造一个文件条目：字段与 services/chat.ts 的 ChatFileRef 对齐。
 *
 * @param name 文件名
 * @param path 绝对路径，默认等于 name
 * @returns 文件条目
 */
function makeFile(name: string, path = name): ChatFileRef {
  return {
    // 绝对路径：胶囊 tooltip 与预览都用它
    path,
    // 文件名：胶囊上显示的文字
    name,
    // 文件大类：文本类
    kind: 'text',
    // 是否可预览：true 表示点击胶囊会请求左侧面板预览
    previewable: true,
    // 字节数：仅展示
    size: 2048,
    // 人类可读大小：tooltip 里展示
    size_text: '2.0 KB',
    // 不可预览原因：可预览时为空
    reason: '',
    // MIME 类型
    mime: 'text/markdown',
  }
}

// 每个用例前清掉提示调用记录，避免互相干扰
beforeEach(() => {
  toast.mockClear()
})

// 用例结束恢复真实定时器（流式节流用例会开假定时器）
afterEach(() => {
  vi.useRealTimers()
})

describe('MarkdownView：基础渲染', () => {
  it('普通 Markdown 语法被渲染成 HTML 元素', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '**加粗** 与 `行内代码`' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('strong').text()).toBe('加粗')
    expect(wrapper.find('code').text()).toBe('行内代码')
  })

  it('标题按层级渲染', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '## 扫描结果' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('h2').text()).toBe('扫描结果')
  })

  it('没有文件清单时只有 HTML 块，没有文件胶囊', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '纯文本回答' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('.markdown-view__html').exists()).toBe(true)
    expect(wrapper.find('.file-chip').exists()).toBe(false)
  })
})

describe('MarkdownView：XSS 净化（DOMPurify 白名单）', () => {
  it('<script> 标签连同内容一起被清除', () => {
    const wrapper = mount(MarkdownView, {
      // markdown-it 开了 html:true，原始 HTML 会原样进入渲染链路，必须靠 DOMPurify 拦住
      props: { content: '正常文本<script>alert(1)</script>' },
      ...MOUNT_OPTIONS,
    })

    // 一个 <script> 元素都不允许留下
    expect(wrapper.find('script').exists()).toBe(false)
    // 内容也不能以文本形式残留（否则只是「看不见的脚本」）
    expect(wrapper.html()).not.toContain('alert(1)')
    // 正常文本不受影响
    expect(wrapper.text()).toContain('正常文本')
  })

  it('内联事件处理器（onerror）被清除，但安全的 <img> 保留', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '<img src="https://example.com/a.png" onerror="alert(1)">' },
      ...MOUNT_OPTIONS,
    })

    const img = wrapper.find('img')
    // 正常的图片仍然渲染（净化不能「一刀切」到把内容全删了）
    expect(img.exists()).toBe(true)
    // 事件属性必须被剥掉：它才是执行脚本的入口
    expect(img.attributes('onerror')).toBeUndefined()
    expect(img.attributes('src')).toBe('https://example.com/a.png')
  })

  it('javascript: 协议的链接被剥掉 href', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '<a href="javascript:alert(1)">点我</a>' },
      ...MOUNT_OPTIONS,
    })

    const link = wrapper.find('a')
    // 链接元素本身可以保留（文案还是有意义的），但危险协议必须去掉
    expect(link.attributes('href')).toBeUndefined()
    expect(wrapper.html()).not.toContain('javascript:')
  })

  it('iframe 被整段移除（不允许嵌入外部页面）', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '<iframe src="https://example.com/evil"></iframe>' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('常规 Markdown 链接仍然保留 href（净化没有过度）', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '[文档](https://example.com/doc)' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.find('a').attributes('href')).toBe('https://example.com/doc')
  })
})

describe('MarkdownView：代码块', () => {
  it('渲染带语言标签、复制按钮与高亮 class 的代码块', () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '```ts\nconst a: number = 1\n```' },
      ...MOUNT_OPTIONS,
    })

    const block = wrapper.find('.md-code')
    expect(block.exists()).toBe(true)
    // data-lang 是自定义属性，靠 DOMPurify 的 ADD_ATTR 才保留下来
    expect(block.attributes('data-lang')).toBe('ts')
    expect(block.find('.md-code__lang').text()).toBe('ts')
    // 复制按钮：纯 HTML 字符串生成，事件靠根节点事件委托
    expect(block.find('.md-code__copy').exists()).toBe(true)

    const code = block.find('.md-code__pre code')
    // hljs 类名是 highlight.js 样式表生效的前提
    expect(code.classes()).toContain('hljs')
    // 关键字被包上了高亮 span
    expect(code.html()).toContain('hljs-')
  })

  it('点击复制按钮把代码写进剪贴板并提示「已复制」', async () => {
    /** 假的剪贴板写入函数：记录被写入的文本（形参名以 _ 开头，表示只用于占位） */
    const writeText = vi.fn(async (_text: string) => undefined)
    // jsdom 没有 Clipboard API，这里临时补一个
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    const wrapper = mount(MarkdownView, {
      props: { content: '```ts\nconst a: number = 1\n```' },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.md-code__copy').trigger('click')
    // 复制是 async 的，等它跑完
    await flushPromises()

    expect(writeText).toHaveBeenCalledTimes(1)
    // 只断言「包含代码内容」：highlight.js 可能给文本包上 span，但 textContent 不变
    expect(writeText.mock.calls[0]?.[0]).toContain('const a: number = 1')
    expect(toast).toHaveBeenCalledWith('已复制')

    // 清掉临时补的剪贴板，避免影响后续用例
    delete (navigator as unknown as Record<string, unknown>).clipboard
  })

  it('剪贴板不可用时提示「当前环境不支持自动复制」', async () => {
    // 浏览器调试模式下（非安全上下文）navigator.clipboard 可能不存在
    const wrapper = mount(MarkdownView, {
      props: { content: '```ts\nconst a: number = 1\n```' },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.md-code__copy').trigger('click')
    await flushPromises()

    expect(toast).toHaveBeenCalledWith('当前环境不支持自动复制')
  })

  it('剪贴板写入失败时提示用户手动选择', async () => {
    /** 模拟浏览器拒绝写入（例如用户未授权剪贴板权限） */
    const writeText = vi.fn(async () => {
      throw new Error('denied')
    })
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    const wrapper = mount(MarkdownView, {
      props: { content: '```ts\nconst a: number = 1\n```' },
      ...MOUNT_OPTIONS,
    })

    await wrapper.find('.md-code__copy').trigger('click')
    await flushPromises()

    expect(toast).toHaveBeenCalledWith('复制失败，请手动选择')

    delete (navigator as unknown as Record<string, unknown>).clipboard
  })
})

describe('MarkdownView：流式渲染节流', () => {
  it('streaming 为 true 时内容变化要等 60ms 才落到 DOM', async () => {
    vi.useFakeTimers()

    const wrapper = mount(MarkdownView, {
      props: { content: '第一段', streaming: true },
      ...MOUNT_OPTIONS,
    })

    // 流式模式下首次渲染也被节流推迟，避免每个 token 都重排一次 DOM
    await nextTick()
    expect(wrapper.text()).toBe('')

    vi.advanceTimersByTime(60)
    await nextTick()
    expect(wrapper.text()).toBe('第一段')

    // 追加内容后同样要等节流窗口
    await wrapper.setProps({ content: '第一段，第二段' })
    expect(wrapper.text()).toBe('第一段')

    vi.advanceTimersByTime(60)
    await nextTick()
    expect(wrapper.text()).toBe('第一段，第二段')
  })

  it('streaming 为 false 时不节流，内容立刻渲染', async () => {
    const wrapper = mount(MarkdownView, {
      props: { content: '一次性渲染' },
      ...MOUNT_OPTIONS,
    })

    expect(wrapper.text()).toBe('一次性渲染')
  })
})

describe('MarkdownView：文件胶囊', () => {
  it('正文里出现的文件被渲染成胶囊，点击后向父组件抛出 preview', async () => {
    const file = makeFile('a.md', 'D:/docs/a.md')

    const wrapper = mount(MarkdownView, {
      props: { content: '答案见 D:/docs/a.md', files: [file] },
      ...MOUNT_OPTIONS,
    })

    const chip = wrapper.find('.file-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.find('.file-chip__name').text()).toBe('a.md')

    await chip.trigger('click')

    // 事件必须是「原样的文件对象」，父组件据此去加载预览
    expect(wrapper.emitted('preview')).toEqual([[file]])
  })
})
