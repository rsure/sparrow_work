/**
 * composables/useFileSegments.ts 的单元测试 —— 把回答正文切成「文字 + 文件胶囊」。
 *
 * 为什么重要：文件清单里的 name 通常只是 path 的尾巴（a.md 是 D:\docs\a.md 的一部分）。
 * 如果匹配顺序不是「长串优先」，正文里的完整路径会被切成两半：
 * 前面剩一段 D:\docs\ 文字、后面才是一个 a.md 胶囊，位置明显错乱。
 * 这类错误在长回答里很难被肉眼发现，所以必须锁住。
 */
// Vitest：断言与用例组织
import { describe, expect, it } from 'vitest'
// Vue：ref / computed 用来测响应式版本会不会随输入变化重新切分
import { computed, ref } from 'vue'
// 被测对象：纯函数 splitFileSegments（核心）与响应式包装 useFileSegments
import { splitFileSegments, useFileSegments } from '@/composables/useFileSegments'
// 类型：对话文件条目的结构（字段含义见 services/chat.ts）
import type { ChatFileRef } from '@/services/chat'

/**
 * 造一个文件条目：path 默认为 name，其余字段给「可预览的普通文本文件」默认值。
 *
 * @param name 文件名（含扩展名）
 * @param path 绝对路径；不传时等于 name（适合不关心路径的用例）
 * @param overrides 需要覆盖的字段
 * @returns 文件条目
 */
function makeFile(name: string, path = name, overrides: Partial<ChatFileRef> = {}): ChatFileRef {
  return {
    // 文件绝对路径：与正文里出现的字符串做匹配
    path,
    // 文件名：也参与匹配（正文里常只写文件名）
    name,
    // 文件大类：文本类，可预览
    kind: 'text',
    // 是否允许预览：true 时点击胶囊会走预览，而不是打开文件夹
    previewable: true,
    // 字节数：仅展示用
    size: 1024,
    // 人类可读大小：胶囊 tooltip 里展示
    size_text: '1.0 KB',
    // 不可预览的原因：可预览时为空串
    reason: '',
    // MIME 类型：决定预览器用哪种方式渲染
    mime: 'text/markdown',
    ...overrides,
  }
}

describe('splitFileSegments：纯文本切分', () => {
  it('正文为空时返回一个空文本片段', () => {
    // 空正文没什么可切的，但调用方仍要拿到一个合法片段，模板才不会渲染出错
    expect(splitFileSegments('', [makeFile('a.md')])).toEqual([{ type: 'text', text: '' }])
  })

  it('没有文件清单时整段都是文本', () => {
    expect(splitFileSegments('答案在 a.md 里', [])).toEqual([{ type: 'text', text: '答案在 a.md 里' }])
  })

  it('命中文件名时切成「文字 + 文件 + 文字」', () => {
    const file = makeFile('a.md')

    const segments = splitFileSegments('答案在 a.md 里', [file])

    expect(segments).toEqual([
      { type: 'text', text: '答案在 ' },
      { type: 'file', file },
      { type: 'text', text: ' 里' },
    ])
  })

  it('完整路径优先于文件名，不会只切掉半截路径', () => {
    // 反斜杠是 Windows 路径的形态，也是后端返回 path 的真实样子
    const file = makeFile('a.md', 'D:\\docs\\a.md')

    const segments = splitFileSegments('见 D:\\docs\\a.md 谢谢', [file])

    // 关键断言：第一个片段只有「见 」，而不是「见 D:\docs\」
    expect(segments).toEqual([
      { type: 'text', text: '见 ' },
      { type: 'file', file },
      { type: 'text', text: ' 谢谢' },
    ])
  })

  it('正文里用正斜杠写路径也能命中（同一文件两种写法）', () => {
    const file = makeFile('a.md', 'D:\\docs\\a.md')

    const segments = splitFileSegments('D:/docs/a.md', [file])

    expect(segments).toEqual([{ type: 'file', file }])
  })

  it('多个文件按在正文里出现的先后顺序切分', () => {
    const first = makeFile('a.md')
    const second = makeFile('b.md')

    const segments = splitFileSegments('先 a.md 再 b.md', [second, first])

    // 传入顺序与正文顺序相反，结果仍按正文顺序（切分是按位置找的，与数组顺序无关）
    expect(segments).toEqual([
      { type: 'text', text: '先 ' },
      { type: 'file', file: first },
      { type: 'text', text: ' 再 ' },
      { type: 'file', file: second },
    ])
  })

  it('正文里没出现的文件不会被塞进结果', () => {
    const segments = splitFileSegments('什么都没提到', [makeFile('a.md')])

    expect(segments).toEqual([{ type: 'text', text: '什么都没提到' }])
  })
})

describe('useFileSegments：响应式版本', () => {
  it('answer 变化后重新切分', () => {
    // 回答文本用 ref 存，模拟流式拼接过程中的持续变化
    const answer = ref('先看 a.md')
    // 文件清单：本项目里只在 done 事件后才会有值
    const files = computed(() => [makeFile('a.md')])

    const segments = useFileSegments(computed(() => answer.value), files)

    expect(segments.value.map((s) => s.type)).toEqual(['text', 'file'])

    // 回答变成一段不含文件名的文字：应当重新切成单个文本片段
    answer.value = '这轮没有引用任何文件'
    expect(segments.value).toEqual([{ type: 'text', text: '这轮没有引用任何文件' }])
  })
})
