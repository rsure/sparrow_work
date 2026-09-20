<!--
  components/layout/Sidebar.vue —— 左栏：工作区选择 + 新建对话 + 导航 + 最近会话。
  改造前这些入口散在 App.vue 顶部导航与 scannHistory 的「会话」抽屉里；
  三栏布局把它们收到一个固定侧栏，中栏就能专注内容。
-->
<script setup lang="ts">
/**
 * Sidebar —— 左侧导航栏。
 *
 * 四块内容（自上而下）：
 *   1. 品牌位 + 工作区选择器
 *   2. 「新建对话」主按钮
 *   3. 页面导航（对话 / 扫描 / 操作记录 / 设置 / 关于）—— 设置页入口就在这里
 *   4. 最近会话列表（点击即打开，悬停出现删除）
 */
// Vue：computed 派生当前会话高亮等状态，ref 存搜索词与"正在改名"的行
import { computed, onBeforeUnmount, ref } from 'vue'
// Vue Router：导航链接与当前路由（用于高亮）
import { RouterLink, useRoute, useRouter } from 'vue-router'
// Vant：删除会话前的确认对话框 + 轻提示（新建工作区的反馈）
import { showConfirmDialog, showToast } from 'vant'
// 应用标题：与 Electron 窗口标题共用一份配置
import { APP_TITLE } from '@/config'
// 对话 store：会话列表 / 新建 / 打开 / 删除 / 置顶 / 归档 / 导出
import { useChatStore } from '@/stores/chat'
// 会话与导出格式的类型：行内菜单要用到 pinned/archived 字段
import type { ChatExportFormat, ChatSessionInfo } from '@/services/chat'
// 工作区 store：多 profile 列表与切换
import { useWorkspacesStore } from '@/stores/workspaces'

const chat = useChatStore()
const workspaces = useWorkspacesStore()
const route = useRoute()
const router = useRouter()

/** 导航项：路径 + 文案 + 图标（Vant 图标名） */
const navItems = [
  { path: '/', label: '对话', icon: 'chat-o' },
  { path: '/scanner', label: '扫描', icon: 'apps-o' },
  { path: '/trace', label: '执行轨迹', icon: 'eye-o' },
  { path: '/audit', label: '操作记录', icon: 'records' },
  { path: '/settings', label: '设置', icon: 'setting-o' },
  { path: '/diagnostics', label: '诊断', icon: 'chart-trending-o' },
  { path: '/about', label: '关于', icon: 'info-o' },
]

/** 当前选中工作区的 id（select 的 v-model 需要一个字符串） */
const activeWorkspaceId = computed<string>({
  get: () => workspaces.activeId,
  set: (id: string) => {
    if (id && id !== workspaces.activeId) void workspaces.setActive(id)
  },
})

/** 是否正在创建工作区（防重复点击：选目录的对话框可能停留几秒） */
const creatingWorkspace = ref(false)

/**
 * 新建工作区：选一个文件夹 → 用文件夹名当工作区名 → 创建并切过去。
 *
 * 为什么不弹表单让用户填名字：目录名几乎总是最合适的名字，
 * 需要改名时到「设置 → 工作区」里改即可。少一步填表，路径选择更直接。
 */
async function onCreateWorkspace(): Promise<void> {
  if (creatingWorkspace.value) return
  const desktop = window.desktop
  if (!desktop?.selectFolder) {
    showToast('浏览器调试模式下无法选择目录，请在桌面应用里操作')
    return
  }
  const picked = await desktop.selectFolder()
  if (!picked) return

  // 取路径最后一段作为名字（Windows 用反斜杠，macOS/Linux 用斜杠）
  const segments = picked.split(/[\\/]/).filter(Boolean)
  const name = segments[segments.length - 1] || '新工作区'

  creatingWorkspace.value = true
  try {
    await workspaces.create(name, [picked])
    // 创建后自动切过去：用户点"+"的意图就是"我要在这个目录里干活"
    const created = workspaces.list.find((item) => item.roots.includes(picked))
    if (created && created.id !== workspaces.activeId) {
      await workspaces.setActive(created.id)
    }
    showToast(`已创建工作区「${name}」`)
  } catch (error) {
    console.error('创建工作区失败:', error)
    showToast('创建工作区失败')
  } finally {
    creatingWorkspace.value = false
  }
}

