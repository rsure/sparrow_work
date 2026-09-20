<!--
  components/layout/AppShell.vue —— 三栏骨架（UX-1）。
  布局：
    ┌──────────┬───────────────────────┬──────────────┐
    │ Sidebar  │ TopBar                │ ContextPanel │
    │ 232px    │ ───────────────────── │ 300px(可折叠) │
    │          │ <RouterView />        │              │
    └──────────┴───────────────────────┴──────────────┘
  为什么把"外壳"单独做成组件而不是塞进 App.vue：
    App.vue 只保留一行 `<AppShell />`，以后要做"无边框窗口 / 全屏预览"这类特殊布局，
    换一个外壳组件即可，不用动根组件。
-->
<script setup lang="ts">
/**
 * AppShell —— 全局布局与启动初始化。
 *
 * 启动时做四件事（都只做一次）：
 *   1. 拉设置（顶栏模型 chip、主题、输入行为都依赖它）
 *   2. 拉工作区（左栏选择器、右栏展示）
 *   3. 拉对话数据（会话列表 + `\doc` 文档候选）
 *   4. 安装主题（读系统明暗 → 写 CSS 变量）
 */
// Vue：computed 判断是否对话页，ref 存右栏展开状态，onMounted 做启动初始化
import { computed, onMounted, ref } from 'vue'
// Vue Router：RouterView 渲染中栏内容，useRoute 判断当前页是否需要满幅布局
import { RouterView, useRoute } from 'vue-router'
// 三个布局组件
import Sidebar from '@/components/layout/Sidebar.vue'
import TopBar from '@/components/layout/TopBar.vue'
import ContextPanel from '@/components/layout/ContextPanel.vue'
// 设置 / 工作区 / 对话 store：启动初始化要用的数据源
import { useSettingsStore } from '@/stores/settings'
import { useWorkspacesStore } from '@/stores/workspaces'
import { useChatStore } from '@/stores/chat'
// 主题安装：挂载后立即应用一次，之后设置变化自动重应用
import { useTheme } from '@/composables/useTheme'

const route = useRoute()

/**
 * 当前是否是对话页。
 *
 * 对话页要"满幅 + 自己滚动"（消息区必须撑满中栏，输入栏贴底）；
 * 其它页面（设置/扫描/关于）沿用改造前的居中容器 + 内边距，避免老页面排版被拉散。
 */
const isChat = computed<boolean>(() => route.path === '/')

const settings = useSettingsStore()
const workspaces = useWorkspacesStore()
const chat = useChatStore()
// 调用即完成"监听 + 首次应用"；返回值暂时不用，但保留引用便于以后加主题相关操作
const theme = useTheme()

/** 右栏是否展开：默认展开，用户收起后记在 localStorage（下次进来保持习惯） */
const contextOpen = ref<boolean>(localStorage.getItem('ui.contextOpen') !== '0')

/** 切换右栏并把选择记下来 */
function toggleContext(): void {
  contextOpen.value = !contextOpen.value
  localStorage.setItem('ui.contextOpen', contextOpen.value ? '1' : '0')
}

onMounted(async () => {
  // 设置与工作区是"其它一切的输入"，先并行拉；对话数据与它们无依赖，也一起发出去
  await Promise.all([
    settings.loadAll(),
    workspaces.loadAll(),
    chat.bootstrap(),
  ])
  // 设置到位后主题才知道该用哪套色，这里再应用一次（useTheme 的 onMounted 已先应用过默认值）
  theme.apply()
})
</script>

<template>
  <div class="shell">
    <Sidebar />

    <div class="shell__main">
      <TopBar :context-open="contextOpen" @toggle-context="toggleContext" />
      <main class="shell__content" :class="{ 'shell__content--flush': isChat }">
        <div class="shell__page" :class="{ 'shell__page--flush': isChat }">
          <!-- 路由出口：/ 是对话，/settings 是设置，/scanner/* 是扫描模块 -->
          <RouterView />
        </div>
      </main>
    </div>

    <ContextPanel v-if="contextOpen" />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  /* 透明：让 body 的主题渐变透上来（写死底色会把渐变盖掉） */
  background: transparent;
  color: var(--color-text);
}

.shell__main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
}

.shell__content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: transparent;
}

/* 对话页：不滚动父容器，让消息区自己滚（否则输入栏会被推到底部之外） */
.shell__content--flush {
  overflow: hidden;
}

/* 普通页容器：沿用改造前的 1080~1120px 居中 + 内边距，老页面排版不变 */
.shell__page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 24px 28px 40px;
}

.shell__page--flush {
  max-width: none;
  margin: 0;
  padding: 0;
  height: 100%;
}
</style>
