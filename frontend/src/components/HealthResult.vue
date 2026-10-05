<script setup lang="ts">
/**
 * HealthResult.vue —— 后端健康检查结果的只读展示组件。
 * 使用场景：首页点击「检查后端」之后，把请求结果（数据 / 错误 / 检查时间）交给它渲染。
 * 它自己不发请求、不持有状态，三种界面（连接失败 / 有数据 / 未检查）完全由 props 决定。
 */
// Vue 响应式工具：computed 把 props.data 拍平成「标签-值」表格行，data 变化时自动重算
import { computed } from 'vue'

// 后端健康检查的数据类型：字段与 app/schemas/health.py 的 HealthData 一一对应
import type { HealthData } from '@/services'

const props = defineProps<{
  /** 后端 GET /api/health 返回的数据；还没检查过、或请求失败时为 null */
  data: HealthData | null
  /** 请求失败时的错误信息；空字符串表示「没有错误」（用空串而非 null 是为了模板判断简单） */
  error: string
  /** 本次检查的时间文案，父组件已格式化好（如 2024-05-01 12:00:00）；空字符串表示还没查过 */
  checkedAt: string
}>()

/** 把健康数据拍平成 「标签 + 值」 数组，供模板用 v-for 渲染 <dt>/<dd>；data 为 null 时返回空数组 */
const rows = computed(() => {
  const data = props.data
  if (!data) return [] as Array<{ label: string; value: string }>
  return [
    { label: '服务名', value: data.service },
    { label: '版本', value: data.version },
    { label: '运行环境', value: data.env },
    // 新后端返回 runtime_version；旧 Python 后端只返回 python_version，做兼容回退
    { label: '运行时', value: data.runtime_version ?? data.python_version },
    { label: '平台', value: data.platform },
    { label: '已运行', value: `${data.uptime_seconds}s` },
    { label: '服务器时间', value: data.server_time },
  ]
})
</script>

<template>
  <div class="health-result">
    <div class="health-result__head">
      <span v-if="error" class="badge badge--error">连接失败</span>
      <span v-else-if="data" class="badge badge--ok">● {{ data.status === 'ok' ? '健康' : data.status }}</span>
      <span v-else class="badge badge--idle">未检查</span>
      <span v-if="checkedAt" class="muted health-result__time">检查时间：{{ checkedAt }}</span>
    </div>

    <p v-if="error" class="health-result__error">{{ error }}</p>

    <dl v-else-if="data" class="health-result__list">
      <template v-for="row in rows" :key="row.label">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </template>
    </dl>

    <p v-else class="muted">点击上方按钮，查看后端服务健康状态。</p>
  </div>
</template>

<style scoped>
.health-result__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.health-result__time {
  font-size: 12px;
}

.health-result__error {
  color: var(--color-danger);
  margin: 0;
  word-break: break-all;
}

.health-result__list {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 16px;
  margin: 0;
}

.health-result__list dt {
  color: var(--color-text-muted);
}

.health-result__list dd {
  margin: 0;
  word-break: break-all;
}
</style>
