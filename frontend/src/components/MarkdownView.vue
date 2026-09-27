<!--
  components/MarkdownView.vue —— 统一的 Markdown 渲染入口（UX-3）。
  为什么必须只有这一个入口：
    LLM 输出是**不可信内容**。任何地方直接 v-html 都可能被"回答里夹一段 <script> 或 <img onerror>"
    打穿页面（能读到本地 workspace 路径、能发起请求）。所以渲染只有这一条路径：
      markdown-it 出 HTML → DOMPurify 净化 → v-html
    组件外部永远不要自己拼 HTML。

  能力：
    - 标题 / 列表 / 表格 / 引用 / 链接 / 行内代码
    - 代码块：highlight.js 高亮 + 语言标签 + 复制按钮
    - 文件引用：正文里命中的路径渲染成可点击胶囊（复用 FilePathChip）
    - 流式输出：内容每 60ms 最多重渲染一次，避免每个 token 都跑一遍 markdown + 净化
-->
<script setup lang="ts">
/**
 * MarkdownView —— 把一段 Markdown 渲染成安全的 HTML。
 *
 * 两种内容形态：
 *   1. 普通文本：整段走 Markdown；
 *   2. 带文件引用（files 非空）：先切成「文本片段 + 文件片段」，文本片段各自走 Markdown，
 *      文件片段渲染成胶囊 —— 这样胶囊的点击事件是真正的 Vue 事件，而不是往 HTML 里塞 onclick。
 */
// Vue 响应式与生命周期：ref 存渲染结果，watch 监听内容变化，onMounted/onBeforeUnmount 管理复制按钮的事件委托
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
// Markdown 解析器：把 Markdown 文本转成 HTML
import MarkdownIt from 'markdown-it'
// 代码高亮核心：只引 core，再按需注册语言 —— 全量 highlight.js 会把主包撑到 900kB 以上
import hljs from 'highlight.js/lib/core'
// 按需注册的语言包：覆盖本机项目里最常见的代码类型（其余语言自动识别不出高亮，但不会报错）
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import sql from 'highlight.js/lib/languages/sql'
import markdown from 'highlight.js/lib/languages/markdown'
import yaml from 'highlight.js/lib/languages/yaml'
import java from 'highlight.js/lib/languages/java'
import go from 'highlight.js/lib/languages/go'
// XSS 净化：唯一的安全闸门，任何 HTML 都必须过它才能进 DOM
import DOMPurify from 'dompurify'
// 事件委托需要的复制提示：复制成功/失败给用户明确反馈
import { showToast } from 'vant'
// 文件片段切分：正文里的路径 → 可点击胶囊
import { splitFileSegments } from '@/composables/useFileSegments'
// 文件胶囊组件与它的数据类型
import FilePathChip from '@/components/FilePathChip.vue'
import type { ChatFileRef } from '@/services/chat'

const props = withDefaults(
  defineProps<{
    /** 要渲染的 Markdown 原文（LLM 输出的纯文本） */
    content: string
    /** 本轮回答提到的文件清单；为空表示不识别文件引用 */
    files?: ChatFileRef[]
    /** 是否仍在流式输出：true 时降低重渲染频率，避免每个 token 都跑一遍解析 */
    streaming?: boolean
  }>(),
  { files: () => [], streaming: false },
)

/** 组件事件：点击文件胶囊时把预览请求抛给上层 */
const emit = defineEmits<{
  /** 请求预览某个文件（由页面决定在右栏还是弹层展示） */
  (e: 'preview', file: ChatFileRef): void
}>()

/** 渲染结果的片段：html=已净化的 HTML，file=可点击的文件胶囊 */
interface RenderBlock {
  /** 片段类型 */
  kind: 'html' | 'file'
  /** 已净化的 HTML（kind=html 时有） */
  html?: string
  /** 文件信息（kind=file 时有） */
  file?: ChatFileRef
}

// ---------------------------------------------------------------------------
// 注册语言：别名（js/ts/py/sh/html/vue…）也要注册，否则 ```vue 这种常见标记会退化成纯文本
// ---------------------------------------------------------------------------
hljs.registerLanguage('javascript', javascript)
hljs.registerAliases(['js', 'jsx'], { languageName: 'javascript' })
hljs.registerLanguage('typescript', typescript)
hljs.registerAliases(['ts', 'tsx'], { languageName: 'typescript' })
hljs.registerLanguage('python', python)
hljs.registerAliases(['py'], { languageName: 'python' })
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerAliases(['sh', 'shell', 'zsh', 'console'], { languageName: 'bash' })
hljs.registerLanguage('css', css)
hljs.registerLanguage('xml', xml)
hljs.registerAliases(['html', 'vue', 'svg'], { languageName: 'xml' })
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('markdown', markdown)
hljs.registerAliases(['md'], { languageName: 'markdown' })
hljs.registerLanguage('yaml', yaml)
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerLanguage('java', java)
hljs.registerLanguage('go', go)

