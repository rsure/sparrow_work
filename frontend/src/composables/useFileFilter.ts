// composables/useFileFilter.ts
/**
 * 模块说明：文件列表的「关键词 + 类型」过滤与排序逻辑，全部收拢在这个 composable 里。
 * 使用场景：扫描结果页把扫描到的原始文件数组交给它，返回过滤后的 filtered、排序后的 visible
 * 以及总数/总大小等派生数据；页面组件只负责把返回的值绑到模板上，不自己写过滤代码。
 * 设计要点：输入框要立刻回显、但过滤用防抖后的值，所以用「可写 computed」把两者桥接起来。
 */
// Vue 响应式工具：computed 做派生数据、ref 存可变的筛选状态、Ref 是类型标注（Ref<T> 表示一个响应式容器）
import { computed, ref, type Ref } from 'vue'
// 项目内的文件领域类型：FileEntry 是文件条目，FileKind 是文件大类，SortField/SortOrder 决定排序
import type { FileEntry, FileKind, SortField, SortOrder } from '@/services/file'
// 防抖 ref：让「用户停止输入 200ms 后」才真正触发过滤，避免每敲一个字就重算一遍列表
import { useDebouncedRef } from '@/composables/useDebouncedRef'

export interface UseFileFilterOptions {
  /** 过滤结果里是否保留目录；默认 false（即默认排除目录，只列文件） */
  includeDirectories?: boolean,
}

/** 开发期断言：确认排序没有把 filtered 的缓存数组原地改写了顺序/内容（生产构建会被 tree-shake 掉） */
function assertFilteredUnmutated(
  filtered: readonly FileEntry[],
  snapshotPaths: readonly string[],
): void {
  /** 长度一致且逐项 path 与快照相同，才算「排序没有动过 filtered」 */
  const unchanged =
    filtered.length === snapshotPaths.length &&
    filtered.every((f, i) => f.path === snapshotPaths[i])
  if (!unchanged) {
    throw new Error('[useFileFilter] 断言失败：sort 修改了 filtered 的顺序/内容')
  }
}


/**
 * 扫描结果页的过滤 / 排序状态机。
 * 传入原始文件数组，返回关键词、类型、排序字段、排序方向这几个可绑定状态，
 * 以及过滤结果 filtered、排序结果 visible、总大小 totalSize，还有重置与切换排序两个操作。
 * @param source 原始的（未过滤未排序的）文件数组，通常来自扫描接口的响应式 ref
 * @param options 行为开关，目前只有 includeDirectories（是否保留目录，默认不保留）
 */
export function useFileFilter(
  source: Ref<readonly FileEntry[]>,
  options: UseFileFilterOptions = {},
) {

  // 输入框要立即回显（不能卡），过滤用防抖值 → 用可写 computed 桥接
  /** 输入框的真实值：用户每敲一个字立刻更新，保证输入框不卡顿 */
  const rawKeyword = ref('')
  /** 防抖后的关键词：停顿 200ms 才更新，真正参与过滤的是它 */
  const delayKeyWord = useDebouncedRef('', 200)
  /** 对外暴露的可写 computed：读的时候给 rawKeyword（即时回显），写的时候同时写 rawKeyword 与防抖值 */
  const keyword = computed({
    get: () => rawKeyword.value,
    set: (v: string) => {
      rawKeyword.value = v
      delayKeyWord.value = v
    },
  })

  /** 当前选中的文件类型；null 表示「全部类型」，不做类型过滤 */
  const kind = ref<FileKind | null>(null)
  /** 当前排序字段，默认按文件大小；取值必须是 SortField（name/fileSize/modifiedAt/kind） */
  const sortField = ref<SortField>('fileSize')
  /** 当前排序方向，默认降序（大的 / 新的在前），取值 'asc' 或 'desc' */
  const sortOrder = ref<SortOrder>('desc')

  /** 过滤结果：按「目录开关 → 类型 → 关键词（去空格转小写后做模糊匹配）」依次筛选；用防抖关键词 */
  const filtered = computed<readonly FileEntry[]>(() => {
    /** 生效中的关键词：去首尾空格 + 转小写，空串代表不做关键词过滤 */
    const kw = delayKeyWord.value.trim().toLowerCase()
    return source.value.filter((f) => {
      if (!options.includeDirectories && f.isDirectory) return false
      if (kind.value !== null && f.kind !== kind.value) return false
      return kw === '' || f.name.toLowerCase().includes(kw)
    })
  })

  /** 最终展示顺序的文件数组：在 filtered 之上再排序（先复制再排，避免污染 filtered 的缓存数组） */
  const visible = computed<readonly FileEntry[]>(() => {
    /** 排序方向乘数：升序用 1（保持比较结果），降序用 -1（把结果取反） */
    const dir = sortOrder.value === 'asc' ? 1 : -1
    /** 开发环境下的过滤结果路径快照，仅用于下面断言「排序没有原地改到 filtered」；生产环境为 null 不参与 */
    const filteredSnapshotPaths = import.meta.env.DEV ? filtered.value.map((f) => f.path) : null

    // ★ 必须复制再排：sort 是原地排序，会改到 filtered 的缓存数组
    const sorted = [...filtered.value].sort((a, b) => {
      switch (sortField.value) {
        case 'name':
          return a.name.localeCompare(b.name, 'zh-CN') * dir // 中文按拼音
        case 'fileSize':
          return (a.fileSize - b.fileSize) * dir
        case 'modifiedAt':
          return a.modifiedAt.localeCompare(b.modifiedAt) * dir // ISO 串字典序 == 时间序
        case 'kind':
          return a.kind.localeCompare(b.kind) * dir
      }
    })

    if (filteredSnapshotPaths) assertFilteredUnmutated(filtered.value, filteredSnapshotPaths)
    return sorted
  })

  /** 当前展示结果的总字节数（未格式化），供页面显示「总大小」用；随 visible 变化自动重算 */
  const totalSize = computed(() => visible.value.reduce((s, f) => s + f.fileSize, 0))

  /** 重置全部筛选条件回到初始状态：清空关键词、取消类型筛选、恢复「按大小降序」 */
  function reset(): void {
    keyword.value = ''
    kind.value = null
    sortField.value = 'fileSize'
    sortOrder.value = 'desc'
  }

  /**
   * 点击排序表头时调用：点的还是当前字段就翻转方向（升↔降）；
   * 换到新字段则重置为降序（大的 / 新的在前）。
   */
  function toggleSort(field: SortField): void {
    if (sortField.value === field) {
      sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortField.value = field
      sortOrder.value = 'desc' // 换字段时默认降序（大的/新的在前），符合默认按大小降序
    }
  }

  // 对外暴露：四个可 v-model 绑定的筛选状态 + 三个派生数据 + 两个操作方法
  return { keyword, kind, sortField, sortOrder, filtered, visible, totalSize, reset, toggleSort }
}
