/**
 * composables/useFileFilter.ts 的单元测试 —— 扫描结果页的「过滤 / 排序 / 统计」状态机。
 *
 * 为什么重要：
 *   1. 关键词过滤是「防抖后生效」的，写错会让搜索框看起来没反应；
 *   2. 排序必须「先复制再排」，否则会原地改掉 filtered 的缓存数组，
 *      表现为「切换一次排序后，取消排序结果顺序也回不去了」——这类隐性状态污染很难排查，
 *      实现里专门留了开发期断言，这里把断言保护的行为也测出来。
 */
// Vitest：假定时器用来跨过 200ms 的防抖窗口
import { afterEach, describe, expect, it, vi } from 'vitest'
// Vue：ref 造响应式输入源，effectScope 模拟组件作用域（composable 内部的 onScopeDispose 需要它）
import { effectScope, ref, type EffectScope, type Ref } from 'vue'
// 被测对象与选项类型：过滤/排序状态机
import { useFileFilter, type UseFileFilterOptions } from '@/composables/useFileFilter'
// 领域类型：文件条目（字段含义见 services/file.ts）
import type { FileEntry } from '@/services/file'

/** 本文件创建过的作用域：用例结束统一停掉，避免防抖定时器漏到下一个用例 */
const scopes: EffectScope[] = []

/**
 * 造一条文件记录：只传关心的字段，其余给「普通文档」默认值。
 *
 * @param overrides 需要覆盖的字段（例如 name / fileSize / kind）
 * @returns 完整的文件条目
 */
function makeEntry(overrides: Partial<FileEntry> = {}): FileEntry {
  /** 绝对路径：默认放在 D:/docs 下，文件名从路径尾巴上取 */
  const path = overrides.path ?? 'D:/docs/a.md'
  return {
    // 绝对路径：列表 key，也是排序后断言「顺序没被弄乱」的依据
    path,
    // 文件名：关键词过滤匹配的就是它（不匹配整条路径）
    name: overrides.name ?? path.slice(path.lastIndexOf('/') + 1),
    // 字节数：默认 100B，用例按需覆盖
    fileSize: overrides.fileSize ?? 100,
    // 文件大类：默认普通文档
    kind: overrides.kind ?? 'document',
    // 是否目录：默认是文件，目录只在 includeDirectories 时被保留
    isDirectory: overrides.isDirectory ?? false,
    // 修改时间：ISO 字符串，字典序即时间序
    modifiedAt: overrides.modifiedAt ?? '2026-01-01T00:00:00.000Z',
    // 是否已入 RAG 索引：本 composable 不关心，给默认值即可
    indexed: overrides.indexed ?? false,
  }
}

/**
 * 在独立作用域里创建过滤器，返回状态机对象。
 *
 * @param source 原始文件数组（响应式）
 * @param options 行为开关（是否保留目录）
 * @returns useFileFilter 的返回值
 */
function createFilter(source: Ref<readonly FileEntry[]>, options?: UseFileFilterOptions) {
  /** 每个用例独立的 scope，便于统一销毁 */
  const scope = effectScope()
  scopes.push(scope)
  const result = scope.run(() => useFileFilter(source, options))
  if (!result) throw new Error('在 effectScope 里创建 useFileFilter 失败')
  return result
}

// 用例结束：恢复真实定时器并销毁作用域（等价于组件卸载）
afterEach(() => {
  vi.useRealTimers()
  for (const scope of scopes.splice(0)) scope.stop()
})

describe('useFileFilter：过滤', () => {
  it('默认排除目录，只保留文件', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a.md' }),
      makeEntry({ path: 'D:/docs/sub', isDirectory: true }),
    ])
    const filter = createFilter(source)

    expect(filter.filtered.value.map((f) => f.path)).toEqual(['D:/docs/a.md'])
  })

  it('includeDirectories 为 true 时保留目录', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a.md' }),
      makeEntry({ path: 'D:/docs/sub', isDirectory: true }),
    ])
    const filter = createFilter(source, { includeDirectories: true })

    expect(filter.filtered.value).toHaveLength(2)
  })

  it('按类型筛选：kind 为 null 表示全部', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a.md', kind: 'document' }),
      makeEntry({ path: 'D:/docs/b.png', kind: 'image' }),
    ])
    const filter = createFilter(source)

    // 初始 null：不过滤
    expect(filter.filtered.value).toHaveLength(2)

    filter.kind.value = 'image'
    expect(filter.filtered.value.map((f) => f.name)).toEqual(['b.png'])
  })

  it('关键词过滤要等 200ms 防抖后才生效，且忽略大小写与首尾空格', () => {
    vi.useFakeTimers()
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/Readme.md' }),
      makeEntry({ path: 'D:/docs/b.txt' }),
    ])
    const filter = createFilter(source)

    filter.keyword.value = ' README '

    // 输入框立刻回显（用户敲下去就得看见字），但过滤还没跑
    expect(filter.keyword.value).toBe(' README ')
    expect(filter.filtered.value).toHaveLength(2)

    vi.advanceTimersByTime(199)
    expect(filter.filtered.value).toHaveLength(2)

    vi.advanceTimersByTime(1)
    // 去空格 + 转小写后做包含匹配，所以 'README' 能命中 'Readme.md'
    expect(filter.filtered.value.map((f) => f.name)).toEqual(['Readme.md'])
  })
})

