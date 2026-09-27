<!--
  views/chat/MessageList.vue —— 消息流（滚动容器 + 空态 + 阶段提示）。
  职责很窄：只负责"把消息列表铺出来并跟随滚动"，状态全部来自 chat store。
-->
<script setup lang="ts">
/**
 * MessageList —— 消息列表渲染与自动滚动。
 *
 * 为什么自动滚动放在这里：滚动位置是 DOM 的职责，store 不该知道 DOM。
 * 监听"消息条数 / 最后一条内容长度 / 阶段提示"三个信号即可覆盖流式追加与工具执行。
 */
// Vue：ref 拿容器，nextTick 等 DOM 更新后再滚，watch 监听新内容
import { nextTick, ref, watch } from 'vue'
// 对话 store：消息与阶段提示的唯一来源
import { useChatStore } from '@/stores/chat'
// 单条消息组件
import MessageItem from '@/views/chat/MessageItem.vue'
// 文件条目类型：预览事件携带的数据
import type { ChatFileRef } from '@/services/chat'

const store = useChatStore()

/** 滚动容器 */
const listRef = ref<HTMLElement | null>(null)

/** 把列表滚到底部（等新气泡入列之后再改 scrollTop，否则算出来的高度是旧的） */
function scrollToBottom(): void {
  void nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 三个信号任一变化都表示"有新内容": 条数变了、最后一条变长了、状态行变了
watch(
  () => [
    store.messages.length,
    store.messages[store.messages.length - 1]?.content.length ?? 0,
    store.statusText,
  ],
  scrollToBottom,
)

/** 点击文件胶囊时把文件交给右栏预览（右栏是全局的，所以写进 store） */
function onPreview(file: ChatFileRef): void {
  store.setPreview(file)
}
</script>

<template>
  <div ref="listRef" class="msg-list">
    <!-- 空态：给两条最常用的上手路径，而不是一句"暂无数据" -->
    <div v-if="store.messages.length === 0" class="msg-list__empty">
      <p class="msg-list__empty-title">开始对话</p>
      <p class="msg-list__empty-hint">
        直接提问，AI 会自己决定读文件还是查知识库；输入
        <code>\doc -h</code> 可以看知识库指令的全部用法。
      </p>
    </div>

    <MessageItem
      v-for="(message, index) in store.messages"
      :key="index"
      :message="message"
      @preview="onPreview"
    />

    <!-- 阶段提示：思考中 / 正在执行工具 -->
    <div v-if="store.statusText" class="msg-list__status">{{ store.statusText }}</div>
  </div>
</template>

<style scoped>
.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px 28px 12px;
  scroll-behavior: smooth;
}

.msg-list__empty {
  max-width: 460px;
  margin: 12vh auto 0;
  text-align: center;
  color: var(--color-text-muted);
}

.msg-list__empty-title {
  margin: 0 0 8px;
  font-size: 18px;
  color: var(--color-text);
}

.msg-list__empty-hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
}

.msg-list__empty-hint code {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  font-family: var(--font-mono);
  font-size: 12px;
}

.msg-list__status {
  padding: 4px 4px 8px;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
