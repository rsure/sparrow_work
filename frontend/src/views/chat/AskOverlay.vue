<!--
  views/chat/AskOverlay.vue —— 统一的「停下来问用户」弹层（UX-7 授权 + UX-9 预算）。
  为什么不用 Vant 的 showConfirmDialog：
    1. workspace 模式要在弹层里加「记住本工作区授权」勾选框，命令式弹窗塞不进自定义内容；
    2. 确认与预算两种询问的按钮语义不同（同意/拒绝 vs 继续/停止），受控组件更好表达；
    3. 受控弹层能被 store 驱动，异步流程（等待用户回答的 Promise）读起来更直白。
-->
<script setup lang="ts">
/**
 * AskOverlay —— 渲染当前待回答的询问。
 *
 * 数据来源：`chat.pendingAsk`（confirm / budget 二选一），回答通过 `chat.resolveAsk()` 提交。
 * 弹层不自己发请求：提交后由 store 的发送循环继续调用 /chat/resume。
 */
// Vue：computed 派生展示文案，onMounted/onBeforeUnmount 管理 Esc 快捷键
import { computed, onBeforeUnmount, onMounted } from 'vue'
// 对话 store：询问状态与提交入口，以及确认弹窗的中文标签映射
import {
  CONFIRM_ARG_LABEL,
  CONFIRM_TITLE,
  describeConfirmArgs,
  useChatStore,
} from '@/stores/chat'

const store = useChatStore()

/** 当前是否是"操作确认"（另一种是预算超限） */
const isConfirm = computed(() => store.pendingAsk?.kind === 'confirm')

/** 弹层标题：确认用后端给的标题，预算用固定文案 */
const title = computed<string>(() => {
  if (!store.pendingAsk) return ''
  if (store.pendingAsk.kind === 'budget') return '预算已超出'
  const req = store.pendingAsk.request
  return req.title || CONFIRM_TITLE[req.tool] || `确认执行 ${req.tool}`
})

/** 弹层正文：后端已经拼好中文说明时直接用 */
const message = computed<string>(() => {
  const ask = store.pendingAsk
  if (!ask) return ''
  if (ask.kind === 'budget') return ask.request.message || '本轮已超出预算。'
  // 后端没给 message 时，用入参拼一段"标签：值"的说明，别让弹窗只剩标题
  return ask.request.message || describeConfirmArgs(ask.request.args)
})

/** 需要展示的工具名（预算询问没有工具名） */
const toolName = computed<string>(() => (store.confirmAsk ? store.confirmAsk.tool : ''))

/** 参数清单：确认弹层里把入参逐条列出来，用户靠它判断影响范围 */
const argEntries = computed<Array<[string, string]>>(() => {
  const args = store.confirmAsk?.args
  if (!args) return []
  return Object.entries(args).map(([key, value]) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    return [CONFIRM_ARG_LABEL[key] ?? key, text.length > 200 ? `${text.slice(0, 200)}…` : text]
  })
})

/** 是否显示「记住本工作区授权」勾选（后端说可以才有） */
const canRemember = computed<boolean>(() => Boolean(store.confirmAsk?.can_remember))

/**
 * 提交选择。
 *
 * @param approved 确认弹层=同意执行；预算弹层=继续执行
 */
function submit(approved: boolean): void {
  store.resolveAsk(approved)
}

/**
 * Esc = 拒绝 / 停止（安全方向：不确定时不做有风险的事）。
 *
 * @param event 键盘事件
 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && store.pendingAsk) submit(false)
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="store.pendingAsk" class="ask">
    <div class="ask__mask" />
    <div class="ask__card" role="dialog" aria-modal="true">
      <header class="ask__head">
        <span class="ask__badge" :class="isConfirm ? 'ask__badge--warn' : 'ask__badge--danger'">
          {{ isConfirm ? '需要确认' : '预算熔断' }}
        </span>
        <h3 class="ask__title">{{ title }}</h3>
      </header>

      <p class="ask__message">{{ message }}</p>

      <!-- 确认弹层：把工具名与入参摊开，避免用户盲点"同意" -->
      <template v-if="isConfirm">
        <p v-if="toolName" class="ask__tool">工具：<code>{{ toolName }}</code></p>
        <dl v-if="argEntries.length" class="ask__args">
          <template v-for="[key, value] in argEntries" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </template>
        </dl>
        <label v-if="canRemember" class="ask__remember">
          <input v-model="store.rememberWorkspace" type="checkbox" />
          记住本工作区授权（以后这个工具在本工作区不再询问）
        </label>
      </template>

      <footer class="ask__actions">
        <button type="button" class="ask__btn" @click="submit(false)">
          {{ isConfirm ? '拒绝' : '停止本轮' }}
        </button>
        <button
          type="button"
          class="ask__btn ask__btn--primary"
          :class="{ 'ask__btn--danger': !isConfirm }"
          @click="submit(true)"
        >
          {{ isConfirm ? '同意执行' : '继续执行' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.ask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.ask__mask {
  position: absolute;
  inset: 0;
  background: rgba(2, 6, 23, 0.55);
  backdrop-filter: blur(2px);
}

.ask__card {
  position: relative;
  width: min(560px, 100%);
  max-height: 80vh;
  overflow-y: auto;
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: calc(var(--radius, 14px) + 2px);
  box-shadow: 0 24px 60px rgba(2, 6, 23, 0.45);
  padding: 18px 20px 16px;
}

.ask__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.ask__badge {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.ask__badge--warn {
  color: var(--color-warning);
  border: 1px solid var(--color-warning);
}

.ask__badge--danger {
  color: var(--color-danger);
  border: 1px solid var(--color-danger);
}

.ask__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.ask__message {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.ask__tool {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.ask__tool code {
  font-family: var(--font-mono);
  color: var(--color-primary);
}

.ask__args {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 6px 10px;
  margin: 0 0 10px;
  padding: 10px;
  border: 1px dashed var(--color-border);
  border-radius: 8px;
  background: var(--color-surface-2);
  font-size: 12px;
}

.ask__args dt {
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.ask__args dd {
  margin: 0;
  word-break: break-all;
  font-family: var(--font-mono);
}

.ask__remember {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-muted);
  cursor: pointer;
}

.ask__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.ask__btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text);
  border-radius: 9px;
  padding: 7px 16px;
  font-size: 13px;
  cursor: pointer;
}

.ask__btn:hover {
  border-color: var(--color-primary);
}

.ask__btn--primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 600;
}

.ask__btn--danger {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: #fff;
}
</style>