describe('useFileFilter：排序', () => {
  it('默认按文件大小降序（大的在前）', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/small.md', fileSize: 100 }),
      makeEntry({ path: 'D:/docs/large.md', fileSize: 300 }),
      makeEntry({ path: 'D:/docs/mid.md', fileSize: 200 }),
    ])
    const filter = createFilter(source)

    expect(filter.sortField.value).toBe('fileSize')
    expect(filter.sortOrder.value).toBe('desc')
    expect(filter.visible.value.map((f) => f.name)).toEqual(['large.md', 'mid.md', 'small.md'])
  })

  it('点击同一个排序字段会翻转方向', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/small.md', fileSize: 100 }),
      makeEntry({ path: 'D:/docs/large.md', fileSize: 300 }),
    ])
    const filter = createFilter(source)

    filter.toggleSort('fileSize')
    expect(filter.sortOrder.value).toBe('asc')
    expect(filter.visible.value.map((f) => f.name)).toEqual(['small.md', 'large.md'])
  })

  it('换到新字段时重置为降序（大的 / 新的在前）', () => {
    const source = ref<readonly FileEntry[]>([makeEntry()])
    const filter = createFilter(source)

    // 先把默认字段翻成升序
    filter.toggleSort('fileSize')
    expect(filter.sortOrder.value).toBe('asc')

    filter.toggleSort('name')
    expect(filter.sortField.value).toBe('name')
    expect(filter.sortOrder.value).toBe('desc')
  })

  it('按名称排序使用中文拼音顺序', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/白.md' }),
      makeEntry({ path: 'D:/docs/阿.md' }),
    ])
    const filter = createFilter(source)

    filter.toggleSort('name')
    // localeCompare('zh-CN') 下「阿(a)」排「白(bai)」之前，降序则相反
    expect(filter.visible.value.map((f) => f.name)).toEqual(['白.md', '阿.md'])
  })

  it('按修改时间排序（ISO 字符串字典序即时间序）', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/1.md', modifiedAt: '2026-01-01T00:00:00.000Z' }),
      makeEntry({ path: 'D:/docs/3.md', modifiedAt: '2026-03-01T00:00:00.000Z' }),
      makeEntry({ path: 'D:/docs/2.md', modifiedAt: '2026-02-01T00:00:00.000Z' }),
    ])
    const filter = createFilter(source)

    filter.toggleSort('modifiedAt')
    expect(filter.visible.value.map((f) => f.name)).toEqual(['3.md', '2.md', '1.md'])
  })

  it('按类型排序', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a', kind: 'document' }),
      makeEntry({ path: 'D:/docs/b', kind: 'other' }),
      makeEntry({ path: 'D:/docs/c', kind: 'image' }),
    ])
    const filter = createFilter(source)

    filter.toggleSort('kind')
    expect(filter.visible.value.map((f) => f.kind)).toEqual(['other', 'image', 'document'])
  })

  it('排序不改写过滤结果的顺序（先复制再排）', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a.md', fileSize: 100 }),
      makeEntry({ path: 'D:/docs/b.md', fileSize: 300 }),
    ])
    const filter = createFilter(source)

    // 先读一次过滤结果，把它的顺序记下来
    const filteredOrder = filter.filtered.value.map((f) => f.path)
    // 排序结果里大的在前，顺序与 filtered 不同
    expect(filter.visible.value.map((f) => f.path)).toEqual(['D:/docs/b.md', 'D:/docs/a.md'])
    // 但 filtered 必须保持原顺序：实现里的 DEV 断言也会在这次读取中被触发
    expect(filter.filtered.value.map((f) => f.path)).toEqual(filteredOrder)
  })
})

describe('useFileFilter：统计与重置', () => {
  it('totalSize 只统计当前展示的条目', () => {
    const source = ref<readonly FileEntry[]>([
      makeEntry({ path: 'D:/docs/a.md', fileSize: 100 }),
      makeEntry({ path: 'D:/docs/b.md', fileSize: 300 }),
      makeEntry({ path: 'D:/docs/sub', isDirectory: true, fileSize: 0 }),
    ])
    const filter = createFilter(source)

    // 目录被默认排除，所以只累加两个文件
    expect(filter.totalSize.value).toBe(400)

    filter.kind.value = 'other'
    // 没有任何条目的类型是 other：展示为空，总大小也归零
    expect(filter.totalSize.value).toBe(0)
  })

  it('reset 把关键词、类型、排序全部恢复默认', () => {
    vi.useFakeTimers()
    const source = ref<readonly FileEntry[]>([makeEntry({ kind: 'image' })])
    const filter = createFilter(source)

    filter.keyword.value = 'x'
    filter.kind.value = 'image'
    filter.toggleSort('name')

    filter.reset()

    expect(filter.keyword.value).toBe('')
    expect(filter.kind.value).toBeNull()
    expect(filter.sortField.value).toBe('fileSize')
    expect(filter.sortOrder.value).toBe('desc')

    // reset 也要让防抖层回到空串，否则 200ms 后旧关键词会「复活」
    vi.advanceTimersByTime(200)
    expect(filter.filtered.value).toHaveLength(1)
  })
})
