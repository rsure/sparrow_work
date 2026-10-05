<script setup lang="ts">
/**
 * 诊断页：健康检查 + 运行环境 + 一键导出诊断包（OPS-3）。
 *
 * 为什么放在这个页面而不是设置页：
 *    「导出诊断包」是出问题时才会用的动作，跟着"健康状态"一起看最顺手；
 *    设置页负责"配置"，这里负责"体检与取证"。
 */
// Vue：ref 存可变状态，computed 派生按钮文案，onMounted 拉一次概要
import { computed, onMounted, ref } from 'vue' // 响应式工具
// Vant：轻提示
import { showToast } from 'vant'

import HealthResult from '@/components/HealthResult.vue' // 结果展示子组件：把健康数据或错误渲染成卡片
import { buildUrl, fetchHealth, type HealthData } from '@/services' // 接口层：buildUrl / fetchHealth / HealthData
import {
  exportDiagnosticPackage,
  fetchDiagnosticSummary,
  saveBlob,
  type DiagnosticSummary,
} from '@/services/diagnostic' // 诊断接口：概要 + 诊断包导出

/** 是否正在请求健康接口：true 时按钮禁用并显示「检查中…」 */
const loading = ref(false)
/** 最近一次成功拿到的健康数据；未请求或失败时为 null */
const data = ref<HealthData | null>(null)
/** 最近一次失败的提示文案；成功时为空串 */
const error = ref('')
/** 最近一次检查的时刻（本地时间字符串），用于告诉用户数据新鲜度 */
const checkedAt = ref('')

/** 诊断概要（版本 / 库版本 / 日志大小 / 轨迹条数） */
const summary = ref<DiagnosticSummary | null>(null)
/** 是否正在导出诊断包 */
const exporting = ref(false)

/** 按钮文案：请求中显示「检查中…」，已有数据时提示可重新检查 */
const buttonText = computed(() => {
  if (loading.value) return '检查中…'
  return data.value ? '重新检查健康状态' : '检查健康状态'
})

/** 日志大小的可读形式 */
const logSize = computed(() => {
  const bytes = summary.value?.log_bytes ?? 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
})

onMounted(loadSummary)

/** 拉概要；失败只提示，不影响健康检查按钮 */
async function loadSummary(): Promise<void> {
  try {
    summary.value = await fetchDiagnosticSummary()
  } catch (err) {
    console.error('加载诊断概要失败:', err)
  }
}

/**
 * 点击「检查健康状态」按钮的处理函数：
 * 请求后端 /api/health，成功写入 data，失败写入 error，两种情况都记录检查时刻。
 */
async function handleCheckHealth(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchHealth()
  } catch (err) {
    data.value = null
    // ApiError 也是 Error 子类，这里统一取 message 展示
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkedAt.value = new Date().toLocaleTimeString()
    loading.value = false
  }
}

/** 导出诊断包并保存到本地 */
async function handleExport(): Promise<void> {
  exporting.value = true
  try {
    const pkg = await exportDiagnosticPackage()
    saveBlob(pkg.blob, pkg.filename)
    showToast('诊断包已导出')
  } catch (err) {
    console.error('导出诊断包失败:', err)
    showToast(err instanceof Error ? err.message : '导出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <section class="home">
    <div class="home__hero">
      <h1>诊断与运行环境</h1>
      <p class="muted">
        查看后端健康状态与运行环境；出问题时可以一键导出诊断包（含日志尾部、脱敏配置、
        库结构与最近的执行轨迹）。
      </p>
      <div class="home__actions">
        <button class="btn" type="button" :disabled="loading" @click="handleCheckHealth">
          {{ buttonText }}
        </button>
        <code class="home__endpoint">{{ buildUrl('/health') }}</code>
      </div>
    </div>

    <div class="card home__result">
      <HealthResult :data="data" :error="error" :checked-at="checkedAt" />
    </div>

    <!-- 环境信息 + 导出诊断包 -->
    <div class="card diag">
      <div class="diag__head">
        <div>
          <h2 class="diag__title">运行环境</h2>
          <p class="diag__hint">
            诊断包已脱敏（密钥不会出现在里面），适合发给开发者排查问题。
          </p>
        </div>
        <button class="btn" type="button" :disabled="exporting" @click="handleExport">
          {{ exporting ? '打包中…' : '导出诊断包' }}
        </button>
      </div>

      <dl v-if="summary" class="diag__grid">
        <dt>版本</dt>
        <dd>{{ summary.version }}{{ summary.packaged ? '（打包运行）' : '（开发运行）' }}</dd>
        <dt>Python</dt>
        <dd>{{ summary.python }}</dd>
        <dt>系统</dt>
        <dd>{{ summary.platform }}</dd>
        <dt>数据库</dt>
        <dd>{{ summary.db_revision || '未记录' }} · {{ summary.tables }} 张表</dd>
        <dt>日志</dt>
        <dd :title="summary.log_file">{{ logSize }} · {{ summary.log_file }}</dd>
        <dt>轨迹</dt>
        <dd>{{ summary.trace_events }} 条（最近）</dd>
      </dl>
      <p v-else class="diag__hint">正在读取环境信息…</p>
    </div>
  </section>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.home__hero h1 {
  font-size: 28px;
}

.home__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 20px;
}

.home__endpoint {
  font-size: 12px;
  color: var(--color-text-muted);
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 4px 8px;
}

.home__result {
  min-height: 160px;
}

.diag {
  padding: 18px 20px;
}

.diag__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.diag__title {
  margin: 0 0 4px;
  font-size: 15px;
}

.diag__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.diag__grid {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 6px 12px;
  margin: 14px 0 0;
  font-size: 12px;
}

.diag__grid dt {
  color: var(--color-text-muted);
}

.diag__grid dd {
  margin: 0;
  color: var(--color-text);
  word-break: break-all;
}
</style>
