<!-- components/SearchInput.vue -->
<script setup lang="ts">
/**
 * SearchInput.vue —— 原生表单版的「搜索框 + 排序方式下拉 + 清空按钮」组合控件。
 * 使用场景：需要学习/演示 v-model 原理时用它（对比 SearchBar.vue 的 Vant 版本）。
 * 本身不持有状态：搜索词与排序字段都通过 v-model 交由父组件持有，本组件只负责把用户操作原样上报。
 */
// 排序字段的联合类型：'name' | 'fileSize' | 'modifiedAt' | 'kind'，用作排序下拉的取值范围
import type { SortField } from '@/services/file'

/** 搜索关键词的双向绑定（v-model="keyword"）：父组件用 v-model 传值，本组件在输入时会更新它 */
const model = defineModel<string>({ required: true })
/** 排序字段的双向绑定（v-model:sort-field）：默认按名称排序，取值必须是 SortField 之一 */
const sortField = defineModel<SortField>('sortField', { default: 'name' })

/** 清空按钮的处理函数：只把搜索词置空，排序字段保持不变；由模板的 @click 触发 */
function clear(): void {
  model.value = ''
}
</script>

<template>
  <!-- 输入即写入 model（v-model 双向绑定），父组件立刻拿到最新关键词 -->
  <input v-model="model" type="search" />
  <!-- 下拉选项的 value 必须与 SortField 的四个字面量完全一致，选中后写回 sortField -->
  <select v-model="sortField">
    <option value="name">按名称</option>
    <option value="fileSize">按大小</option>
    <option value="modifiedAt">按修改时间</option>
    <option value="kind">按类型</option>
  </select>
  <button type="button" @click="clear">清空</button>
</template>
