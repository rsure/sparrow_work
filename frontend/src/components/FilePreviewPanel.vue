<script setup lang="ts">
/**
 * 左侧文件预览面板：显示 AI 回答里被点击的文件内容。
 *
 * 三种渲染方式（对应后端的 kind）：
 *   text  → 纯文本 + 行号（自己按 \n 切行，不引入代码高亮库：本项目没有这个依赖）
 *   image → <img>，src 用后端 /api/file/raw（渲染进程读不了本地文件，必须走后端）
 *   rich / binary → 只显示说明与两个"打开"按钮
 */
// Vue 响应式：ref 存加载状态与内容，computed 派生行号数组
import { computed, ref, watch } from 'vue'
// Vant 反馈与骨架屏：加载中用骨架屏，失败用轻提示
import { showToast } from 'vant'
// 文件接口：预览与清单
import { fetch_file_preview, type FilePreview } from '@/services/file'
// 对话服务类型：文件条目
import type { ChatFileRef } from '@/services/chat'
// 地址拼接：图片直链需要补上后端域名与 /api 前缀
import { buildUrl } from '@/services/http'

/** 组件入参：当前要预览的文件；为 null 表示面板收起 */
const props = defineProps<{ file: ChatFileRef | null }>()

/** 组件事件：请求关闭面板 */
defineEmits<{ (e: 'close'): void }>()

/** 是否正在加载 */
const loading = ref(false)
/** 后端返回的预览结果；null 表示还没加载 */
const preview = ref<FilePreview | null>(null)

/** 文本内容按行切分，供模板渲染行号 */
const lines = computed<string[]>(() => {
  const text = preview.value?.content ?? ''
  return text ? text.split('\n') : []
})

/** 图片直链：后端返回的是 /api 相对地址，这里补全成完整 URL */
const imageUrl = computed<string>(() => {
  if (preview.value?.kind !== 'image' || !preview.value.raw_url) return ''
  return buildUrl(preview.value.raw_url.replace(/^\/api/, ''))
})

/** 是否运行在 Electron 桌面环境 */
const isDesktop = computed<boolean>(() => Boolean(window.desktop?.isDesktop))

/** 拉取预览内容；切换文件时自动重新加载 */
async function load(file: ChatFileRef | null): Promise<void> {
  preview.value = null
  if (!file) return
  loading.value = true
  try {
    preview.value = await fetch_file_preview(file.path)
    if (preview.value?.truncated) showToast('内容过长，仅显示前 20 万字符')
  } catch (e) {
    showToast(`预览失败：${String(e)}`)
  } finally {
    loading.value = false
  }
}

// 监听入参变化：点击不同文件时重新加载；切换为 null 时清空
watch(() => props.file, (f) => void load(f), { immediate: true })

/** 用系统默认程序打开当前文件（rich / binary 场景的主要出口） */
async function openWithSystem(): Promise<void> {
  const target = props.file
  if (!target) return
  const desktop = window.desktop
  if (!desktop?.openPath) {
    showToast('浏览器调试模式下无法调用系统程序，请在桌面应用里操作')
    return
  }
  const error = await desktop.openPath(target.path)
  if (error) showToast(`打开失败：${error}`)
}

/** 在系统文件管理器中定位当前文件 */
async function openFolder(): Promise<void> {
  const target = props.file
  if (!target) return
  const desktop = window.desktop
  if (!desktop?.showItemInFolder) {
    showToast('浏览器调试模式下无法打开本地文件夹，请在桌面应用里操作')
    return
  }
  await desktop.showItemInFolder(target.path)
}
</script>

<template>
  <div class="preview-panel">
    <div class="preview-panel__header">
      <span class="preview-panel__title">{{ file?.name ?? '文件预览' }}</span>
      <van-icon name="cross" class="preview-panel__close" @click="$emit('close')" />
    </div>

    <div v-if="file" class="preview-panel__meta">
      {{ file.path }}<span v-if="file.size_text"> · {{ file.size_text }}</span>
    </div>

    <div class="preview-panel__body">
      <van-loading v-if="loading" class="preview-panel__loading" vertical>加载中…</van-loading>

      <!-- 文本：行号 + 内容 -->
      <div v-else-if="preview?.kind === 'text'" class="preview-panel__text">
        <div v-for="(line, i) in lines" :key="i" class="preview-panel__line">
          <span class="preview-panel__ln">{{ i + 1 }}</span>
          <span class="preview-panel__code">{{ line }}</span>
        </div>
      </div>

      <!-- 图片：走后端 /file/raw 直链 -->
      <img
          v-else-if="preview?.kind === 'image' && imageUrl"
          :src="imageUrl"
          class="preview-panel__image"
          alt="预览图片"
      />

      <!-- rich / binary / 失败：说明 + 打开按钮 -->
      <div v-else class="preview-panel__fallback">
        <p class="preview-panel__reason">{{ preview?.reason || file?.reason || '该格式不支持在页面内预览' }}</p>
        <div v-if="isDesktop" class="preview-panel__actions">
          <van-button size="small" plain type="primary" @click="openWithSystem">用系统程序打开</van-button>
          <van-button size="small" plain @click="openFolder">打开所在文件夹</van-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 面板整体：由父组件给定宽度（chat-layout__preview），这里只负责内部排版 */
.preview-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 40vh;
  box-sizing: border-box;
}

.preview-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--van-border-color, #ebedf0);
}

.preview-panel__title {
  font-size: 14px;
  font-weight: 600;
  word-break: break-all;
}

.preview-panel__close {
  cursor: pointer;
  font-size: 16px;
  color: var(--van-text-color-2, #969799);
}

.preview-panel__meta {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--van-text-color-3, #c8c9cc);
  word-break: break-all;
}

.preview-panel__body {
  flex: 1;
  overflow: auto;
  padding: 8px 12px 12px;
}

.preview-panel__loading {
  padding: 32px 0;
  justify-content: center;
}

/* 文本：等宽 + 行号，保留空白，便于读代码/日志 */
.preview-panel__text {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.preview-panel__line {
  display: flex;
  gap: 8px;
  white-space: pre-wrap;
  word-break: break-all;
}

.preview-panel__ln {
  flex: none;
  min-width: 2.5em;
  text-align: right;
  color: var(--van-text-color-3, #c8c9cc);
  user-select: none;
}

.preview-panel__code {
  white-space: pre-wrap;
}

.preview-panel__image {
  max-width: 100%;
  border-radius: 4px;
}

.preview-panel__fallback {
  padding: 12px 0;
}

.preview-panel__reason {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--van-text-color-2, #969799);
  white-space: pre-wrap;
}

.preview-panel__actions {
  display: flex;
  gap: 8px;
}
</style>