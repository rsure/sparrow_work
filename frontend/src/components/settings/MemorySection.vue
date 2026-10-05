<!--
  components/settings/MemorySection.vue
  工作空间记忆面板：看「AI 记住了什么」、搜一下、手填一条、删掉记错的。

  为什么这个面板值得存在：
  记忆是**自动写**的，用户看不见就等于黑箱。一旦模型不知道为什么"记得"某件错事，
  没有任何地方能纠正它。这个面板给用户三件事：可审计（看得见）、可纠正（能删）、可补充（能手填）。
-->
<script setup lang="ts">
// Vue：生命周期与响应式
import { computed, onMounted, ref } from 'vue'
// Vant：操作反馈与二次确认（清空是不可逆的）
import { showConfirmDialog, showToast } from 'vant'

// 项目内：记忆接口
import {
  MEMORY_CATEGORY_LABEL,
  clearMemories,
  createMemory,
  deleteMemory,
  fetchMemoryStats,
  listMemories,
  pruneMemories,
  reindexMemories,
  searchMemories,
  type MemoryCategory,
  type MemoryItem,
  type MemoryStats,
} from '@/services/memory'

/** 分类选项（下拉用） */
const CATEGORIES = Object.entries(MEMORY_CATEGORY_LABEL) as Array<[MemoryCategory, string]>

/** 当前列表（检索时是命中结果，否则是全量列表） */
const items = ref<MemoryItem[]>([])
/** 统计信息 */
const stats = ref<MemoryStats | null>(null)
/** 记忆总开关状态（关掉时整页功能不生效，要明确告诉用户） */
const enabled = ref(true)
/** 是否正在加载 */
const loading = ref(false)
/** 搜索关键词 */
const keyword = ref('')
/** 是否处于"搜索结果"状态（决定标题文案与"清空搜索"按钮） */
const searching = ref(false)

/** 新增表单：正文 */
const draftContent = ref('')
/** 新增表单：分类 */
const draftCategory = ref<MemoryCategory>('decision')
/** 新增表单：重要度 */
const draftImportance = ref(3)
/** 是否正在跑维护动作（整理 / 重建向量）：防止连点，也让按钮有禁用态 */
const maintaining = ref(false)

/** 分类中文名（列表里的小标签） */
function categoryLabel(category: string): string {
  return MEMORY_CATEGORY_LABEL[category as MemoryCategory] ?? category
}

/** 是否有内容可显示 */
const hasItems = computed(() => items.value.length > 0)

/**
 * 拉列表 + 统计（两个请求并发，任一失败只提示一次）。
 */
async function refresh(): Promise<void> {
  loading.value = true
  searching.value = false
  try {
    const [list, statsData] = await Promise.all([listMemories(), fetchMemoryStats()])
    items.value = list.memories
    enabled.value = list.enabled
    stats.value = statsData
  } catch (error) {
    console.error('加载记忆失败:', error)
    showToast('加载记忆失败')
  } finally {
    loading.value = false
  }
}

/** 执行检索（空关键词等价于回到全量列表） */
async function onSearch(): Promise<void> {
  const query = keyword.value.trim()
  if (!query) {
    await refresh()
    return
  }
  loading.value = true
  try {
    const data = await searchMemories(query)
    items.value = data.hits
    searching.value = true
  } catch (error) {
    console.error('检索记忆失败:', error)
    showToast('检索失败')
  } finally {
    loading.value = false
  }
}

/** 清空搜索框并回到全量列表 */
async function clearSearch(): Promise<void> {
  keyword.value = ''
  await refresh()
}

/** 新增一条记忆 */
async function onCreate(): Promise<void> {
  const content = draftContent.value.trim()
  if (!content) {
    showToast('先写一句要记住的话')
    return
  }
  try {
    const result = await createMemory(content, draftCategory.value, draftImportance.value)
    if (!result.saved) {
      // 被判为重复不是错误，但要说清楚"为什么没加进去"，否则用户会以为按钮坏了
      showToast('这条和已有记忆太像，已跳过')
      return
    }
    draftContent.value = ''
    showToast('已记住')
    await refresh()
  } catch (error) {
    console.error('新增记忆失败:', error)
    showToast('保存失败')
  }
}

/**
 * 删除一条记忆。
 *
 * @param item 要删的记忆
 */
async function onDelete(item: MemoryItem): Promise<void> {
  try {
    await deleteMemory(item.id)
    // 本地先移除，避免为一次删除再拉一遍列表（失败时下次刷新会回来）
    items.value = items.value.filter((row) => row.id !== item.id)
    if (stats.value) {
      stats.value = {
        ...stats.value,
        total: Math.max(0, stats.value.total - 1),
        by_category: { ...stats.value.by_category },
      }
      const left = (stats.value.by_category[item.category] ?? 1) - 1
      if (left > 0) stats.value.by_category[item.category] = left
      else delete stats.value.by_category[item.category]
    }
  } catch (error) {
    console.error('删除记忆失败:', error)
    showToast('删除失败')
  }
}