/** 左栏当前渲染的会话：正常视图是「最近会话」，归档视图是归档箱（置顶的已由后端排在前面） */
const sessions = computed(() => chat.visibleSessions)

/**
 * 新建对话：清空当前上下文并回到对话页。
 * 已经在对话页时也执行（用户可能从别的页面点进来）。
 */
async function onNewConversation(): Promise<void> {
  await chat.newConversation()
  if (route.path !== '/') await router.push('/')
}

/**
 * 打开一条历史会话：先切到对话页，再加载消息。
 *
 * @param sessionId 会话 id
 */
async function onOpenSession(sessionId: string): Promise<void> {
  if (route.path !== '/') await router.push('/')
  await chat.openSession(sessionId)
}

/**
 * 删除会话：二次确认后调 store 删除。
 *
 * @param event 点击事件（用来阻止冒泡到"打开会话"）
 * @param sessionId 会话 id
 * @param title 会话标题（弹窗里展示）
 */
async function onRemoveSession(event: MouseEvent, sessionId: string, title: string): Promise<void> {
  event.stopPropagation()
  menuId.value = null
  try {
    await showConfirmDialog({
      title: '删除会话',
      message: `确定删除「${title}」及其全部对话内容吗？删除后无法恢复。`,
    })
  } catch {
    return // 用户取消
  }
  // 归档箱里的会话也要能删，所以从当前渲染的列表里找
  const target = sessions.value.find((item) => item.session_id === sessionId)
  // 删除结果由 store 统一提示，这里不重复弹 toast
  if (target) await chat.removeSession(target)
}

// --------------------------------------------------------------------------- //
// UX-4：行内操作菜单（置顶 / 归档 / 导出）
// 为什么做成「⋯」弹出而不是每行摆四个按钮：
//   侧栏只有 232px，四个按钮会让标题被压到看不清；而置顶/归档/导出都是低频操作，
//   收进菜单既省空间，也不会让用户误点。
// --------------------------------------------------------------------------- //
/** 当前展开操作菜单的会话 id；null 表示所有菜单都收起 */
const menuId = ref<string | null>(null)

/**
 * 展开 / 收起某一行的操作菜单。
 *
 * @param event 点击事件（阻止冒泡到"打开会话"）
 * @param sessionId 会话 id
 */
function toggleMenu(event: MouseEvent, sessionId: string): void {
  event.stopPropagation()
  menuId.value = menuId.value === sessionId ? null : sessionId
}

/**
 * 置顶 / 取消置顶。
 *
 * @param event 点击事件（阻止冒泡）
 * @param sess 目标会话
 */
async function onTogglePin(event: MouseEvent, sess: ChatSessionInfo): Promise<void> {
  event.stopPropagation()
  menuId.value = null
  await chat.setSessionPinned(sess, !sess.pinned)
}

/**
 * 归档 / 取消归档。
 *
 * @param event 点击事件（阻止冒泡）
 * @param sess 目标会话
 */
async function onToggleArchive(event: MouseEvent, sess: ChatSessionInfo): Promise<void> {
  event.stopPropagation()
  menuId.value = null
  await chat.setSessionArchived(sess, !sess.archived)
}

/**
 * 导出会话并触发下载。
 *
 * @param event 点击事件（阻止冒泡）
 * @param sess 目标会话
 * @param format 导出格式：md 给人看，json 给程序读
 */
async function onExport(
  event: MouseEvent,
  sess: ChatSessionInfo,
  format: ChatExportFormat,
): Promise<void> {
  event.stopPropagation()
  menuId.value = null
  await chat.exportSession(sess.session_id, format)
}

