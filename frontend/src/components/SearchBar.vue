<!-- ✅ components/SearchBar.vue -->
<script setup lang="ts">
/**
 * SearchBar.vue —— 扫描结果页顶部的「搜索 + 筛选 + 排序」工具条（Vant 版本）。
 * 职责：把用户输入的关键词、类型筛选、排序字段、排序方向用自定义事件上报给父组件；
 * 自身不持有筛选状态、不做过滤计算（真正的过滤/排序在 composables/useFileFilter.ts 里）。
 * 因此父组件要这样用：v-model:keyword / v-model:kind / v-model:sort-field / v-model:sort-order。
 */
/*

要求：
1. props：`keyword: string`、`kind: FileKind | null`、`sortField: SortField`、`sortOrder: SortOrder`、`matchCount: number`
2. `defineEmits` 用**元组语法**，声明 5 个事件：
   - `update:keyword` → `[value: string]`
   - `update:kind` → `[value: FileKind | null]`
   - `update:sortField` → `[value: SortField]`
   - `update:sortOrder` → `[value: 'asc' | 'desc']`
   - `reset` → `[]`
3. 组件内**绝对不许**写 `props.keyword = ...` 这类赋值
4. 父组件用 `v-model:keyword` / `v-model:kind` / `v-model:sort-field` / `v-model:sort-order` 绑四个值
*/

// 类型-only 导入：FileKind 约束文件类型取值，SortField 约束可排序字段，仅参与类型检查、不会打进产物
import type { FileKind, SortField } from '@/services/file'
// 运行时导入：FILE_KINDS 是全部文件大类的有序数组，用来动态生成「全部类型」下拉的选项
import { FILE_KINDS } from '@/services/file'

interface Props {
  /** 当前搜索关键词，父组件持有；本组件只读，改动通过 emit('update:keyword') 上报 */
  keyword: string
  /** 当前选中的文件类型；null 表示「全部类型」（Vant 的 options 不支持 null，见下方 KIND_OPTIONS） */
  kind: FileKind | null
  /** 当前排序字段，取值 name / fileSize / modifiedAt / kind */
  sortField: SortField
  /** 当前排序方向：'asc'=升序（小的/旧的在前），'desc'=降序 */
  sortOrder: 'asc' | 'desc'
  /** 当前过滤后命中的文件条数，仅用于展示「找到 N 项」文案 */
  matchCount: number
}
/** 父组件传入的只读属性集合；本组件不允许直接修改，只能 emit 事件请父组件改 */
const props = defineProps<Props>()

/** ★ 元组语法（Vue 3.3+）：emit( 处有参数名提示 */
// https://cn.vuejs.org/guide/components/events 组件事件
// 在组件的模板表达式中，可以直接使用 $emit 方法触发自定义事件 (例如：在 v-on 的处理函数中)：
// 父组件可以通过 v-on (缩写为 @) 来监听事件：

/*
2. ⚠️ **故意错一次**：`emit('chnage', 'x')` 和 `emit('update:kind', 'document')`
   （注意：`'document'` 是合法 `FileKind`，但这里故意传 `string` 字面量），
   分别贴出两条 `pnpm typecheck` 报错
*/

const emit = defineEmits<{
  /** 搜索词变化：上报新关键词，对应父组件的 v-model:keyword */
  'update:keyword': [value: string]
  /** 类型筛选变化：上报新类型，传 null 表示「全部类型」，对应 v-model:kind */
  'update:kind': [value: FileKind | null]
  /** 排序字段变化：上报新字段名，对应 v-model:sort-field */
  'update:sortField': [value: SortField]
  /** 排序方向变化：上报 'asc' 或 'desc'，对应 v-model:sort-order */
  'update:sortOrder': [value: 'asc' | 'desc']
  /** 点击「清空」：请求父组件重置全部筛选条件（无参数事件写成空元组） */
  reset: [] // 无参数事件写成空元组
}>()

//emit('chnage', 'x')
//emit('update:kind', 'document') // ❌ 直接改 prop

/** 文件类型 → 中文名 映射表，用于下拉里把 'document' 显示成「文档」 */
const KIND_LABEL: Record<FileKind, string> = {
  document: '文档',
  image: '图片',
  video: '视频',
  audio: '音频',
  archive: '压缩包',
  code: '代码',
  other: '其他',
}

