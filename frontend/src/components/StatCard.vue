<!-- components/StatCard.vue -->
<script setup lang="ts">
/**
 * StatCard.vue —— 单个「统计数值卡片」，纯展示组件。
 * 使用场景：扫描结果页顶部的指标区（文件总数、总大小、耗时等），父组件把已经格式化好的字符串传进来即可。
 * 设计约定：组件内部不做任何业务计算（数值格式化在父组件完成），它只负责配色与排版。
 */
/*

要求：
1. `interface Props` 含 `label: string`、`value: string`、可选 `hint?: string`、可选 `tone?: 'default' | 'primary' | 'warn'`
2. 用 `withDefaults` 给可选 props 兜底
3. **不许**在组件内部做任何业务计算（数值格式化在父组件做）——这是「纯展示组件」的定义
4. `<style scoped>` 里给三个 tone 各一套配色
*/
// Vue 响应式工具：computed 依据 tone 派生 CSS 类名，配色交给样式表
import { computed } from 'vue'

interface Props {
  /** 卡片标题，如「文件总数」「总大小」 */
  label: string
  /** 主数值，是父组件已格式化好的字符串（如 "128"、"1.5 GB"）；组件不负责单位换算 */
  value: string
  /** 副标题 / 补充说明；可选，默认空字符串，为空时模板里那一行不渲染 */
  hint?: string
  /** 配色主题：default=普通灰底，primary=蓝色强调，warn=橙色警示；默认 default */
  tone?: 'default' | 'primary' | 'warn'
}

/** 用 withDefaults 给可选 props 兜底（hint→''、tone→'default'），避免模板里拿到 undefined */
const props = withDefaults(defineProps<Props>(), { hint: '', tone: 'default' })
/** 由 tone 派生出的 CSS 类名，如 stat-card--primary；具体颜色由下方三套 scoped 样式规则决定 */
const toneClass = computed(() => `stat-card--${props.tone}`)
</script>

<template>
  <div class="stat-card" :class="toneClass">
    <div class="stat-card__label">{{ label }}</div>
    <div class="stat-card__value">{{ value }}</div>
    <div v-if="hint" class="stat-card__hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  flex: 1;
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid transparent;
}

.stat-card__label {
  font-size: 13px;
  color: var(--van-text-color-2, #969799);
}

.stat-card__value {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 600;
  color: var(--van-text-color, #323233);
}

.stat-card__hint {
  margin-top: 2px;
  font-size: 12px;
  color: var(--van-text-color-3, #c8c9cc);
}

.stat-card--default {
  background-color: var(--van-background-2, #f7f8fa);
  border-color: var(--van-border-color, #ebedf0);
}

.stat-card--primary {
  background-color: rgba(25, 137, 250, 0.08);
  border-color: var(--van-primary-color, #1989fa);
}

.stat-card--primary .stat-card__value {
  color: var(--van-primary-color, #1989fa);
}

.stat-card--warn {
  background-color: rgba(255, 151, 106, 0.1);
  border-color: var(--van-warning-color, #ff976a);
}

.stat-card--warn .stat-card__value {
  color: var(--van-warning-color, #ff976a);
}
</style>