/**
 * 切换「最近会话 / 归档箱」。
 * 归档箱是懒加载的，第一次切过去才会真的查库（见 store 的 loadArchivedSessions）。
 */
async function onToggleArchivedView(): Promise<void> {
  menuId.value = null
  await chat.switchArchivedView(!chat.showArchived)
}

// --------------------------------------------------------------------------- //
// 搜索（UX-4）：输入即搜，但压在 300ms 防抖里，避免每敲一个字打一次后端
// --------------------------------------------------------------------------- //
/** 搜索输入框的本地值（与 store.searchQuery 分开，避免打字时列表闪） */
const keyword = ref(chat.searchQuery)
/** 防抖定时器句柄 */
let searchTimer: number | null = null

/** 输入变化：300ms 内没有新输入才真正请求 */
function onSearchInput(): void {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    void chat.searchSessions(keyword.value)
  }, 300)
}

/** 清空搜索（同时立刻刷新列表） */
function clearSearch(): void {
  keyword.value = ''
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  void chat.searchSessions('')
}

// --------------------------------------------------------------------------- //
// 重命名（UX-4）：双击标题进入行内编辑，Enter 提交、Esc 取消
// --------------------------------------------------------------------------- //
/** 正在改名的会话 id；null 表示没有在编辑 */
const editingId = ref<string | null>(null)
/** 编辑中的标题草稿 */
const editingTitle = ref('')

/**
 * 进入某一行的改名状态。
 *
 * @param event 双击事件（阻止它冒泡到"打开会话"）
 * @param sessionId 会话 id
 * @param title 当前标题
 */
function startRename(event: MouseEvent, sessionId: string, title: string): void {
  event.stopPropagation()
  if (chat.sending) return
  editingId.value = sessionId
  editingTitle.value = title
}

/** 提交改名（空标题不改，避免把标题清空） */
async function commitRename(): Promise<void> {
  const id = editingId.value
  if (!id) return
  editingId.value = null
  const title = editingTitle.value.trim()
  if (!title) return
  await chat.renameSession(id, title)
}

/** 取消改名（Esc） */
function cancelRename(): void {
  editingId.value = null
}

onBeforeUnmount(() => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
})

/**
 * 把后端返回的 ISO 时间转成本地「MM-DD HH:mm」。
 *
 * @param iso UTC 时间字符串（可能不带时区后缀）
 * @returns 简短时间文案；空值返回空串
 */
