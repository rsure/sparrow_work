<!--
  views/chat/ChatInput.vue —— 输入栏（UX-6 快捷键 + `\doc` 候选 + `/` 命令 + `@` 文件 + 模型胶囊）。
  为什么用原生 <textarea> 而不是 van-field：
    需要在 keydown 里精确区分 Enter / Shift+Enter / Ctrl+Enter，并且要判断中文输入法组合
    （event.isComposing）。原生 textarea 的行为最可控，也方便做自动增高。
-->
<script setup lang="ts">
/**
 * ChatInput —— 输入、发送、终止，以及三种输入辅助：`\doc` 文档名、`/` 命令、`@` 文件。
 *
 * 快捷键规则（可在设置里改 `input.enter_to_send`）：
 *   - Enter          发送（enterToSend=true 时）
 *   - Shift+Enter    换行（永远换行，不发送）
 *   - Ctrl/⌘+Enter   发送（enterToSend=false 时用它发送）
 *   - Esc            收起模型面板
 *   - 中文输入法选词时的 Enter 一律不发送（isComposing / keyCode 229）
 */
// Vue：computed 双向绑定 store.input，ref 拿 textarea 与本地候选状态，watch 跟随输入变化
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
// Vant：浏览器不支持选择目录时的提示
import { showToast } from 'vant'
// 对话 store：输入内容、发送、终止、候选、命令、模型面板开关
import { useChatStore } from '@/stores/chat'
// 设置 store：读 Enter 行为开关（input.enter_to_send）
import { useSettingsStore } from '@/stores/settings'
// 工作区保存接口：桌面端选完目录后落库（与设置页共用同一份存储）
import { save_workspace } from '@/services/scan'
// 命令类型：点候选时把命令名拼回输入框
import type { CommandInfo } from '@/services/command'
// 文件提及类型：选中候选后把路径插进输入框
import type { MentionFile } from '@/services/file'
// 候选面板：`/` 命令、`@` 文件、`\doc` 文档名三合一（纯展示，点击往上抛事件）
import SuggestPanel from './SuggestPanel.vue'
// 模型选择面板：输入栏胶囊点开它，改的是后端 llm.provider / llm.model
import ModelPicker from './ModelPicker.vue'

const store = useChatStore()
const settings = useSettingsStore()

/** 输入框 DOM 引用（自动增高需要它） */
const textareaRef = ref<HTMLTextAreaElement | null>(null)

/** `@` 文件候选的防抖毫秒数：打字时别每敲一个字母就查一次目录 */
const MENTION_DEBOUNCE_MS = 180

/** 输入内容：直接读写 store，保证左栏新建对话时也能清空 */
const text = computed<string>({
  get: () => store.input,
  set: (value: string) => {
    store.input = value
  },
})

/** Enter 是否直接发送（设置缺失时按 true，符合大多数人的预期） */
const enterToSend = computed<boolean>(() => {
  const value = settings.entries['input.enter_to_send']?.value
  return value === undefined ? true : Boolean(value)
})

/**
 * 执行中插话是否可用（ARCH-6）：读设置 `agent.steering_enabled`。
 *
 * 关闭后行为回到 UX 收尾之前：流式输出期间输入框禁用、只能点「终止」。
 * 设置项还没加载时按 true——插话失败后端会给出明确原因，比"按钮凭空消失"好解释。
 */
const steeringEnabled = computed<boolean>(() => {
  const value = settings.entries['agent.steering_enabled']?.value
  return value === undefined ? true : Boolean(value)
})

/** 当前 `@` 候选（本地状态：只关心"这一次关键词"的结果，不放进 store） */
const mentions = ref<MentionFile[]>([])
/** `@` 候选是否正在搜索（决定面板显示"搜索中…"还是"没搜到"） */
const mentionLoading = ref(false)
/** 防抖计时器句柄；-1 表示当前没有待触发的搜索 */
let mentionTimer = -1
/**
 * 搜索序号：每发起一次 +1。
 * 响应回来时如果序号已经变了，说明用户又敲了字，这次结果直接丢弃——
 * 否则慢的那次会把新的结果覆盖掉，面板会"抖一下"。
 */
let mentionSeq = 0

/**
 * 自适应高度：内容变化时把高度重置再按 scrollHeight 撑开，最多 200px。
 * 不这么做的话，多行输入会出现内部滚动条，看自己写的内容要滚。
 */
