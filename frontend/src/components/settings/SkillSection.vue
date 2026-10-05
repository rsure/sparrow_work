<!--
  components/settings/SkillSection.vue —— 设置页「技能」分区（EXT-1）。
  为什么要单独一个组件而不是纯 meta 渲染：
    设置项（skill.enabled / auto_inject / dirs / disabled）只能表达"开关与配置"，
    而技能是一个**列表**（名字、描述、解析错误），meta 驱动的 SettingField 渲染不出来。

  交互：
    - 每个技能一行：勾选框（启用/禁用，写 skill.disabled）+ 名字 + 描述 + 查看说明
    - 顶部：重新扫描（调 /skills/reload）+ 打开技能目录（Electron 能力）
    - 错误与目录直接摊开在下面 —— 用户手写 SKILL.md 出错时能自己修
-->
<script setup lang="ts">
/**
 * SkillSection —— 技能列表与启停。
 *
 * 数据来源：`GET /api/skills`（列表 + 错误 + 目录）；启停写设置键 `skill.disabled`。
 */
// Vue：computed 派生展示数据，onMounted 拉一次，ref 存加载状态
import { computed, onMounted, ref } from 'vue'
// Vant：轻提示与"查看说明"弹窗
import { showDialog, showToast } from 'vant'
// 技能接口：清单 / 重载 / 正文
import {
  fetchSkillBody,
  fetchSkills,
  reloadSkills,
  type SkillSnapshot,
} from '@/services/skills'
// 设置 store：启停开关写到 skill.disabled
import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()

/** 当前技能快照；null 表示还没加载 */
const snapshot = ref<SkillSnapshot | null>(null)
/** 是否正在请求（重载按钮 loading 用） */
const loading = ref(false)

/** 被禁用的技能名列表（与设置 store 保持同步） */
const disabled = computed<string[]>(() => {
  const value = settings.entries['skill.disabled']?.value
  return Array.isArray(value) ? (value as string[]) : []
})

/** 是否有可用技能（决定空态文案） */
const hasSkills = computed(() => (snapshot.value?.skills.length ?? 0) > 0)

// 进入分区时拉一次；设置页本身已 loadAll，但技能清单是独立接口
onMounted(load)

/** 拉取技能清单；失败只提示，不阻塞设置页其它分区 */
async function load(): Promise<void> {
  loading.value = true
  try {
    snapshot.value = await fetchSkills()
  } catch (error) {
    console.error('加载技能失败:', error)
    showToast('加载技能失败')
  } finally {
    loading.value = false
  }
}

/** 重新扫描目录（装好新技能后点它） */
async function reload(): Promise<void> {
  loading.value = true
  try {
    snapshot.value = await reloadSkills()
    showToast(`已重扫，共 ${snapshot.value.skills.length} 个技能`)
  } catch (error) {
    console.error('重扫技能失败:', error)
    showToast('重扫失败')
  } finally {
    loading.value = false
  }
}

/**
 * 启用/禁用某个技能：写 `skill.disabled`（只影响注入与 `/技能名`，不删文件）。
 *
 * @param name 技能名
 * @param enabled 目标状态
 */
async function toggle(name: string, enabled: boolean): Promise<void> {
  const next = enabled
    ? disabled.value.filter((item) => item !== name)
    : [...new Set([...disabled.value, name])]
  await settings.saveOne('skill.disabled', next)
  // 本地快照同步，避免要再点一次刷新才看到状态变化
  if (snapshot.value) {
    snapshot.value.skills = snapshot.value.skills.map((item) =>
      item.name === name ? { ...item, enabled } : item,
    )
    snapshot.value.disabled = next
  }
}

/**
 * 查看技能正文（弹窗里展示，便于确认步骤是否符合预期）。
 *
 * @param name 技能名
 */
async function viewBody(name: string): Promise<void> {
  try {
    const detail = await fetchSkillBody(name)
    await showDialog({
      title: `${detail.name}（${detail.body.length} 字）`,
      message: detail.body.length > 4000 ? `${detail.body.slice(0, 4000)}…` : detail.body,
      messageAlign: 'left',
      confirmButtonText: '关闭',
    })
  } catch (error) {
    console.error('读取技能正文失败:', error)
    showToast('读取失败')
  }
}

