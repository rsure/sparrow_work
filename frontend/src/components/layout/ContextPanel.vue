<!--
  components/layout/ContextPanel.vue —— 右栏：上下文 / 文件预览 / 本轮统计。
  改造前这些信息没有固定位置（预览挤在对话左侧、token 数字根本看不到）；
  右栏把它们收在一处，可折叠，不影响主区阅读宽度。
-->
<script setup lang="ts">
/**
 * ContextPanel —— 右侧上下文面板。
 *
 * 两种形态（互斥）：
 *   1. 有文件预览请求 → 显示文件预览（带关闭按钮，关掉回到形态 2）
 *   2. 无预览       → 显示本轮统计（模型 / token / 耗时）+ 工具轨迹摘要 + 工作区
 *
 * 数据全部来自 store，不自己发请求（预览面板自己读文件内容）。
 */
// Vue：computed 派生展示数据
import { computed } from 'vue'
// 文件预览面板：能文本预览的文件在这里打开
import FilePreviewPanel from '@/components/FilePreviewPanel.vue'
// 对话 store：预览目标与本轮统计
import { useChatStore } from '@/stores/chat'
// 工作区 store：展示当前工作区名与根目录
import { useWorkspacesStore } from '@/stores/workspaces'

const chat = useChatStore()
const workspaces = useWorkspacesStore()

/** 最近一条助手消息：token / 模型 / 工具轨迹都挂在它身上 */
const lastAssistant = computed(() => chat.lastAssistant)

/** 当前工作区对象（未创建时为 null） */
const workspace = computed(() => workspaces.activeWorkspace)

/** 子任务状态 → 左侧标记（用字符而不是图标：右栏窄，字符更稳且不需要额外字体） */
const TASK_MARK: Record<string, string> = {
  pending: '○',
  running: '◐',
  success: '●',
  failed: '×',
  verify_failed: '!',
}

/** 子任务状态 → 中文（悬停提示用） */
const TASK_LABEL: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  success: '已完成',
  failed: '执行失败',
  verify_failed: '校验未通过',
}

/**
 * 子任务标记的样式修饰：让"完成/失败"一眼能看出来，而不是全靠读文字。
 *
 * @param status 子任务状态
 * @returns 用于 class 的后缀
 */
function taskTone(status: string): string {
  if (status === 'success') return 'ok'
  if (status === 'running') return 'run'
  if (status === 'failed' || status === 'verify_failed') return 'bad'
  return 'idle'
}

/** 工具轨迹摘要：只取最近 8 条，避免右栏被历史记录撑爆 */
const tools = computed(() => (lastAssistant.value?.tools ?? []).slice(-8))

/**
 * 金额格式化：一次短对话可能只有 0.0003 元，固定两位小数会显示成 ¥0.00，看不出差别。
 *
 * @param value 金额（元）
 * @returns 小于 0.01 时保留 4 位，否则保留 2 位
 */
function formatCost(value: number): string {
  return value < 0.01 ? value.toFixed(4) : value.toFixed(2)
}

/**
 * 关闭预览：回到统计形态。
 */
function closePreview(): void {
  chat.setPreview(null)
}
</script>