function shortTime(iso: string | null): string {
  if (!iso) return ''
  const normalized = /Z|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>

<template>
  <aside class="sidebar">
    <!-- 品牌位 -->
    <div class="sidebar__brand">
      <span class="sidebar__dot" />
      <span class="sidebar__brand-text">{{ APP_TITLE }}</span>
    </div>

    <!-- 工作区：选择 + 新建（放在「新建对话」之上——先定在哪干活，再开口聊） -->
    <div class="sidebar__workspace">
      <label class="sidebar__label" for="ws-select">工作区</label>
      <div class="sidebar__workspace-row">
        <select id="ws-select" v-model="activeWorkspaceId" class="sidebar__select">
          <option v-if="workspaces.list.length === 0" value="">（尚未创建工作区）</option>
          <option v-for="ws in workspaces.list" :key="ws.id" :value="ws.id">
            {{ ws.name }}
          </option>
        </select>
        <button
          type="button"
          class="sidebar__ws-add"
          title="新建工作区（选择一个文件夹）"
          :disabled="creatingWorkspace"
          @click="onCreateWorkspace"
        >
          +
        </button>
      </div>
    </div>

    <!-- 新建对话：整栏最显眼的主动作 -->
    <button type="button" class="sidebar__new" :disabled="chat.sending" @click="onNewConversation">
      + 新建对话
    </button>

    <!-- 页面导航 -->
    <nav class="sidebar__nav">
      <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="sidebar__nav-item">
        <van-icon :name="item.icon" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>

    <!-- 最近会话 / 归档箱 -->
    <div class="sidebar__sessions">
      <div class="sidebar__sessions-head">
        <span>{{ chat.showArchived ? '归档箱' : '最近会话' }}</span>
        <div class="sidebar__sessions-actions">
          <button
            type="button"
            class="sidebar__sessions-refresh"
            @click="chat.showArchived ? chat.loadArchivedSessions() : chat.loadSessions()"
          >
            刷新
          </button>
          <!-- 归档箱入口：数量为 0 时不显示角标，避免每次启动都以为有未读 -->
          <button type="button" class="sidebar__sessions-refresh" @click="onToggleArchivedView">
            {{ chat.showArchived ? '返回' : chat.archivedCount ? `归档 ${chat.archivedCount}` : '归档' }}
          </button>
        </div>
      </div>

      <!-- 搜索：命中标题或消息正文（服务端过滤） -->
      <div class="sidebar__search">
        <input
          v-model="keyword"
          type="search"
          class="sidebar__search-input"
          placeholder="搜索会话 / 内容…"
          @input="onSearchInput"
        />
        <button v-if="keyword" type="button" class="sidebar__search-clear" title="清空" @click="clearSearch">
          ×
        </button>
      </div>

      <div v-if="chat.loadingSessions && sessions.length === 0" class="sidebar__empty">加载中…</div>
      <div v-else-if="sessions.length === 0" class="sidebar__empty">
        {{ chat.showArchived ? '归档箱是空的' : '还没有对话记录' }}
      </div>
      <div v-else class="sidebar__sessions-list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="session"
          :class="{ 'session--active': session.session_id === chat.sessionId }"
          @click="onOpenSession(session.session_id)"
        >
          <div class="session__main">
            <!-- 行内改名：Enter 提交、Esc 取消、失焦也提交 -->
            <input
              v-if="editingId === session.session_id"
              v-model="editingTitle"
              class="session__rename"
              autofocus
              @click.stop
              @keyup.enter="commitRename"
              @keyup.esc="cancelRename"
              @blur="commitRename"
            />
            <div
              v-else
              class="session__title"
              title="双击重命名"
              @dblclick="startRename($event, session.session_id, session.title)"
            >
              <!-- 置顶标记：不改变标题本身，只在前面加一个小图钉 -->
              <span v-if="session.pinned" class="session__pin" title="已置顶">📌</span>
              {{ session.title || '未命名会话' }}
            </div>
            <div class="session__meta">
              {{ session.message_count }} 条 · {{ shortTime(session.updated_at) }}
            </div>
          </div>

          <!-- 「⋯」操作菜单：置顶 / 归档 / 导出（侧栏太窄，收起比摆四个按钮好） -->
          <button
            type="button"
            class="session__more"
            title="更多操作"
            @click="toggleMenu($event, session.session_id)"
          >
            ⋯
          </button>
          <div v-if="menuId === session.session_id" class="session__menu" @click.stop>
            <button type="button" class="session__menu-item" @click="onTogglePin($event, session)">
              {{ session.pinned ? '取消置顶' : '置顶' }}
            </button>
            <button type="button" class="session__menu-item" @click="onToggleArchive($event, session)">
              {{ session.archived ? '取消归档' : '归档' }}
            </button>
            <button type="button" class="session__menu-item" @click="onExport($event, session, 'md')">
              导出 Markdown
            </button>
            <button type="button" class="session__menu-item" @click="onExport($event, session, 'json')">
              导出 JSON
            </button>
            <button
              type="button"
              class="session__menu-item session__menu-item--danger"
              @click="onRemoveSession($event, session.session_id, session.title)"
            >
              删除会话
            </button>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 232px;
  flex: 0 0 232px;
  height: 100%;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: 14px 12px 10px;
  gap: 12px;
  min-height: 0;
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 4px 6px;
  font-weight: 600;
  font-size: 13px;
}