// ---------------------------------------------------------------------------
// Markdown 实例：只创建一次，所有消息共用（避免每条消息都重新初始化插件链）
// ---------------------------------------------------------------------------
const md = new MarkdownIt({
  // 允许原始 HTML：LLM 有时会用 <br> / <details> 表达结构；安全性由后面的 DOMPurify 负责
  html: true,
  // 裸链接自动变成可点击链接
  linkify: true,
  // 单个换行就换行：中文回答里"回车分段"很常见，按 CommonMark 严格规则会挤成一行
  breaks: true,
  // 不在解析阶段做高亮：改用下面的 fence 规则，才能同时输出语言标签与复制按钮
  highlight: undefined,
})

/** 把任意字符串转成可安全放进 HTML 属性的文本（语言名、语言标签用） */
function escapeAttr(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 渲染一个 fenced code block：高亮 + 语言标签 + 复制按钮。
 *
 * 复制按钮不内联代码（避免超长内容塞进属性），点击时由事件委托读 `code.innerText`。
 */
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  // 语言标记可能带附加信息（```ts title=xxx），只取第一段
  const info = (token.info || '').trim().split(/\s+/)[0]
  const lang = info || 'text'
  const code = token.content
  let highlighted: string
  if (lang !== 'text' && hljs.getLanguage(lang)) {
    highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
  } else {
    // 语言未知（或就是纯文本）：自动识别一次，识别失败则按纯文本输出
    highlighted = hljs.highlightAuto(code).value
  }
  return (
    `<div class="md-code" data-lang="${escapeAttr(lang)}">` +
    `<div class="md-code__bar"><span class="md-code__lang">${escapeAttr(lang)}</span>` +
    `<button type="button" class="md-code__copy" aria-label="复制代码">复制</button></div>` +
    `<pre class="md-code__pre"><code class="hljs">${highlighted}</code></pre>` +
    `</div>`
  )
}

/**
 * 把 Markdown 渲染成**已净化**的 HTML。
 *
 * @param text Markdown 原文
 * @returns 可以交给 v-html 的 HTML 字符串
 */
function renderMarkdown(text: string): string {
  if (!text) return ''
  // 1. 解析成 HTML
  const raw = md.render(text)
  // 2. 净化：显式允许 class（高亮与布局都靠 class），其余按 DOMPurify 默认白名单
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['data-lang'] })
}

/** 当前要渲染的片段列表 */
const blocks = ref<RenderBlock[]>([])

/**
 * 计算片段列表：有文件引用时切分，否则整段渲染。
 *
 * @param content Markdown 原文
 * @param files 文件清单
 * @returns 渲染片段
 */
function buildBlocks(content: string, files: ChatFileRef[]): RenderBlock[] {
  if (!content) return []
  if (!files.length) return [{ kind: 'html', html: renderMarkdown(content) }]

  return splitFileSegments(content, files).map((segment) =>
    segment.type === 'file' && segment.file
      ? { kind: 'file', file: segment.file }
      : { kind: 'html', html: renderMarkdown(segment.text ?? '') },
  )
}

/** 流式期间的重渲染节流句柄（number 是浏览器 setTimeout 的返回类型） */
let pending: number | null = null

/** 立即重算渲染结果（内容定稿后调用） */
function renderNow(): void {
  if (pending !== null) {
    window.clearTimeout(pending)
    pending = null
  }
  blocks.value = buildBlocks(props.content, props.files)
}

/**
 * 安排一次重渲染。
 *
 * 流式输出时每个 token 都会触发 watch，如果每次都跑 markdown + DOMPurify，
 * 长回答会明显掉帧；这里把频率压到 ~16fps，肉眼几乎看不出延迟。
 */
function scheduleRender(): void {
  if (!props.streaming) {
    renderNow()
    return
  }
  if (pending !== null) return
  pending = window.setTimeout(() => {
    pending = null
    blocks.value = buildBlocks(props.content, props.files)
  }, 60)
}

// 内容或文件清单变化就重渲染；immediate 保证首帧就有内容
watch(() => [props.content, props.files, props.streaming], scheduleRender, { immediate: true })

/** 复制按钮的事件委托：从按钮往上找到代码块，读其中的纯文本 */
function onRootClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null
  const button = target?.closest('.md-code__copy') as HTMLElement | null
  if (!button) return
  const block = button.closest('.md-code')
  const code = block?.querySelector('code')
  if (!code) return
  const text = code.textContent ?? ''
  // 浏览器（含 Electron 渲染进程）都支持 navigator.clipboard；不可用时退化为 execCommand
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => showToast('已复制'),
      () => showToast('复制失败，请手动选择'),
    )
    return
  }
  showToast('当前环境不支持自动复制')
}

/** 根节点引用：事件委托挂在它身上（复制按钮是 HTML 字符串生成的，拿不到 Vue 事件） */
const rootRef = ref<HTMLElement | null>(null)

onMounted(() => rootRef.value?.addEventListener('click', onRootClick))
onBeforeUnmount(() => {
  rootRef.value?.removeEventListener('click', onRootClick)
  if (pending !== null) window.clearTimeout(pending)
})
</script>