<template>
  <aside class="context">
    <!-- 形态 1：文件预览（占满右栏，带关闭） -->
    <template v-if="chat.previewFile">
      <div class="context__head">
        <span class="context__title">文件预览</span>
        <button type="button" class="context__close" @click="closePreview">关闭</button>
      </div>
      <div class="context__preview">
        <FilePreviewPanel :file="chat.previewFile" @close="closePreview" />
      </div>
    </template>

    <!-- 形态 2：本轮上下文 -->
    <template v-else>
      <div class="context__head">
        <span class="context__title">上下文</span>
      </div>

      <!-- TASK：任务计划与进度（只有复杂任务才有；简单对话不显示，避免噪音） -->
      <section v-if="chat.hasTaskPlan" class="block">
        <div class="block__head">
          <p class="block__title">
            任务进度
            <span class="block__count">{{ chat.taskProgress.done }}/{{ chat.taskProgress.total }}</span>
          </p>
        </div>
        <p v-if="chat.taskReason" class="block__hint">{{ chat.taskReason }}</p>
        <ol class="tasks">
          <li v-for="task in chat.taskPlan" :key="task.id" class="task" :class="`task--${taskTone(task.status)}`">
            <span class="task__mark" :title="TASK_LABEL[task.status] || task.status">
              {{ TASK_MARK[task.status] || '○' }}
            </span>
            <div class="task__body">
              <div class="task__title">{{ task.title }}</div>
              <div v-if="task.files.length" class="task__files">{{ task.files.join('、') }}</div>
              <div v-if="task.summary" class="task__summary">{{ task.summary }}</div>
            </div>
          </li>
        </ol>
      </section>

      <section class="block">
        <p class="block__title">本轮</p>
        <dl class="kv">
          <dt>模型</dt>
          <dd>{{ lastAssistant?.model || '—' }}</dd>
          <dt>Token</dt>
          <dd>
            {{ lastAssistant?.usage ? `${lastAssistant.usage.total_tokens}` : '—' }}
            <span v-if="lastAssistant?.usage" class="kv__sub">
              （入 {{ lastAssistant.usage.input_tokens }} / 出 {{ lastAssistant.usage.output_tokens }}）
            </span>
          </dd>
          <dt>费用</dt>
          <dd>
            {{ lastAssistant?.usage?.cost !== undefined ? `¥${formatCost(lastAssistant.usage.cost)}` : '—' }}
          </dd>
          <dt>耗时</dt>
          <dd>{{ lastAssistant?.elapsed ? `${lastAssistant.elapsed}s` : '—' }}</dd>
          <dt>会话</dt>
          <dd class="kv__mono">{{ chat.shortSessionId }}</dd>
        </dl>
        <p class="block__hint">
          Token 来自模型 API 返回的真实 usage，不是估算；换模型后历史轮次仍按当时的模型记账。
        </p>
      </section>

      <!-- 本会话累计：数据来自后端按轮聚合（GET /chat/history/sessions/{id}/usage） -->
      <section class="block">
        <div class="block__head">
          <p class="block__title">本会话累计</p>
          <button type="button" class="block__refresh" @click="chat.refreshUsage()">刷新</button>
        </div>
        <dl class="kv">
          <dt>轮次</dt>
          <dd>{{ chat.usage ? `${chat.usage.turns} 轮` : '—' }}</dd>
          <dt>Token</dt>
          <dd>{{ chat.usage ? chat.usage.total_tokens.toLocaleString() : '—' }}</dd>
          <dt>费用</dt>
          <dd>{{ chat.usage ? `¥${formatCost(chat.usage.cost)}` : '—' }}</dd>
        </dl>
        <p v-if="!chat.usage" class="block__empty">开始对话后这里会显示累计用量</p>
        <p v-else-if="chat.usage.by_model.length > 1" class="block__hint">
          本会话用过 {{ chat.usage.by_model.length }} 个模型，已按各自单价分别记账。
        </p>
      </section>

      <section class="block">
        <p class="block__title">工具轨迹</p>
        <p v-if="tools.length === 0" class="block__empty">本轮还没有工具调用</p>
        <ul v-else class="tools">
          <li v-for="(tool, index) in tools" :key="index" class="tools__item">
            <span class="tools__name">{{ tool.name }}</span>
            <span v-if="tool.truncated" class="tools__flag">截断</span>
          </li>
        </ul>
      </section>

      <section class="block">
        <p class="block__title">工作区</p>
        <p class="block__value">{{ workspace?.name || '未选择' }}</p>
        <p v-if="workspace?.roots?.length" class="block__path">{{ workspace.roots[0] }}</p>
        <p v-else class="block__empty">还没有配置根目录，写入类工具会要求确认</p>
      </section>
    </template>
  </aside>
</template>

<style scoped>
.context {
  display: flex;
  flex-direction: column;
  width: 300px;
  flex: 0 0 300px;
  height: 100%;
  min-height: 0;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
}

.context__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 46px;
  flex: 0 0 46px;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-border);
}

.context__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.context__close {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: 12px;
  cursor: pointer;
}

.context__preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

/* ---------- 信息块 ---------- */
.block {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
}

.block__count {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

.tasks {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.task__mark {
  flex: none;
  width: 14px;
  text-align: center;
  font-family: var(--font-mono);
}

.task--ok .task__mark {
  color: var(--color-success, #22c55e);
}

.task--run .task__mark {
  color: var(--color-primary);
}

.task--bad .task__mark {
  color: var(--color-danger);
}

.task--run .task__title {
  color: var(--color-text);
}

.task__body {
  min-width: 0;
  flex: 1;
}

.task__title {
  color: var(--color-text);
}

.task--idle .task__title {
  color: var(--color-text-muted);
}

.task__files {
  font-family: var(--font-mono);
  font-size: 10px;
  opacity: 0.8;
  word-break: break-all;
}

.task__summary {
  font-size: 11px;
  opacity: 0.85;
}

.block__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.block__refresh {
  appearance: none;
  border: none;
  background: none;
  padding: 0 0 8px;
  font-size: 11px;
  color: var(--color-text-muted);
  cursor: pointer;
}

.block__refresh:hover {
  color: var(--color-primary);
}

.block__title {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.block__hint,
.block__empty {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.block__value {
  margin: 0;
  font-size: 12px;
  color: var(--color-text);
}

.block__path {
  margin: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-muted);
  word-break: break-all;
}

.kv {
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 6px 8px;
  margin: 0;
  font-size: 12px;
}

.kv dt {
  color: var(--color-text-muted);
}

.kv dd {
  margin: 0;
  color: var(--color-text);
}

.kv__sub {
  color: var(--color-text-muted);
  font-size: 11px;
}

.kv__mono {
  font-family: var(--font-mono);
  font-size: 11px;
}

.tools {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.tools__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--color-text-muted);
  padding: 3px 6px;
  border-radius: 6px;
  background: var(--color-surface-2);
}

.tools__flag {
  color: var(--color-warning);
}
</style>
