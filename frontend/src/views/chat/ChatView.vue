<!--
  views/chat/ChatView.vue —— 对话主视图（三栏布局的中栏）。
  改造前它是 views/scannHistory.vue（1138 行巨石：聊天 + 会话抽屉 + 预览 + 输入挤在一起）。
  现在按职责拆开：
    - 状态与请求 → stores/chat.ts
    - 消息流     → views/chat/MessageList.vue + MessageItem.vue
    - 输入栏     → views/chat/ChatInput.vue
    - 会话列表   → components/layout/Sidebar.vue
    - 文件预览   → components/layout/ContextPanel.vue
  本文件只负责"把这几块摆到一起"以及顶部标题栏。
-->
<script setup lang="ts">
/**
 * ChatView —— 对话页。
 *
 * 顶部一行只放「当前会话标题 + 新建 + 刷新」，其余入口都在左右两栏，
 * 中栏留给内容本身（这是 CC 式布局的核心：操作不抢阅读区）。
 */
// 生命周期：首次进入拉一次文档候选与会话列表
import { onMounted } from 'vue'
// Vant：轻提示（刷新结果）
import { showToast } from 'vant'
// 对话 store：消息、发送、会话
import { useChatStore } from '@/stores/chat'
// 消息流、输入栏与「停下来问用户」弹层（确认 / 预算共用）
import MessageList from '@/views/chat/MessageList.vue'
import ChatInput from '@/views/chat/ChatInput.vue'
import AskOverlay from '@/views/chat/AskOverlay.vue'

const store = useChatStore()

onMounted(() => {
  void store.bootstrap()
})

/** 手动刷新会话列表（别处刚聊过 / 刚导入文档时用） */
async function refresh(): Promise<void> {
  await Promise.all([store.loadSessions(), store.loadDocuments()])
  showToast('已刷新')
}
</script>

<template>
  <section class="chat-view">
    <header class="chat-view__head">
      <div class="chat-view__title">
        <h1>{{ store.title || '新对话' }}</h1>
        <span class="chat-view__meta">
          {{ store.sessionId ? `会话 ${store.shortSessionId}` : '尚未开始' }} ·
          {{ store.messages.length }} 条消息
        </span>
      </div>
      <div class="chat-view__actions">
        <button type="button" class="btn-ghost" :disabled="store.sending" @click="store.newConversation()">
          新建
        </button>
        <button type="button" class="btn-ghost" @click="refresh">刷新</button>
      </div>
    </header>

    <MessageList />
    <ChatInput />

    <!-- 确认（含"记住本工作区"）与预算熔断共用这一个弹层 -->
    <AskOverlay />
  </section>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.chat-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 28px 10px;
  border-bottom: 1px solid var(--color-border);
}

.chat-view__title {
  min-width: 0;
}

.chat-view__title h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-view__meta {
  font-size: 11px;
  color: var(--color-text-muted);
}

.chat-view__actions {
  display: flex;
  gap: 8px;
}

.btn-ghost {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.btn-ghost:hover:not(:disabled) {
  color: var(--color-text);
  border-color: var(--color-primary);
}

.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
