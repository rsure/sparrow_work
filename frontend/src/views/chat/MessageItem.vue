<!--
  views/chat/MessageItem.vue —— 单条消息气泡（含工具轨迹）。
  为什么单独拆出来：
    - 工具轨迹的展示规则（等待确认 / 已截断 / 查看完整输出）只写一份；
    - Markdown 渲染必须走 MarkdownView，不允许在别处 v-html。
-->
<script setup lang="ts">
/**
 * MessageItem —— 渲染一条用户/助手消息。
 *
 * 结构（自上而下）：
 *   工具轨迹（仅助手）→ 气泡（Markdown 或纯文本）→ 终止标记
 */
// 计算属性：把"这条消息是否还在流式输出"等派生展示状态集中算好，模板保持简单
import { computed } from 'vue'
// Vant：查看完整输出用的弹窗
import { showDialog, showToast } from 'vant'
// Markdown 渲染入口：唯一允许把 LLM 文本变成 HTML 的组件
import MarkdownView from '@/components/MarkdownView.vue'
// 续读接口：按 continuation_ref 取回被截断工具输出的完整内容
import { fetchToolOutput } from '@/services/chat'
// 对话 store：工具卡片上的「取消」要把请求发回后端（ARCH-6 第 2 档）
import { useChatStore } from '@/stores/chat'
// 类型：气泡模型与工具记录
import type { UIMessage, UIToolCall } from '@/stores/chat'

const props = defineProps<{
  /** 要渲染的一条消息 */
  message: UIMessage
}>()

/** 组件事件 */
const emit = defineEmits<{
  /** 请求预览某个文件（由 ChatView 交给右栏） */
  (e: 'preview', file: NonNullable<UIMessage['files']>[number]): void
}>()

/** 是否是用户消息（决定气泡对齐方向与配色） */
const isUser = computed(() => props.message.role === 'user')

/** 对话 store：取消工具是"对后端运行态的操作"，不归组件自己管 */
const chat = useChatStore()

/**
 * 点工具卡片上的「取消」：请后端在这次工具**开始执行前**跳过它。
 *
 * 为什么还需要后端判断能不能取消：前端只看到"还没出结果"（output 为空），
 * 但工具可能已经跑起来了；已经开始执行的同步工具无法安全中断，
 * 后端会返回明确原因（由 store 弹提示），这里不自己猜。
 *
 * @param tool 要取消的那条工具记录
 */
async function cancelTool(tool: UIToolCall): Promise<void> {
  if (tool.output !== undefined) return
  await chat.cancelTool(tool.name)
}

/**
 * 工具轨迹每一行的状态图标与说明。
 *
 * @param tool 一条工具调用记录
 * @returns 形如 "⚠ 等待确认" / "✓" / "⏳"
 */
function toolBadge(tool: UIToolCall): string {
  if (tool.confirm === 'pending') return '⚠ 等待确认'
  if (tool.confirm === 'approved') return '✅ 已同意'
  if (tool.confirm === 'rejected') return '⛔ 已拒绝'
  return tool.output === undefined ? '⏳' : '✓'
}

/** 工具输出的预览文本：最多展示 6 行，超出交给「查看完整输出」 */
function toolPreview(tool: UIToolCall): string {
  const text = tool.output ?? ''
  const lines = text.split('\n')
  if (lines.length <= 6) return text
  return `${lines.slice(0, 6).join('\n')}\n…（共 ${lines.length} 行）`
}

/**
 * 打开「查看完整输出」：调续读接口把完整内容取回来，用弹窗展示。
 *
 * 为什么要走接口而不是直接从 store 拿：完整内容从来没下发过前端（只存在后端设置库），
 * 这样工具输出再大也不会撑爆 SSE 帧。
 *
 * @param tool 带 continuationRef 的工具记录
 */
async function showFullOutput(tool: UIToolCall): Promise<void> {
  const ref = tool.continuationRef
  if (!ref) {
    showToast('完整输出不可用')
    return
  }
  try {
    const payload = await fetchToolOutput(ref)
    if (!payload.found) {
      showToast('完整输出已被清理')
      return
    }
    // 弹窗不适合放几十万字：截到一个可读长度，并说明还剩多少
    const limit = 8000
    const text = payload.content.length > limit
      ? `${payload.content.slice(0, limit)}\n\n…（共 ${payload.chars} 字符，此处显示前 ${limit} 个）`
      : payload.content
    await showDialog({
      title: `${tool.name} 完整输出（${payload.chars} 字符）`,
      message: text,
      messageAlign: 'left',
      confirmButtonText: '关闭',
    })
  } catch (error) {
    console.error('读取完整输出失败:', error)
    showToast('读取完整输出失败')
  }
}
</script>