.sidebar__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 12px var(--color-primary);
}

.sidebar__brand-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__workspace {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebar__label {
  font-size: 11px;
  color: var(--color-text-muted);
  padding-left: 2px;
}

.sidebar__workspace-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sidebar__ws-add {
  flex: none;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}

.sidebar__ws-add:hover:not(:disabled) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.sidebar__ws-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sidebar__select {
  width: 100%;
  background: var(--color-surface-2);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 5px 8px;
  font-size: 12px;
  outline: none;
}

.sidebar__new {
  appearance: none;
  border: 1px solid var(--color-primary);
  background: var(--color-primary-weak);
  color: var(--color-primary);
  border-radius: 9px;
  padding: 7px 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.sidebar__new:hover:not(:disabled) {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.sidebar__new:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.sidebar__nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
}

.sidebar__nav-item:hover {
  background: var(--color-surface-2);
  color: var(--color-text);
}

.sidebar__nav-item.router-link-active {
  background: var(--color-primary-weak);
  color: var(--color-primary);
  font-weight: 600;
}

.sidebar__sessions {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.sidebar__sessions-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--color-text-muted);
  padding: 2px 4px 6px;
}

/* 「刷新 / 归档」两个小按钮并排：右对齐，间距 6px */
.sidebar__sessions-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sidebar__sessions-refresh {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: 11px;
  cursor: pointer;
}

.sidebar__sessions-refresh:hover {
  color: var(--color-primary);
}

.sidebar__search {
  position: relative;
  padding: 0 2px 6px;
}

.sidebar__search-input {
  width: 100%;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: 7px;
  color: var(--color-text);
  font-size: 12px;
  padding: 4px 22px 4px 8px;
  outline: none;
}

.sidebar__search-input:focus {
  border-color: var(--color-primary);
}

.sidebar__search-clear {
  position: absolute;
  right: 6px;
  top: 3px;
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  padding: 2px;
}

.sidebar__search-clear:hover {
  color: var(--color-danger);
}

.sidebar__empty {
  padding: 12px 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.sidebar__sessions-list {
  overflow-y: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.session:hover {
  background: var(--color-surface-2);
}

.session--active {
  background: var(--color-primary-weak);
}

.session__main {
  flex: 1;
  min-width: 0;
}

.session__title {
  font-size: 12px;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session__rename {
  width: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-primary);
  border-radius: 5px;
  color: var(--color-text);
  font-size: 12px;
  padding: 1px 4px;
  outline: none;
}

.session__meta {
  font-size: 10px;
  color: var(--color-text-muted);
}

/* 「⋯」操作菜单按钮：平时半透明，悬停整行时才明显（不抢标题的视觉重量） */
.session__more {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1;
  padding: 2px 4px;
  cursor: pointer;
  opacity: 0;
}

.session:hover .session__more,
.session__more:focus-visible {
  opacity: 1;
}

.session__more:hover {
  color: var(--color-primary);
}

/* 操作菜单：绝对定位贴在「⋯」下方右侧，不参与列表流式布局 */
.session__menu {
  position: absolute;
  right: 6px;
  top: 26px;
  z-index: 20;
  display: flex;
  flex-direction: column;
  min-width: 118px;
  padding: 4px;
  border: 1px solid var(--color-border);
  border-radius: 9px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
}

.session__menu-item {
  appearance: none;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text);
  font-size: 11px;
  text-align: left;
  padding: 5px 8px;
  cursor: pointer;
  white-space: nowrap;
}

.session__menu-item:hover {
  background: var(--color-surface-2);
}

.session__menu-item--danger {
  color: var(--color-danger);
}

/* 置顶标记：小图钉跟着标题，不参与省略号计算 */
.session__pin {
  margin-right: 2px;
  font-size: 10px;
}
</style>
