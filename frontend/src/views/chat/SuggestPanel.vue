<!--
  views/chat/SuggestPanel.vue —— 输入栏上方的候选面板（UX 收尾：三个入口合成一个）。
  三块候选互斥，按优先级只显示一块：
    1. `/` 命令     —— 输入以 `/` 开头、命令名还没敲完
    2. `@` 文件     —— 输入末尾有一个没写完的 `@关键词`
    3. `\doc` 文档名 —— 在 `\doc ` / `\doc -d ` 后面还没写完文件名
  为什么做成一个组件而不是三个：
    它们占的是同一块位置（输入框正上方），各写一份布局会立刻出现"高度不一致、切换时会跳"的问题。
  这个组件是**纯展示**的：数据由 ChatInput 传进来，点击只往上抛事件，
  不直接改 store —— 这样它没有任何状态，最好测也最不容易出 bug。
-->
<script setup lang="ts">
// 斜杠命令的类型：候选条目要显示 name / description / source 三个字段
import type { CommandInfo } from '@/services/command'
// `@` 提及的文件类型：显示 name 主行 + rel 副行
import type { MentionFile } from '@/services/file'

/** 面板数据与当前该显示哪一块，全部由父组件（ChatInput）决定 */
const props = defineProps<{
  /** `\doc` 文档名候选（可能为空数组） */
  docNames: string[]
  /** `/` 命令候选（可能为空数组） */
  commands: CommandInfo[]
  /** `@` 文件候选（可能为空数组） */
  mentions: MentionFile[]
  /** `@` 文件候选是否正在加载（决定显示"搜索中…"而不是"没搜到"） */
  mentionLoading: boolean
  /** 当前 `@` 关键词；null=不在提及模式，空串=刚敲下 `@` */
  mentionKeyword: string | null
}>()

/** 点击候选时通知父组件；父组件负责改写输入框内容 */
const emit = defineEmits<{
  /** 点击文档名 */
  (event: 'pick-doc', name: string): void
  /** 点击命令 */
  (event: 'pick-command', command: CommandInfo): void
  /** 点击文件 */
  (event: 'pick-mention', file: MentionFile): void
}>()

/** 命令来源的中文小标签（内置 / 技能），避免在模板里写三元表达式 */
function sourceLabel(source: string): string {
  if (source === 'builtin') return '内置'
  if (source === 'skill') return '技能'
  return source
}

/** 三块里当前该显示哪一块；都为空时返回空串，模板据此整块隐藏 */
function activeMode(): 'command' | 'mention' | 'doc' | '' {
  if (props.commands.length) return 'command'
  if (props.mentionKeyword !== null) return 'mention'
  if (props.docNames.length) return 'doc'
  return ''
}
</script>

<template>
  <div v-if="activeMode()" class="suggest">
    <!-- 1. `/` 命令 -->
    <template v-if="activeMode() === 'command'">
      <div class="suggest__head">
        <span class="suggest__label">命令</span>
        <span class="suggest__tip">点一下填进输入框，再按 Enter 执行</span>
      </div>
      <ul class="suggest__list">
        <li v-for="cmd in commands" :key="cmd.name">
          <button type="button" class="suggest__row" @click="emit('pick-command', cmd)">
            <span class="suggest__row-main">
              <code class="suggest__code">/{{ cmd.name }}</code>
              <span class="suggest__desc">{{ cmd.description }}</span>
            </span>
            <span class="suggest__badge">{{ sourceLabel(cmd.source) }}</span>
          </button>
        </li>
      </ul>
    </template>

    <!-- 2. `@` 文件 -->
    <template v-else-if="activeMode() === 'mention'">
      <div class="suggest__head">
        <span class="suggest__label">工作区文件</span>
        <span class="suggest__tip">插入文件路径，模型会去读它</span>
      </div>
      <p v-if="mentionLoading" class="suggest__empty">搜索中…</p>
      <p v-else-if="!mentions.length" class="suggest__empty">
        没有匹配的文件（先确认左上角已选择工作区）
      </p>
      <ul v-else class="suggest__list">
        <li v-for="file in mentions" :key="file.path">
          <button type="button" class="suggest__row" @click="emit('pick-mention', file)">
            <span class="suggest__row-main">
              <span class="suggest__name">{{ file.name }}</span>
              <span class="suggest__path">{{ file.rel }}</span>
            </span>
            <span class="suggest__badge">{{ file.size_text }}</span>
          </button>
        </li>
      </ul>
    </template>

    <!-- 3. `\doc` 文档名（沿用原来的胶囊样式，保持熟悉感） -->
    <template v-else>
      <div class="suggest__head">
        <span class="suggest__label">文档名</span>
      </div>
      <div class="suggest__chips">
        <button
          v-for="name in docNames"
          :key="name"
          type="button"
          class="suggest__chip"
          @click="emit('pick-doc', name)"
        >
          {{ name }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.suggest {
  padding-bottom: 8px;
}

.suggest__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 0 2px 4px;
}

.suggest__label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.suggest__tip {
  font-size: 11px;
  color: var(--color-text-muted);
  opacity: 0.8;
}

.suggest__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 232px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius, 14px);
  background: var(--color-surface);
}

.suggest__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.suggest__row:hover {
  background: var(--color-surface-2);
}

.suggest__row-main {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.suggest__code {
  flex: none;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--color-primary);
}

.suggest__name {
  flex: none;
  font-size: 12px;
}

.suggest__desc,
.suggest__path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--color-text-muted);
}

.suggest__badge {
  flex: none;
  padding: 0 6px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  font-size: 10px;
  color: var(--color-text-muted);
}

.suggest__empty {
  margin: 0;
  padding: 8px 10px;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius, 14px);
  font-size: 11px;
  color: var(--color-text-muted);
}

.suggest__chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.suggest__chip {
  max-width: 100%;
  padding: 2px 10px;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
</style>