<template>
  <div class="msg" :class="isUser ? 'msg--user' : 'msg--assistant'">
    <div class="msg__wrap">
      <!-- 工具调用轨迹：放在气泡上方，让用户看到模型查了哪些东西 -->
      <div v-if="message.tools?.length" class="msg__tools">
        <div v-for="(tool, index) in message.tools" :key="index" class="tool">
          <div class="tool__head">
            <span class="tool__name" :class="{ 'tool__name--confirm': tool.confirm }">
              {{ toolBadge(tool) }} {{ tool.name }}
            </span>
            <!-- EXT-5：被截断时给出原始规模与续读入口 -->
            <span v-if="tool.truncated" class="tool__badge" :title="`原始 ${tool.totalChars} 字符，模型只看到前一段`">
              已截断 · 原始 {{ tool.totalChars }} 字符
            </span>
            <button
              v-if="tool.truncated && tool.continuationRef"
              type="button"
              class="tool__link"
              @click="showFullOutput(tool)"
            >
              查看完整输出
            </button>
            <!-- ARCH-6 第 2 档：只给"还没出结果"的工具显示取消；确认中的工具走弹窗的拒绝 -->
            <button
              v-if="tool.output === undefined && !tool.confirm && message.streaming"
              type="button"
              class="tool__cancel"
              title="请后端在这次工具开始执行前跳过它"
              @click="cancelTool(tool)"
            >
              取消
            </button>
          </div>
          <pre v-if="tool.output" class="tool__output">{{ toolPreview(tool) }}</pre>
        </div>
      </div>

      <!-- 气泡正文：用户消息按纯文本（所见即所发），助手消息走 Markdown -->
      <div v-if="message.content || message.streaming" class="msg__bubble">
        <template v-if="isUser">{{ message.content }}</template>
        <MarkdownView
          v-else
          :content="message.content"
          :files="message.files ?? []"
          :streaming="message.streaming"
          @preview="emit('preview', $event)"
        />
        <span v-if="message.streaming" class="msg__cursor">▍</span>
      </div>

      <!-- 本轮元信息：模型 + token + 耗时（有才算，来自 done 事件的真实 usage） -->
      <div v-if="!isUser && (message.usage || message.model || message.elapsed)" class="msg__meta">
        <span v-if="message.model">{{ message.model }}</span>
        <span v-if="message.usage">
          {{ message.usage.total_tokens }} tokens（入 {{ message.usage.input_tokens }} / 出
          {{ message.usage.output_tokens }}）
        </span>
        <span v-if="message.elapsed">{{ message.elapsed }}s</span>
      </div>

      <div v-if="message.stopped" class="msg__stopped">已终止</div>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  margin-bottom: 18px;
}

.msg--user {
  justify-content: flex-end;
}

.msg--assistant {
  justify-content: flex-start;
}

.msg__wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(760px, 88%);
}

.msg--user .msg__wrap {
  align-items: flex-end;
}

/* ---------- 气泡 ---------- */
.msg__bubble {
  padding: 11px 14px;
  border-radius: var(--radius, 14px);
  font-size: var(--font-size, 14px);
  line-height: 1.65;
  word-break: break-word;
}

.msg--user .msg__bubble {
  background: var(--color-primary);
  color: var(--color-on-primary);
  white-space: pre-wrap;
  border-top-right-radius: 4px;
}

.msg--assistant .msg__bubble {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-text);
  border-top-left-radius: 4px;
}

.msg__cursor {
  display: inline-block;
  margin-left: 2px;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* ---------- 工具轨迹 ---------- */
.msg__tools {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool {
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--color-surface-2);
  border: 1px dashed var(--color-border);
  font-size: 12px;
  color: var(--color-text-muted);
}

.tool__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.tool__name {
  font-weight: 600;
  font-family: var(--font-mono);
}

.tool__name--confirm {
  color: var(--color-warning);
}

.tool__badge {
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--color-warning);
  color: var(--color-warning);
  font-size: 11px;
}

.tool__link {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
  text-decoration: underline;
}

/* 取消：红色、不加下划线，和「查看完整输出」这类辅助动作区分开 */
.tool__cancel {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  color: var(--color-danger);
  font-size: 11px;
  cursor: pointer;
}

.tool__output {
  margin: 4px 0 0;
  max-height: 96px;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
}

/* ---------- 本轮元信息 ---------- */
.msg__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.msg__stopped {
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