/** 打开技能目录（Electron 能力；浏览器下提示不可用） */
async function openDir(): Promise<void> {
  const dir = snapshot.value?.dirs[0]
  if (!dir) return
  const desktop = window.desktop
  if (!desktop?.showItemInFolder) {
    showToast('浏览器调试模式下无法打开目录，请在桌面应用里操作')
    return
  }
  await desktop.showItemInFolder(dir)
}
</script>

<template>
  <div class="skills">
    <div class="skills__bar">
      <span class="skills__count">
        {{ snapshot ? `${snapshot.skills.length} 个技能` : '加载中…' }}
      </span>
      <div class="skills__actions">
        <button type="button" class="skills__btn" :disabled="loading" @click="reload">重新扫描</button>
        <button type="button" class="skills__btn" @click="openDir">打开目录</button>
      </div>
    </div>

    <p v-if="!hasSkills" class="skills__empty">
      还没有安装技能。把一个带 <code>SKILL.md</code> 的目录放进
      <code>{{ snapshot?.dirs[0] || '技能目录' }}</code>，再点「重新扫描」。
    </p>

    <ul v-else class="skills__list">
      <li v-for="skill in snapshot?.skills ?? []" :key="skill.name" class="skill">
        <input
          class="skill__check"
          type="checkbox"
          :checked="!disabled.includes(skill.name)"
          :title="disabled.includes(skill.name) ? '点击启用' : '点击禁用'"
          @change="toggle(skill.name, ($event.target as HTMLInputElement).checked)"
        />
        <div class="skill__main">
          <div class="skill__name">
            {{ skill.name }}
            <span v-if="disabled.includes(skill.name)" class="skill__tag">已禁用</span>
          </div>
          <div class="skill__desc">{{ skill.description }}</div>
          <div class="skill__meta">
            <span v-if="skill.tools.length">工具：{{ skill.tools.join(', ') }}</span>
            <span>{{ skill.body_chars }} 字</span>
          </div>
        </div>
        <button type="button" class="skill__link" @click="viewBody(skill.name)">查看说明</button>
      </li>
    </ul>

    <!-- 解析失败的文件：直接摊开，用户能照着原因去修 -->
    <div v-if="snapshot?.errors.length" class="skills__errors">
      <p class="skills__errors-title">有 {{ snapshot.errors.length }} 个技能没能加载：</p>
      <p v-for="item in snapshot.errors" :key="item.path" class="skills__error">
        <code>{{ item.path }}</code><br />{{ item.reason }}
      </p>
    </div>

    <p v-if="snapshot" class="skills__hint">
      技能只是"给模型的说明书"，它调用的工具仍要过权限确认 —— 装了技能不会绕过任何安全护栏。
    </p>
  </div>
</template>

<style scoped>
.skills {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 12px;
}

.skills__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.skills__count {
  font-size: 12px;
  color: var(--color-text-muted);
}

.skills__actions {
  display: flex;
  gap: 8px;
}

.skills__btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 7px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.skills__btn:hover:not(:disabled) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.skills__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.skills__empty,
.skills__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.skills__empty code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-primary);
}

.skills__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.skill {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 6px;
  border-radius: 8px;
}

.skill:hover {
  background: var(--color-surface-2);
}

.skill__check {
  margin-top: 3px;
}

.skill__main {
  flex: 1;
  min-width: 0;
}

.skill__name {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--color-text);
}

.skill__tag {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  font-size: 10px;
  font-weight: 400;
  color: var(--color-text-muted);
}

.skill__desc {
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.skill__meta {
  display: flex;
  gap: 12px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--color-text-muted);
  opacity: 0.85;
}

.skill__link {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 0;
  white-space: nowrap;
}

.skills__errors {
  padding: 10px;
  border: 1px dashed var(--color-danger);
  border-radius: 8px;
  background: var(--color-surface-2);
}

.skills__errors-title {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--color-danger);
}

.skills__error {
  margin: 0 0 6px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-text-muted);
  word-break: break-all;
}
</style>
