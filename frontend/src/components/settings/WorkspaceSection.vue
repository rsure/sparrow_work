<!--
  components/settings/WorkspaceSection.vue
  工作区多 profile 管理面板：
    - 顶部「新建工作区」表单（name + 多行 roots）
    - 列表：每个工作区一行，显示名字/roots/active 标记，右侧四个按钮（激活/改名/编辑 roots/删除）
    - 「设为当前」：调 store.setActive
    - 改名 / 改 roots：展开行内编辑器（不弹窗，避免和列表冲突）
    - 删除：弹确认框
-->
<script setup lang="ts">
/**
 * WorkspaceSection —— 设置页里「工作区」分区的管理面板。
 * 完全由 store.workspaces 状态驱动：列表 = state.list，操作都委托给 store。
 * 本组件不持有工作区数据副本，只持「正在编辑哪个 id 的哪个字段」这种 UI 临时态。
 */
import { computed, ref } from 'vue' // 响应式工具：ref 存 UI 临时态（编辑目标），computed 派生列表展示数据
import { showConfirmDialog, showToast } from 'vant' // Vant 反馈：删除前确认，操作结果提示
import { useWorkspacesStore } from '@/stores/workspaces' // 工作区的全部 CRUD 都走 store

const store = useWorkspacesStore()

// ----------------------------------------------------------------------------
// 1. 新建工作区
// ----------------------------------------------------------------------------
/** 新建表单里的 name */
const newName = ref('')
/** 新建表单里的 roots（多行文本框，一行一个路径；trim 后空行忽略） */
const newRoots = ref('')
/** 是否正在创建（按钮 loading） */
const creating = ref(false)
/** 新建失败的错误文案 */
const createError = ref('')

