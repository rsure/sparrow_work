<!-- components/FileTree.vue -->
<script setup lang="ts">
/**
 * FileTree.vue —— 目录树递归组件，把扫描结果按「文件夹 / 文件」层级展示出来。
 * 使用场景：扫描结果页的树形视图。组件递归调用自身来渲染任意深度的子节点。
 * 关键约定：展开状态（expanded）由父组件持有、本组件只读——这样可以做到切换页面后展开状态不丢；
 * 折叠/展开、选中都只通过事件上报，组件内部不保存任何状态。
 */
// 文件条目类型：path/name/fileSize/kind/isDirectory/modifiedAt 等字段，本组件的节点类型在它基础上加 children
import type { FileEntry } from '@/services/file'
// Vue 响应式工具：下面用 computed 从 props 派生「是否展开、是否有子节点、缩进样式」等只读值
import { computed } from 'vue'

/**
要求：
1. 递归渲染树，展开状态（`expanded: ReadonlySet<string>`）**由父组件持有**，本组件只读
2. 文件夹显示 ▸/▾，文件不显示箭头但**缩进要留位**（否则同级文件名左边缘不齐）
3. 选中项高亮；点击整行触发 `select` 事件
4. 用 `depth` prop + computed 样式控制缩进（不要写 5 套 class）
5. **必须有 `:key="child.path"`**
 */
export interface TreeNode extends FileEntry {
  /** 子节点列表；文件节点没有该字段（undefined），文件夹节点至少有 1 个元素才显示展开箭头 */
  readonly children?: readonly TreeNode[]
}

interface Props {
  /** 当前要渲染的树节点（文件夹或文件），由父组件传入，递归时把子节点传给自己 */
  node: TreeNode
  /** 已展开文件夹的路径集合，由父组件持有（状态提升），本组件只读不改 */
  expanded: ReadonlySet<string>
  /** 当前选中项的绝对路径；null 表示没有选中项，用于高亮当前行 */
  selectedPath: string | null
  /** 当前层级，从 0 开始，每递归一层 +1；仅用于计算左侧缩进像素 */
  depth?: number
}
/** 给 depth 兜底为 0（顶层调用时父组件可以不传），其余 props 必填 */
const props = withDefaults(defineProps<Props>(), { depth: 0 })

/** 本组件对外的事件：展开/收起某个文件夹、选中某个节点，均交给父组件处理 */
const emit = defineEmits<{
  /** 点击 ▸/▾ 箭头：请求父组件切换该路径的展开状态 */
  toggleExpand: [path: string]
  /** 点击整行：请求父组件把该节点设为选中项（文件夹和文件都会触发） */
  select: [node: TreeNode]
}>()

/** 当前节点是否处于展开状态：拿自身 path 去父组件持有的集合里查 */
const isExpanded = computed(() => props.expanded.has(props.node.path))
/** 是否有子节点：决定显示 ▸/▾ 箭头还是显示占位空白（占位是为了让同级文件名左边缘对齐） */
const hasChildren = computed(() => (props.node.children?.length ?? 0) > 0)
/** 本行的缩进样式：每层 14px，再加 8px 基础左内边距，避免写多套 class */
const indentStyle = computed(() => ({ paddingLeft: `${props.depth * 14 + 8}px` }))
/** 传给子节点递归组件的层级：当前层级 +1，用于让下一层缩进更多 */
const childDepth = computed(() => props.depth + 1)
/** 传给子组件递归调用时的选中高亮 class；选中路径与自身一致时得到 'is-selected'，否则空串 */
const row_selected_class = computed(() => (props.node.path === props.selectedPath ? 'is-selected' : ''))
</script>

<template>
  <li>
    <!-- 整行可点：点哪儿都触发选中；缩进由 indentStyle 动态计算 -->
    <div class="tree-node__row" :style="indentStyle" :class="{ 'is-selected': node.path === selectedPath }"
      @click="emit('select', node)">
      <!-- 有子节点才显示箭头；@click.stop 阻止冒泡，避免展开时顺带把该行选中 -->
      <button v-if="hasChildren" type="button" :aria-expanded="isExpanded"
        @click.stop="emit('toggleExpand', node.path)">
        {{ isExpanded ? '▾' : '▸' }}
      </button>
      <!-- 文件没有箭头，用等宽占位块撑住，保证同级文件名左边缘对齐 -->
      <span v-else class="arrow-placeholder" />
      <span>{{ node.isDirectory ? '📁' : '📄' }}</span>
      <span>{{ node.name }}</span>
    </div>

    <ul v-if="hasChildren && isExpanded">
      <!-- ★ 递归：必须带 :key（path 全局唯一）；子节点的事件原样再往上报，父组件只需监听顶层一次 -->
      <FileTree v-for="child in node.children" :key="child.path" :node="child" :expanded="expanded"
        :selected-path="selectedPath" :depth="childDepth" :class="row_selected_class"
        @toggle-expand="emit('toggleExpand', $event)" @select="emit('select', $event)" />
    </ul>
  </li>
</template>
<style lang="css" scoped>
.is-selected {
  background-color: #e0f7fa;
}
</style>