function autoResize(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

// 内容变化（含候选点击、发送后清空）都要重算高度
watch(() => store.input, () => void nextTick(autoResize), { immediate: true })

/**
 * 真正去后端搜一次工作区文件。
 *
 * @param keyword `@` 后面的半截关键词；空串表示刚敲下 `@`，让后端随便给一批
 */
async function runMentionSearch(keyword: string): Promise<void> {
  const seq = (mentionSeq += 1)
  const items = await store.searchMentions(keyword)
  // 期间又敲了字：这次结果已经过期，别覆盖更新的结果
  if (seq !== mentionSeq) return
  mentions.value = items
  mentionLoading.value = false
}

// 输入里出现/离开 `@关键词` 时更新候选：进入就防抖搜一次，离开就立刻清空
watch(
  () => store.mentionQuery,
  (keyword) => {
    window.clearTimeout(mentionTimer)
    if (keyword === null) {
      mentions.value = []
      mentionLoading.value = false
      return
    }
    mentionLoading.value = true
    mentionTimer = window.setTimeout(() => void runMentionSearch(keyword), MENTION_DEBOUNCE_MS)
  },
)

/** 组件卸载时清掉还没触发的防抖，避免对已销毁的组件写 ref */
onBeforeUnmount(() => window.clearTimeout(mentionTimer))

/** 输入框占位文案：按"是否在执行中、能不能插话、是不是 `\doc` 指令"三种上下文切换 */
const placeholder = computed<string>(() => {
  if (store.sending) {
    // 执行中：告诉用户现在的 Enter 是什么意思，避免以为会新开一轮
    return steeringEnabled.value
      ? '执行中：Enter 插话（当前工具结束后生效），Shift+Enter 换行'
      : '正在回答中，可以先点「终止」再输入'
  }
  if (store.isDocInput) return '\\doc -l 列出文档 / -d 删除 / -i 导入 / -h 帮助'
  return '输入问题，Enter 发送，Shift+Enter 换行；/ 唤起命令，@ 引用文件…'
})

/** 把焦点还给输入框：点完候选能接着打字，不用再点一下 */
function focusInput(): void {
  void nextTick(() => textareaRef.value?.focus())
}

/**
 * 键盘处理：区分发送与换行，并挡住输入法组合态。
 *
 * @param event 键盘事件
 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    // Esc 只用来收起模型面板；不影响输入内容
    store.closeModelPicker()
    return
  }
  if (event.key !== 'Enter') return
  // 中文/日文输入法正在选词：这个 Enter 属于输入法，不能当成发送
  if (event.isComposing || event.keyCode === 229) return
  if (event.shiftKey) return // Shift+Enter 交给浏览器插换行

  const withModifier = event.ctrlKey || event.metaKey
  const shouldSend = enterToSend.value ? !withModifier : withModifier
  if (!shouldSend) return

  event.preventDefault()
  void submit()
}

/** 发送：内容为空或正在发送时忽略（按钮本身也做了禁用） */
async function submit(): Promise<void> {
  if (!store.input.trim()) return
  // 执行中按 Enter：如果有插话能力，就当成"插话"而不是新开一轮
  if (store.sending) {
    if (steeringEnabled.value) await store.steer()
    return
  }
  await store.send()
  void nextTick(autoResize)
}

/**
 * 点 `/` 候选：把命令名填进输入框，参数留给用户自己敲。
 *
 * 为什么不点一下就执行：`/doc -d 文件名` 这种带参数的命令点一下就跑会误删数据，
 * 而且"点了就发请求"没有任何撤销机会。面板上的提示写的就是"填进输入框再按 Enter"。
 *
 * @param cmd 被点击的命令
 */
function onPickCommand(cmd: CommandInfo): void {
  store.input = cmd.args_hint ? `/${cmd.name} ` : `/${cmd.name}`
  focusInput()
}

/**
 * 点 `@` 候选：把输入框末尾的半截关键词换成完整文件路径。
 *
 * @param file 被选中的文件
 */
function onPickMention(file: MentionFile): void {
  store.insertMention(file)
  focusInput()
}

/** 选择工作区目录（桌面端能力）：选完保存，后续写入类工具都受它限制 */
async function pickWorkspace(): Promise<void> {
  const desktop = window.desktop
  if (!desktop?.selectFolder) {
    showToast('浏览器调试模式下不支持选择本地目录，请在桌面应用里操作')
    return
  }
  const picked = await desktop.selectFolder()
  if (!picked) return
  await save_workspace([picked])
  showToast(`工作区已设为 ${picked}`)
}
</script>

<template>
  <div class="composer">
    <!-- 三块候选合成一个面板：`/` 命令、`@` 文件、`\doc` 文档名 -->
    <SuggestPanel
      :doc-names="store.docSuggestions"
      :commands="store.commandSuggestions"
      :mentions="mentions"
      :mention-loading="mentionLoading"
      :mention-keyword="store.mentionQuery"
      @pick-doc="store.pickDoc"
      @pick-command="onPickCommand"
      @pick-mention="onPickMention"
    />

    <div class="composer__box" :class="{ 'composer__box--busy': store.sending }">
      <textarea
        ref="textareaRef"
        v-model="text"
        class="composer__input"
        rows="1"
        :placeholder="placeholder"
        :disabled="store.sending && !steeringEnabled"
        @keydown="onKeydown"
        @input="autoResize"
      />

      <div class="composer__bar">
        <div class="composer__tools">
          <button type="button" class="composer__tool" title="选择工作区目录" @click="pickWorkspace">
            工作区
          </button>
          <!-- 模型胶囊：显示这轮实际用的模型，点开可切换 -->
          <button
            type="button"
            class="composer__tool composer__model"
            title="切换模型（/model）"
            @click="store.modelPickerOpen = true"
          >
            {{ store.currentModelLabel }}
          </button>
          <span class="composer__hint">{{ store.inputHint }}</span>
          <!-- 插话排队数：让用户知道"这句话还没被模型看到"，而不是以为丢了 -->
          <span v-if="store.steerQueued > 0" class="composer__queued">
            插话排队 {{ store.steerQueued }}
          </span>
        </div>

        <!-- 执行中且开着插话：输入非空时出现「插话」，与「终止」并排（两种完全不同的意图） -->
        <button
          v-if="store.sending && steeringEnabled"
          type="button"
          class="composer__steer"
          :disabled="!store.input.trim() || store.steering"
          @click="submit"
        >
          插话
        </button>
        <button
          v-if="!store.sending"
          type="button"
          class="composer__send"
          :disabled="!store.input.trim()"
          @click="submit"
        >
          发送
        </button>
        <button v-else type="button" class="composer__stop" @click="store.stop()">终止</button>
      </div>
    </div>

    <!-- 模型选择面板：展开时铺满视口，点遮罩或 Esc 关闭 -->
    <ModelPicker :open="store.modelPickerOpen" @close="store.closeModelPicker" />
  </div>
</template>

<style scoped>
.composer {
  padding: 8px 28px 20px;
}

/* ---------- 输入框 ---------- */
.composer__box {
  border: 1px solid var(--color-border);
  border-radius: calc(var(--radius, 14px) + 2px);
  background: var(--color-surface);
  padding: 8px 10px 6px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer__box:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-weak);
}