<template>
  <div ref="rootRef" class="markdown-view">
    <template v-for="(block, index) in blocks" :key="index">
      <!-- 文件胶囊：真正的组件，点击事件能直接冒到页面 -->
      <FilePathChip
        v-if="block.kind === 'file' && block.file"
        :file="block.file"
        @preview="emit('preview', $event)"
      />
      <!-- HTML 片段：已经过 markdown-it + DOMPurify，可以安全 v-html -->
      <div v-else class="markdown-view__html" v-html="block.html" />
    </template>
  </div>
</template>

<style scoped>
/* 容器只负责排版基线；具体元素样式用 :deep 渗透到 v-html 生成的节点里 */
.markdown-view {
  font-size: var(--font-size, 14px);
  line-height: 1.65;
  word-break: break-word;
}

.markdown-view__html {
  display: block;
}

.markdown-view :deep(p) {
  margin: 0 0 0.65em;
}

.markdown-view :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-view :deep(h1),
.markdown-view :deep(h2),
.markdown-view :deep(h3),
.markdown-view :deep(h4) {
  margin: 1em 0 0.45em;
  line-height: 1.35;
  font-weight: 650;
}

.markdown-view :deep(h1) {
  font-size: 1.32em;
}
.markdown-view :deep(h2) {
  font-size: 1.2em;
}
.markdown-view :deep(h3) {
  font-size: 1.08em;
}

.markdown-view :deep(ul),
.markdown-view :deep(ol) {
  margin: 0.35em 0 0.7em;
  padding-left: 1.35em;
}

.markdown-view :deep(li) {
  margin: 0.18em 0;
}

.markdown-view :deep(blockquote) {
  margin: 0.6em 0;
  padding: 0.15em 0 0.15em 0.85em;
  border-left: 3px solid var(--color-border);
  color: var(--color-text-muted);
}

.markdown-view :deep(a) {
  color: var(--color-primary);
  text-decoration: none;
}
.markdown-view :deep(a:hover) {
  text-decoration: underline;
}

.markdown-view :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 1em 0;
}

/* ---------- 表格：窄屏时允许横向滚动，别把气泡撑破 ---------- */
.markdown-view :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 0.94em;
}

.markdown-view :deep(th),
.markdown-view :deep(td) {
  border: 1px solid var(--color-border);
  padding: 6px 10px;
  text-align: left;
}

.markdown-view :deep(th) {
  background: var(--color-surface-2);
  font-weight: 600;
}

/* ---------- 行内代码 ---------- */
.markdown-view :deep(:not(pre) > code) {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  font-family: var(--font-mono);
  font-size: 0.92em;
}

/* ---------- 代码块：语言标签 + 复制按钮 + 高亮底色 ---------- */
.markdown-view :deep(.md-code) {
  margin: 0.7em 0;
  border: 1px solid var(--code-border);
  border-radius: 10px;
  background: var(--code-bg);
  overflow: hidden;
}

.markdown-view :deep(.md-code__bar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 10px;
  border-bottom: 1px solid var(--code-border);
  background: var(--color-surface-2);
}

.markdown-view :deep(.md-code__lang) {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
}

.markdown-view :deep(.md-code__copy) {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.markdown-view :deep(.md-code__copy:hover) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.markdown-view :deep(.md-code__pre) {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: calc(var(--font-size, 14px) - 1px);
  line-height: 1.55;
}

.markdown-view :deep(.md-code__pre code) {
  background: transparent;
  border: none;
  padding: 0;
  white-space: pre;
}

/* ---------- highlight.js 配色：用主题变量自己画，不额外引两套 css 文件 ---------- */
.markdown-view :deep(.hljs-comment),
.markdown-view :deep(.hljs-quote) {
  color: var(--color-text-muted);
  font-style: italic;
}
.markdown-view :deep(.hljs-keyword),
.markdown-view :deep(.hljs-selector-tag),
.markdown-view :deep(.hljs-literal),
.markdown-view :deep(.hljs-built_in) {
  color: var(--hljs-keyword);
}
.markdown-view :deep(.hljs-string),
.markdown-view :deep(.hljs-attr),
.markdown-view :deep(.hljs-template-variable) {
  color: var(--hljs-string);
}
.markdown-view :deep(.hljs-number),
.markdown-view :deep(.hljs-symbol),
.markdown-view :deep(.hljs-bullet) {
  color: var(--hljs-number);
}
.markdown-view :deep(.hljs-title),
.markdown-view :deep(.hljs-name),
.markdown-view :deep(.hljs-section) {
  color: var(--hljs-title);
}
.markdown-view :deep(.hljs-variable),
.markdown-view :deep(.hljs-params),
.markdown-view :deep(.hljs-type) {
  color: var(--color-text);
}
.markdown-view :deep(.hljs-emphasis) {
  font-style: italic;
}
.markdown-view :deep(.hljs-strong) {
  font-weight: 700;
}
</style>
