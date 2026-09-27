<script setup lang="ts">
/**
 * 文件路径胶囊：回答里的一段路径，可点击触发预览或打开文件夹。
 *
 * 交互约定（与产品需求一致）：
 *   - 能预览的文件：单击 → 请求父组件在左侧面板打开预览
 *   - 不能预览的文件：单击 → 打开所在文件夹（相当于"这张纸我打不开，但指给你看在哪"）
 *   - 无论哪种，右侧的下拉菜单都提供"用系统程序打开"与"打开所在文件夹"两个固定项
 *   - 浏览器环境（window.desktop 为空）下两个"打开"动作会置灰并说明原因
 */
// Vue 响应式与计算属性：computed 派生展示用的图标与 title，ref 存「⋯」菜单展开状态
import { computed, ref } from 'vue'
// Vant 反馈：操作结果轻提示
import { showToast } from 'vant'
// 对话服务类型：文件条目结构
import type { ChatFileRef } from '@/services/chat'

/** 组件入参 */
const props = defineProps<{
  /** 该片段对应的文件条目（来自 done 事件的 files） */
  file: ChatFileRef
}>()

/** 组件事件 */
const emit = defineEmits<{
  /** 请求预览：父组件据此在左侧面板加载内容 */
  (e: 'preview', file: ChatFileRef): void
}>()

/** 当前是否运行在 Electron 桌面环境（决定"打开"类动作是否可用） */
const isDesktop = computed<boolean>(() => Boolean(window.desktop?.isDesktop))

/** 按文件类别给出前置图标（vant 图标名） */
const iconName = computed<string>(() => {
  switch (props.file.kind) {
    case 'image':
      return 'photo-o'
    case 'rich':
      return 'description'
    case 'binary':
      return 'cluster-o'
    case 'missing':
      return 'warning-o'
    default:
      return 'notes-o'
  }
})

/** 悬停提示：路径 + 大小 + 不可预览原因 */
const tooltip = computed<string>(() => {
  const parts = [props.file.path]
  if (props.file.size_text) parts.push(props.file.size_text)
  if (!props.file.previewable && props.file.reason) parts.push(props.file.reason)
  return parts.join(' · ')
})

/** 「⋯」菜单是否展开 */
const showMenu = ref(false)

/** 菜单项：桌面环境按可用能力给"用系统程序打开 / 打开所在文件夹"；浏览器环境为空（不显示菜单） */
const menuActions = computed<Array<{ text: string }>>(() => {
  if (!isDesktop.value) return []
  const actions: Array<{ text: string }> = []
  if (window.desktop?.openPath) actions.push({ text: '用系统程序打开' })
  if (window.desktop?.showItemInFolder) actions.push({ text: '打开所在文件夹' })
  return actions
})

/** 菜单选择：按文案分发到对应动作 */
function onMenuSelect(action: { text: string }): void {
  if (action.text === '用系统程序打开') void openWithSystem()
  else void openFolder()
}

/** 点击胶囊：能预览就预览，不能预览就打开所在文件夹 */
async function onClick(): Promise<void> {
  if (props.file.kind === 'missing') {
    showToast('文件已不存在或不可访问')
    return
  }
  if (props.file.previewable) {
    emit('preview', props.file)
    return
  }
  await openFolder()
}

/** 在系统文件管理器中定位该文件（Electron 能力；浏览器环境提示不可用） */
async function openFolder(): Promise<void> {
  const desktop = window.desktop
  if (!desktop?.showItemInFolder) {
    showToast('浏览器调试模式下无法打开本地文件夹，请在桌面应用里操作')
    return
  }
  await desktop.showItemInFolder(props.file.path)
}

/** 用系统默认程序打开文件（Electron 能力；返回非空串表示失败） */
async function openWithSystem(): Promise<void> {
  const desktop = window.desktop
  if (!desktop?.openPath) {
    showToast('浏览器调试模式下无法调用系统程序，请在桌面应用里操作')
    return
  }
  const error = await desktop.openPath(props.file.path)
  if (error) showToast(`打开失败：${error}`)
}
</script>

<template>
  <span class="file-chip" :title="tooltip" @click="onClick">
    <van-icon :name="iconName" />
    <span class="file-chip__name">{{ file.name }}</span>
    <span v-if="!file.previewable && file.kind !== 'missing'" class="file-chip__badge">仅文件夹</span>
    <van-popover
        v-if="menuActions.length"
        v-model:show="showMenu"
        :actions="menuActions"
        placement="bottom-start"
        @select="onMenuSelect"
    >
      <template #reference>
        <van-icon name="ellipsis" class="file-chip__more" @click.stop />
      </template>
    </van-popover>
  </span>
</template>

<style scoped>
/* 胶囊外观：与正文区分开，但不要抢眼到影响阅读 */
.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 6px;
  margin: 0 2px;
  border: 1px solid var(--van-primary-color);
  border-radius: 10px;
  color: var(--van-primary-color);
  cursor: pointer;
  font-size: 0.92em;
}
.file-chip:hover {
  background: rgba(25, 137, 250, 0.08);
}
/* 不可预览时用灰色，暗示"点了是打开文件夹而不是预览" */
.file-chip__badge {
  font-size: 0.75em;
  opacity: 0.7;
}

/* 「⋯」菜单触发图标：与胶囊主体分开，点击不触发胶囊的预览/打开动作 */
.file-chip__more {
  font-size: 0.85em;
  padding: 2px;
  cursor: pointer;
  color: var(--van-primary-color);
}
</style>