/** 清空本工作区的全部记忆（不可逆，必须二次确认） */
async function onClear(): Promise<void> {
  try {
    await showConfirmDialog({
      title: '清空本工作区的记忆',
      message: '所有自动抽取与手动添加的记忆都会被删除，且无法恢复。工作区里的文件不受影响。',
      messageAlign: 'left',
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    const result = await clearMemories()
    showToast(`已清空 ${result.removed} 条`)
    await refresh()
  } catch (error) {
    console.error('清空记忆失败:', error)
    showToast('清空失败')
  }
}

/** 重要度的可视化：实心点表示分值（比数字更直观） */
function importanceDots(value: number): string {
  const level = Math.max(1, Math.min(value, 5))
  return '●'.repeat(level) + '○'.repeat(5 - level)
}

/**
 * 立即整理：删掉低价值且过期没用的，并把条数压回上限。
 *
 * 不需要二次确认——它删的是"重要度 ≤2 且长期没被用到"的条目，
 * 而这些条目本来就会在下一次抽取结束后被自动清掉；这里只是让用户不必等。
 */
async function onPrune(): Promise<void> {
  if (maintaining.value) return
  maintaining.value = true
  try {
    const result = await pruneMemories()
    showToast(
      result.removed
        ? `清理了 ${result.removed} 条（过期 ${result.removed_expired}、超限 ${result.removed_overflow}）`
        : '没有需要清理的记忆',
    )
    await refresh()
  } catch (error) {
    console.error('整理记忆失败:', error)
    showToast('整理失败')
  } finally {
    maintaining.value = false
  }
}

/**
 * 重建向量：换过向量化后端之后必须跑一次，否则旧记忆会静默检索不到。
 *
 * @param force 是否连维度已经一致的行也重算（排查"语义检索不准"时用）
 */
async function onReindex(force = false): Promise<void> {
  if (maintaining.value) return
  if (force) {
    try {
      await showConfirmDialog({
        title: '重建全部记忆向量',
        message: '会用当前向量化后端把每条记忆重新算一遍向量。远端后端按条计费，条目多时可能需要等一会儿。',
        messageAlign: 'left',
        confirmButtonText: '开始重建',
        cancelButtonText: '取消',
      })
    } catch {
      return // 用户取消
    }
  }
  maintaining.value = true
  try {
    const result = await reindexMemories(undefined, force)
    showToast(`已重算 ${result.updated} 条向量（维度 ${result.dim}）`)
    await refresh()
  } catch (error) {
    console.error('重建向量失败:', error)
    showToast('重建失败（远端不可用时检查密钥与网络）')
  } finally {
    maintaining.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="mem">
    <div class="mem__bar">
      <span class="mem__count">
        <template v-if="stats">
          共 {{ stats.total }} 条
          <span v-if="stats.by_category.decision" class="mem__chip">决策 {{ stats.by_category.decision }}</span>
          <span v-if="stats.by_category.preference" class="mem__chip">偏好 {{ stats.by_category.preference }}</span>
          <span v-if="stats.by_category.fact" class="mem__chip">事实 {{ stats.by_category.fact }}</span>
          <span v-if="stats.by_category.todo" class="mem__chip">待办 {{ stats.by_category.todo }}</span>
        </template>
        <template v-else>加载中…</template>
      </span>
      <div class="mem__actions">
        <button type="button" class="mem__btn" :disabled="loading || maintaining" @click="refresh">刷新</button>
        <button
          type="button"
          class="mem__btn"
          :disabled="loading || maintaining"
          title="删掉重要度低、长期没被检索用到的记忆，并把条数压回上限"
          @click="onPrune"
        >
          整理
        </button>
        <button
          type="button"
          class="mem__btn"
          :disabled="loading || maintaining"
          title="换过向量化后端（本地哈希 ↔ 远端 embedding）之后必须重建，否则旧记忆检索不到"
          @click="onReindex(false)"
        >
          重建向量
        </button>
        <button type="button" class="mem__btn mem__btn--danger" :disabled="loading || !hasItems" @click="onClear">
          清空本工作区
        </button>
      </div>
    </div>

    <p v-if="stats" class="mem__backend">
      向量化：{{ stats.embedding }}
      <button type="button" class="mem__link" :disabled="maintaining" @click="onReindex(true)">全部重算</button>
    </p>

    <p v-if="!enabled" class="mem__warn">
      记忆总开关已关闭（见下方「工作空间记忆」）：不会抽取新记忆，也不会注入到对话里。
    </p>

    <!-- 检索：纯本地相似度匹配，不花模型调用 -->
    <div class="mem__search">
      <input
        v-model="keyword"
        type="search"
        class="mem__input"
        placeholder="在这些记忆里搜一下…"
        @keyup.enter="onSearch"
      />
      <button type="button" class="mem__btn" :disabled="loading" @click="onSearch">检索</button>
      <button v-if="searching" type="button" class="mem__btn" @click="clearSearch">返回全部</button>
    </div>

    <p v-if="loading" class="mem__empty">加载中…</p>
    <p v-else-if="!hasItems" class="mem__empty">
      {{ searching ? '没有匹配的记忆。' : '还没有记忆。聊几轮之后，值得记住的内容会自动出现在这里。' }}
    </p>
    <ul v-else class="mem__list">
      <li v-for="item in items" :key="item.id" class="mem-item">
        <div class="mem-item__main">
          <div class="mem-item__text">{{ item.content }}</div>
          <div class="mem-item__meta">
            <span class="mem-item__tag">{{ categoryLabel(item.category) }}</span>
            <span class="mem-item__dots" :title="`重要度 ${item.importance}/5`">
              {{ importanceDots(item.importance) }}
            </span>
            <span class="mem-item__source">{{ item.source === 'manual' ? '手动' : '自动抽取' }}</span>
            <span v-if="item.use_count > 0" class="mem-item__used" :title="item.last_used_at ? `最近一次被检索命中：${new Date(item.last_used_at).toLocaleString()}` : '被检索命中过'">
              用过 {{ item.use_count }} 次
            </span>
            <span v-if="item.merged_count > 0" class="mem-item__merged" :title="`合并过 ${item.merged_count} 条近似重复的内容`">
              合并 {{ item.merged_count }} 次
            </span>
            <span v-if="item.score !== undefined" class="mem-item__score">相关 {{ item.score }}</span>
          </div>
        </div>
        <button type="button" class="mem-item__del" title="删除这条记忆" @click="onDelete(item)">删除</button>
      </li>
    </ul>

    <!-- 手动新增：模型记漏了，或者你想主动交代一条 -->
    <div class="mem__create">
      <p class="mem__create-title">手动记一条</p>
      <textarea
        v-model="draftContent"
        class="mem__textarea"
        rows="2"
        maxlength="500"
        placeholder="例：这个项目的前端统一用 pnpm，不要用 npm"
      />
      <div class="mem__create-row">
        <select v-model="draftCategory" class="mem__select">
          <option v-for="[value, label] in CATEGORIES" :key="value" :value="value">{{ label }}</option>
        </select>
        <label class="mem__importance">
          重要度
          <input v-model.number="draftImportance" type="number" min="1" max="5" class="mem__number" />
        </label>
        <button type="button" class="mem__btn mem__btn--primary" @click="onCreate">记住</button>
      </div>
    </div>

    <p class="mem__hint">
      记忆按工作区隔离：切换工作区后这里的列表也会跟着变。重要度 5 表示"以后每次都要遵守"。
    </p>
  </div>
</template>

<style scoped>
.mem {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 12px;
}

.mem__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.mem__count {
  font-size: 12px;
  color: var(--color-text-muted);
}

.mem__chip {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-surface-2);
  font-size: 10px;
}

.mem__actions {
  display: flex;
  gap: 8px;
}

.mem__btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 7px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.mem__btn:hover:not(:disabled) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.mem__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mem__btn--danger:hover:not(:disabled) {
  color: var(--color-danger);
  border-color: var(--color-danger);
}

.mem__btn--primary {
  border-color: var(--color-primary);
  color: var(--color-on-primary, #fff);
  background: var(--color-primary);
}

.mem__warn {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.mem__search {
  display: flex;
  gap: 8px;
}

.mem__input,
.mem__textarea,
.mem__select,
.mem__number {
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text);
  border-radius: 8px;
  font-size: 12px;
  padding: 5px 8px;
  outline: none;
}

.mem__input {
  flex: 1;
  min-width: 0;
}

.mem__input:focus,
.mem__textarea:focus,
.mem__select:focus,
.mem__number:focus {
  border-color: var(--color-primary);
}

.mem__empty {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.mem__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mem-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
}

.mem-item__main {
  flex: 1;
  min-width: 0;
}

.mem-item__text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text);
  word-break: break-word;
}

.mem-item__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 10px;
  color: var(--color-text-muted);
  flex-wrap: wrap;
}

.mem-item__tag {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--color-surface);
}

.mem-item__dots {
  letter-spacing: 1px;
  color: var(--color-primary);
}

.mem-item__del {
  flex: none;
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 0;
}

.mem-item__del:hover {
  color: var(--color-danger);
}

.mem__create {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--color-border);
}

.mem__create-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text);
}

.mem__textarea {
  width: 100%;
  resize: vertical;
  font-family: inherit;
  line-height: 1.6;
}

.mem__create-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.mem__importance {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.mem__number {
  width: 52px;
}

.mem__hint {
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-text-muted);
  opacity: 0.85;
}

.mem__backend {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

.mem__link {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  font-size: 11px;
  color: var(--color-primary);
  cursor: pointer;
}

.mem__link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* "用过 N 次"与"合并 N 次"：都只在中性色里做一点区分，不抢正文的注意力 */
.mem-item__used {
  color: var(--color-primary);
}

.mem-item__merged {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--color-surface);
}
</style>