.composer__box--busy {
  opacity: 0.9;
}

.composer__input {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--color-text);
  font-family: inherit;
  font-size: var(--font-size, 14px);
  line-height: 1.6;
  max-height: 200px;
}

.composer__input::placeholder {
  color: var(--color-text-muted);
}

.composer__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 6px;
}

.composer__tools {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.composer__tool {
  flex: none;
  appearance: none;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  border-radius: 7px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.composer__tool:hover {
  color: var(--color-text);
}

/* 模型胶囊最多显示一截，模型名可能很长（如 gpt-4o-mini-2024-07-18） */
.composer__model {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer__hint {
  font-size: 11px;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 插话排队数：淡黄色小徽标，只在有排队时出现，不抢输入框的注意力 */
.composer__queued {
  flex: 0 0 auto;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--color-warning);
  color: var(--color-warning);
  font-size: 11px;
  white-space: nowrap;
}

.composer__send,
.composer__stop,
.composer__steer {
  appearance: none;
  border: none;
  border-radius: 9px;
  padding: 7px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.12s ease;
}

.composer__send {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.composer__send:disabled,
.composer__steer:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.composer__stop {
  background: transparent;
  border: 1px solid var(--color-danger);
  color: var(--color-danger);
}

/* 插话：实心次要按钮，与红色的「终止」区分开——一个继续、一个结束 */
.composer__steer {
  background: var(--color-surface-2, transparent);
  border: 1px solid var(--color-primary);
  color: var(--color-primary);
  margin-right: 8px;
}

.composer__send:hover:not(:disabled),
.composer__steer:hover:not(:disabled) {
  transform: translateY(-1px);
}
</style>