/** 把多行文本转成字符串数组：split 后逐项 trim，过滤空行 */
function parseRoots(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

/** 点击「新建」按钮：构造 workspace 并交给 store */
async function handleCreate(): Promise<void> {
  const name = newName.value.trim()
  if (!name) {
    createError.value = '工作区名称不能为空'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    await store.create(name, parseRoots(newRoots.value))
    // 成功后清空表单
    newName.value = ''
    newRoots.value = ''
    showToast('工作区已创建')
  } catch {
    // store 已经把错误写到 loadError，这里只需显示通用兜底
    createError.value = store.loadError || '新建失败'
  } finally {
    creating.value = false
  }
}

// ----------------------------------------------------------------------------
// 2. 行内编辑（改名 / 改 roots）
// ----------------------------------------------------------------------------
/** 当前正在编辑哪个工作区的哪个字段：null 表示没有编辑 */
interface EditingTarget {
  /** 工作区 id */
  id: string
  /** 编辑的字段名：'name' | 'roots' */
  field: 'name' | 'roots'
}
const editing = ref<EditingTarget | null>(null)
/** 编辑框里的临时值（不直接绑 store，避免边输入边发请求） */
const editDraft = ref('')
/** 行内编辑失败的错误文案 */
const editError = ref('')

/** 展开「改名」编辑器 */
function startEditName(id: string, currentName: string): void {
  editing.value = { id, field: 'name' }
  editDraft.value = currentName
  editError.value = ''
}

/** 展开「改根目录」编辑器：把数组按行 join 起来，方便用户编辑 */
function startEditRoots(id: string, currentRoots: string[]): void {
  editing.value = { id, field: 'roots' }
  editDraft.value = currentRoots.join('\n')
  editError.value = ''
}

/** 取消编辑 */
function cancelEdit(): void {
  editing.value = null
  editDraft.value = ''
  editError.value = ''
}

/** 提交行内编辑：根据 field 调 store.update，传 roots 时把字符串数组转回去 */
async function commitEdit(): Promise<void> {
  if (!editing.value) return
  const target = editing.value
  try {
    if (target.field === 'name') {
      const name = editDraft.value.trim()
      if (!name) {
        editError.value = '名称不能为空'
        return
      }
      await store.update(target.id, { name })
    } else {
      const roots = parseRoots(editDraft.value)
      await store.update(target.id, { roots })
    }
    editing.value = null
    editDraft.value = ''
    showToast('已保存')
  } catch {
    editError.value = store.loadError || '保存失败'
  }
}

// ----------------------------------------------------------------------------
// 3. 激活 / 删除
// ----------------------------------------------------------------------------
/** 设为当前工作区（id 与 activeId 不同时才需要操作） */
async function handleSetActive(id: string): Promise<void> {
  await store.setActive(id)
  if (!store.loadError) showToast('已切换当前工作区')
}

/** 删除工作区：先弹确认框，确认后调 store.remove */
async function handleDelete(id: string, name: string): Promise<void> {
  try {
    await showConfirmDialog({
      title: '删除工作区',
      message: `确认删除工作区「${name}」？该操作不可撤销。`,
    })
  } catch {
    return
  }
  await store.remove(id)
  if (!store.loadError) showToast('已删除')
}

// ----------------------------------------------------------------------------
// 4. 展示计算
// ----------------------------------------------------------------------------
/** 当前所有工作区（带 active 标记），按后端返回顺序 */
const workspaces = computed(() => store.list)
</script>

<template>
  <div class="workspace-section">
    <!-- 顶部：新建表单 -->
    <div class="workspace-section__new">
      <h3 class="workspace-section__sub">新建工作区</h3>
      <van-field v-model="newName" placeholder="工作区名称（如 主项目）" :disabled="creating" />
      <van-field
        v-model="newRoots"
        type="textarea"
        :rows="3"
        autosize
        placeholder="根目录绝对路径，每行一个"
        :disabled="creating"
      />
      <van-button
        size="small"
        type="primary"
        :loading="creating"
        :disabled="creating"
        @click="handleCreate"
      >
        新建
      </van-button>
      <p v-if="createError" class="workspace-section__error">{{ createError }}</p>
    </div>

    <!-- 加载中：首屏时给个简单的 loading 文字即可 -->
    <div v-if="store.loading" class="workspace-section__loading">加载中…</div>

    <!-- 列表 -->
    <div v-else class="workspace-section__list">
      <div v-if="workspaces.length === 0" class="workspace-section__empty">
        暂无工作区。先在上面创建一个，开始指定 Agent 可写入的目录范围。
      </div>

      <div
        v-for="ws in workspaces"
        :key="ws.id"
        class="workspace-section__item"
        :class="{ 'workspace-section__item--active': ws.active }"
      >
        <!-- 头部：名字 + active 徽标 + 操作按钮 -->
        <div class="workspace-section__item-head">
          <div class="workspace-section__item-title">
            <span class="workspace-section__item-name">{{ ws.name }}</span>
            <span v-if="ws.active" class="workspace-section__item-tag">当前</span>
            <span class="workspace-section__item-id">{{ ws.id }}</span>
          </div>
          <div class="workspace-section__item-actions">
            <van-button
              v-if="!ws.active"
              size="mini"
              plain
              type="primary"
              :disabled="store.pending"
              @click="handleSetActive(ws.id)"
            >
              设为当前
            </van-button>
            <van-button
              size="mini"
              plain
              :disabled="store.pending || !!(editing && editing.id === ws.id)"
              @click="startEditName(ws.id, ws.name)"
            >
              改名
            </van-button>
            <van-button
              size="mini"
              plain
              :disabled="store.pending || !!(editing && editing.id === ws.id)"
              @click="startEditRoots(ws.id, ws.roots)"
            >
              编辑根目录
            </van-button>
            <van-button
              size="mini"
              plain
              type="danger"
              :disabled="store.pending"
              @click="handleDelete(ws.id, ws.name)"
            >
              删除
            </van-button>
          </div>
        </div>

        <!-- 根目录列表 -->
        <ul v-if="ws.roots.length > 0" class="workspace-section__roots">
          <li v-for="root in ws.roots" :key="root" class="workspace-section__root">{{ root }}</li>
        </ul>
        <p v-else class="workspace-section__roots-empty">未设置根目录（不限制范围）</p>

        <!-- 行内编辑面板：编辑哪个工作区的哪个字段，就渲染对应的输入框 -->
        <div v-if="editing && editing.id === ws.id" class="workspace-section__edit">
          <van-field
            v-if="editing.field === 'name'"
            v-model="editDraft"
            placeholder="新名称"
            :disabled="store.pending"
          />
          <van-field
            v-else
            v-model="editDraft"
            type="textarea"
            :rows="3"
            autosize
            placeholder="根目录，每行一个"
            :disabled="store.pending"
          />
          <div class="workspace-section__edit-actions">
            <van-button size="mini" type="primary" :disabled="store.pending" @click="commitEdit">
              保存
            </van-button>
            <van-button size="mini" plain :disabled="store.pending" @click="cancelEdit">
              取消
            </van-button>
          </div>
          <p v-if="editError" class="workspace-section__error">{{ editError }}</p>
        </div>
      </div>
    </div>

    <!-- 列表加载错误 -->
    <p v-if="store.loadError" class="workspace-section__error">{{ store.loadError }}</p>
  </div>
</template>

<style scoped>
.workspace-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.workspace-section__new {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px dashed var(--color-border, #1f2937);
  border-radius: 8px;
}

.workspace-section__sub {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.workspace-section__loading,
.workspace-section__empty {
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
  padding: 12px;
  text-align: center;
}

.workspace-section__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workspace-section__item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--color-border, #1f2937);
  border-radius: 8px;
  background: var(--color-surface-2, rgba(17, 24, 39, 0.4));
}

.workspace-section__item--active {
  /* 当前工作区高亮：边框用主题色 */
  border-color: var(--color-primary, #38bdf8);
}

.workspace-section__item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workspace-section__item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.workspace-section__item-name {
  font-size: 15px;
  font-weight: 600;
}

.workspace-section__item-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.15);
  color: var(--color-primary, #38bdf8);
  border: 1px solid var(--color-primary, #38bdf8);
}

.workspace-section__item-id {
  font-size: 11px;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  color: var(--color-text-muted, #94a3b8);
}

.workspace-section__item-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.workspace-section__roots {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.workspace-section__root {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  font-size: 12px;
  background: rgba(56, 189, 248, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 4px;
  padding: 4px 8px;
  word-break: break-all;
}

.workspace-section__roots-empty {
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  margin: 0;
}

.workspace-section__edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border, #1f2937);
}

.workspace-section__edit-actions {
  display: flex;
  gap: 8px;
}

.workspace-section__error {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-danger, #ef4444);
}
</style>