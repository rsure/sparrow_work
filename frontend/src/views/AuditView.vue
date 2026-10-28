<script setup lang="ts">
/**
 * 操作记录页：展示后端落库的工具调用审计记录（谁在什么时候做了什么、结果如何）。
 *
 * 数据来自 GET /api/audit（见 services/audit.ts）。本页只读，不提供任何写操作。
 * 每一条记录都能看出：工具名、操作类型、目标、裁决等级、用户选择与执行结果。
 */
// Vue 生命周期：页面挂载时拉一次数据
import { onMounted, ref } from 'vue'
// Vant 反馈：加载失败的轻提示
import { showToast } from 'vant'
// 审计接口与类型
import { fetch_audit_logs, type AuditLogEntry } from '@/services/audit'

/** 审计记录列表（按时间倒序，后端已排好） */
const logs = ref<AuditLogEntry[]>([])
/** 是否正在加载 */
const loading = ref(false)

/** 拉取审计记录；失败时保留旧数据并提示 */
async function loadLogs(): Promise<void> {
  loading.value = true
  try {
    // 不传 limit：返回多少条由后端契约表决定（默认 100、上限 500）
    logs.value = await fetch_audit_logs()
  } catch (error) {
    console.error('加载审计记录失败:', error)
    showToast('加载审计记录失败')
  } finally {
    loading.value = false
  }
}

/** 操作类型 -> 中文标签 */
function kindLabel(kind: string): string {
  return ({ read: '读取', write: '写入', exec: '执行', net: '联网' } as Record<string, string>)[kind] ?? kind
}

/** 执行结果 -> 中文标签 */
function outcomeLabel(outcome: string): string {
  return ({ ok: '成功', fail: '失败', skipped: '未执行' } as Record<string, string>)[outcome] ?? outcome
}

/** 裁决等级 + 用户选择 -> 给用户看的一句话（deny/rejected 用红色提醒） */
function decisionLabel(row: AuditLogEntry): string {
  if (row.decision === 'approved') return '已同意'
  if (row.decision === 'rejected') return '已拒绝'
  if (row.level === 'deny') return '已拒绝'
  return ({ allow: '放行', ask: '需确认' } as Record<string, string>)[row.level] ?? row.level
}

/** 是否属于"被拦截/被拒绝"的记录（用于红色标记） */
function isBlocked(row: AuditLogEntry): boolean {
  return row.level === 'deny' || row.decision === 'rejected'
}

onMounted(loadLogs)
</script>

<template>
  <div class="audit-page">
    <div class="audit-page__header">
      <span class="audit-page__title">操作记录</span>
      <van-button size="mini" plain @click="loadLogs">刷新</van-button>
    </div>

    <van-loading v-if="loading" class="audit-page__loading" vertical>加载中…</van-loading>
    <van-empty v-else-if="logs.length === 0" description="还没有操作记录" />
    <div v-else class="audit-page__list">
      <div v-for="row in logs" :key="row.id" class="audit-item" :class="{ 'audit-item--blocked': isBlocked(row) }">
        <div class="audit-item__head">
          <span class="audit-item__time">{{ row.created_at }}</span>
          <span class="audit-item__tool">{{ row.tool }}</span>
          <van-tag :type="row.kind === 'exec' ? 'danger' : row.kind === 'write' ? 'warning' : row.kind === 'net' ? 'primary' : 'default'">
            {{ kindLabel(row.kind) }}
          </van-tag>
          <van-tag :type="isBlocked(row) ? 'danger' : 'default'">{{ decisionLabel(row) }}</van-tag>
          <span class="audit-item__outcome">{{ outcomeLabel(row.outcome) }}</span>
        </div>
        <div class="audit-item__target" :title="row.target">{{ row.target }}</div>
        <div v-if="row.detail" class="audit-item__detail">{{ row.detail }}</div>
        <div v-if="row.output_digest" class="audit-item__output">{{ row.output_digest }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.audit-page {
  padding: 12px 0;
}

.audit-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 12px;
}

.audit-page__title {
  font-size: 16px;
  font-weight: 600;
}

.audit-page__loading {
  padding: 32px 0;
  justify-content: center;
}

.audit-page__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.audit-item {
  padding: 10px 12px;
  border: 1px solid var(--van-border-color, #ebedf0);
  border-radius: 8px;
  background: var(--van-gray-1, #f7f8fa);
}

/* 被拦截/被拒绝的记录用淡红底提醒 */
.audit-item--blocked {
  background: rgba(255, 76, 76, 0.06);
  border-color: rgba(255, 76, 76, 0.3);
}

.audit-item__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.audit-item__time {
  font-size: 12px;
  color: var(--van-text-color-3, #c8c9cc);
}

.audit-item__tool {
  font-size: 13px;
  font-weight: 600;
  color: var(--van-text-color, #323233);
}

.audit-item__outcome {
  margin-left: auto;
  font-size: 12px;
  color: var(--van-text-color-2, #969799);
}

.audit-item__target {
  margin-top: 6px;
  font-size: 13px;
  color: var(--van-text-color, #323233);
  word-break: break-all;
}

.audit-item__detail,
.audit-item__output {
  margin-top: 4px;
  font-size: 12px;
  color: var(--van-text-color-2, #969799);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