/** 排序字段 → 中文名 映射表，用于排序下拉的选项文案 */
const SORT_FIELD_LABEL: Record<SortField, string> = {
  fileSize: '按大小',
  name: '按名称',
  modifiedAt: '按修改时间',
  kind: '按类型',
}

/** van-dropdown-item 的 options 里 value 不支持 null，用 '' 代表「全部类型」 */
const KIND_OPTIONS = [
  { text: '全部类型', value: '' },
  ...FILE_KINDS.map((k) => ({ text: KIND_LABEL[k], value: k })),
]

/** 把 SORT_FIELD_LABEL 转成 van-dropdown-item 需要的 { text, value } 选项数组；key 顺序即下拉展示顺序 */
const SORT_FIELD_OPTIONS = (Object.keys(SORT_FIELD_LABEL) as SortField[]).map((field) => ({
  text: SORT_FIELD_LABEL[field],
  value: field,
}))

/*
📚 背景知识：emit 是干什么的
emit（触发/发出）是 props 的反方向通道：子组件向父组件「上报一件事发生了」，
但不直接传数据回去改父组件的状态。写法是子组件里调用 emit('事件名', 参数)，
父组件用 @事件名="处理函数" 监听。这个模式叫「自定义事件」，和浏览器原生的
click/input 事件监听语法长得一样，因为 Vue 想让你用同一套心智模型处理两者。
为什么不能直接改 prop：因为同一份 prop 数据可能被父组件同时传给好几个子组件，
谁都能改的话数据来源就不唯一了（这叫「单向数据流」，父 → 子永远是唯一权威方向）。
官方文档：指南 · 组件事件 ·
API · defineEmits
*/
/** 搜索框输入/清除时触发：Vant 的 Search 可能回传数字，这里统一转成字符串后再上报 */
function onKeywordUpdate(value: string | number): void {
  emit('update:keyword', String(value))
}

/** 类型下拉选中时触发：把 Vant 传回的 '' 还原成业务语义的 null（表示「全部类型」），其余按 FileKind 上报 */
function onKindChange(value: unknown): void {
  const v = value as string
  emit('update:kind', v === '' ? null : (v as FileKind))
}

/** 排序字段下拉选中时触发：把选中值当作 SortField 上报给父组件 */
function onSortFieldChange(value: unknown): void {
  emit('update:sortField', value as SortField)
}

/** sortOrder 不做下拉，点击标题直接切换 asc/desc */
function onToggleSortOrder(): void {
  emit('update:sortOrder', props.sortOrder === 'desc' ? 'asc' : 'desc')
}
</script>

<template>
  <div class="search-bar">
    <van-search
      :model-value="keyword"
      placeholder="搜索文件名…"
      show-action
      @update:model-value="onKeywordUpdate"
      @clear="emit('update:keyword', '')"
    >
      <template #action>
        <van-button size="small" plain @click="emit('reset')">清空</van-button>
      </template>
    </van-search>

    <!-- auto-locate：父容器 .scan-result 上有 transform（作为 fixed 定位的包含块），
         开启后 Vant 会自动扣除该包含块的顶部偏移，避免下拉面板与触发条之间出现过大间距 -->
    <van-dropdown-menu auto-locate>
      <van-dropdown-item :model-value="kind ?? ''" :options="KIND_OPTIONS" @change="onKindChange" />
      <van-dropdown-item
        :model-value="sortField"
        :options="SORT_FIELD_OPTIONS"
        @change="onSortFieldChange"
      />
      <!-- 排序方向：与其它下拉项同款标题样式，但点击时只切换方向、不展开下拉（@click.stop 阻止打开） -->
      <van-dropdown-item>
        <template #title>
          <span class="order-title" @click.stop="onToggleSortOrder">
            {{ sortOrder === 'desc' ? '↓ 降序' : '↑ 升序' }}
          </span>
        </template>
      </van-dropdown-item>
    </van-dropdown-menu>

    <span class="match-count">找到 {{ matchCount }} 项</span>
  </div>
</template>

<style scoped>
.search-bar {
  display: flex;
  flex-direction: column;
}

.match-count {
  padding: 8px 16px;
  color: var(--van-text-color-2, #969799);
  font-size: 13px;
}
</style>
