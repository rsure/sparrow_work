<!--
📚 背景知识：普通插槽只能传「模板结构」，作用域插槽（scoped slot）额外把子组件内部的数据
也传出来，写法是在 <slot> 标签上加属性（<slot name="row" :file="file" />），
父组件用 <template #row="{ file }"> 把这些属性解构出来使用。
典型场景就是下面的 FileList：子组件知道「每一行是什么文件」，但不知道「这一行该长什么样」，
于是把 file 数据甩给插槽，让父组件决定视觉呈现。
官方文档：指南 · 作用域插槽
 -->

<!-- components/FileList.vue -->
<script setup lang="ts">
/**
 * FileList.vue —— 文件多选列表组件（Vant 单元格列表）。
 * 使用场景：扫描结果页的列表视图，展示过滤后的文件，支持勾选、全选、清空选择、打开所在目录、导入。
 * 它是一个「受控」组件：勾选了哪些文件由父组件通过 selected 传入，本组件只把用户操作用事件上报；
 * 行内容通过 #row 作用域插槽交给父组件自定义，#empty 插槽可替换空状态文案。
 */
/**
改造 `FileList.vue`，让它支持：
1. `#row` 作用域插槽，暴露 `{ file, sizeText, index }` 三个 slot props
   （📌 注意：本仓库实际实现把第二个 prop 命名为 `sizeLabel`，见下方 <slot name="row">；
   这里的名称是题目原文，读代码时以实际实现为准）
2. `#empty` 具名插槽，带默认内容「没有匹配的文件」
3. 默认行内容（不填 slot 时）也要可用
 */
// 文件条目类型：每行的数据来源，含 path/name/fileSize/kind/isDirectory 等字段
import type { FileEntry } from '@/services/file'

interface Props {
  /** 要展示的文件数组（父组件已完成过滤与排序）；只读，本组件不修改它 */
  files: readonly FileEntry[]
  /** 已勾选文件的绝对路径集合；用 Set 是为了 selected.has(path) 判断达到 O(1) */
  selected: ReadonlySet<string>
  /** 是否处于加载中：为 true 时列表区显示「加载中…」而不是文件行；默认 false */
  loading?: boolean
}
/** 给 loading 兜底为 false，父组件不传时不会出现加载态 */
withDefaults(defineProps<Props>(), { loading: false })

/** 本组件对外的事件：勾选/取消勾选、全选、清空选择、导入文档、打开所在目录 */
const emit = defineEmits<{
  /** 勾选或取消勾选某一行，参数是该文件的绝对路径 */
  toggle: [path: string]
  /** 点击「全选」：请求父组件把当前列表全部选中 */
  selectAll: []
  /** 点击「清空选择」：请求父组件清空选中集合 */
  clearSelection: []
  /** 点击「导入」：请求父组件把该文件入库（仅 kind 为 document 的行会出现这个按钮） */
  open: [entry: FileEntry]
  /** 点击「打开」：请求父组件在系统文件管理器中定位该文件 */
  openFolder: [entry: FileEntry]
}>()

/** 把字节数格式化成人类可读的字符串（如 2048 → "2.0 KB"）；1KB 以下直接显示 B，最多算到 TB */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB'] as const
  let v = bytes / 1024,
    i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(1)} ${units[i] ?? 'TB'}`
}
</script>

<template>
  <div class="file-list">
    <!-- 工具条：两个批量操作按钮 + 已选数量标签（数量取 Set 的 .size，父组件持有选中集合） -->
    <div class="file-list__toolbar">
      <van-button size="small" plain @click="emit('selectAll')">全选</van-button>
      <van-button size="small" plain @click="emit('clearSelection')">清空选择</van-button>
      <van-tag plain type="primary" class="file-list__selected-tag">已选 {{ selected.size }} 项</van-tag>
      <!-- 📌 讲义校正：selected 是 ReadonlySet<string>，取个数要用 Set 原生的 .size，
           不存在 .fileSize 这个属性（.fileSize 只是 FileEntry 里"文件大小"字段的名字，
           这里原稿把两者混用了，已改正） -->
    </div>

    <!-- 空状态：默认文案「没有匹配的文件」，父组件可用 #empty 插槽替换 -->
    <van-loading v-if="loading" class="file-list__empty" vertical>加载中…</van-loading>
    <div v-else-if="files.length === 0" class="file-list__empty">
      <!-- 空状态文案交给父组件定制 -->
      <slot name="empty">
        <van-empty description="没有匹配的文件" />
      </slot>
    </div>
    <van-cell-group v-else inset>
      <!-- 每行一个文件，用全局唯一的 file.path 当 key；center 让图标与文字垂直居中 -->
      <van-cell v-for="file in files" :key="file.path" center>
        <template #icon>
          <!-- 受控勾选框：选中与否由父组件的 selected 集合决定，用户点击只上报 toggle，不本地改状态 -->
          <van-checkbox
            :model-value="selected.has(file.path)"
            class="file-list__checkbox"
            @update:model-value="emit('toggle', file.path)"
          />
        </template>
        <!-- ★ 作用域插槽：把 file / sizeLabel 交给父组件渲染  { file, sizeLabel, index }  -->
        <slot name="row" :file="file" :sizeLabel="formatSize(file.fileSize)" :index="files.indexOf(file)">
          <!-- 默认内容：父组件不填时的兜底 -->
          <div class="file-list__row">
            <span class="file-list__name">{{ file.name }}</span>
            <span class="file-list__size">{{ formatSize(file.fileSize) }}</span>
          </div>
        </slot>
        <template #right-icon>
          <div class="file-list__actions">
            <!-- 「打开」= 在系统文件管理器里定位该文件；「导入」只在 kind 为 document 时出现（后端仅支持文档入库） -->
            <van-button size="small" type="primary" plain @click="emit('openFolder', file)">打开</van-button>
            <van-button
              v-if="file.kind === 'document'"
              size="small"
              type="primary"
              plain
              @click="emit('open', file)"
            >
              导入
            </van-button>
          </div>
        </template>
      </van-cell>
    </van-cell-group>
  </div>
</template>

<style scoped>
.file-list__toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px 12px;
}

.file-list__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-list__selected-tag {
  margin-left: auto;
}

.file-list__checkbox {
  margin-right: 8px;
}

.file-list__empty {
  padding: 32px 0;
  justify-content: center;
}

.file-list__row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-list__name {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-list__size {
  flex-shrink: 0;
  color: var(--van-text-color-2);
}
</style>
