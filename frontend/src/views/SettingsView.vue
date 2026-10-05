<!--
  views/SettingsView.vue
  设置页主体：完全由 meta 驱动渲染。
  - 进入页面：并行拉 meta + 当前值 + 工作区
  - 渲染：按 category 自动分区（model / tools / context / agent / advanced / workspaces）
  - model 分区用 ModelSection（联动下拉 + 测连通）
  - workspaces 分区用 WorkspaceSection（CRUD）
  - 其它分区按 SettingDef 一键渲染 SettingField
  - 顶部「刷新」按钮允许用户手动重新拉一遍
-->
<script setup lang="ts">
/**
 * SettingsView —— 设置页主体。
 * 视觉骨架：顶部标题 + 顶部错误/刷新条 + 下方一组 SettingSection。
 * 数据骨架：store.settings 持有 meta/values/entries，store.workspaces 持有工作区。
 * 本视图不直接调用 API，全部经 store。
 */
import { computed, onActivated, onMounted } from 'vue' // 响应式工具与生命周期：computed 派生分区列表，onMounted/onActivated 拉数据
import { useSettingsStore } from '@/stores/settings' // 普通设置 + 密钥的全局状态
// 设置项声明的类型：modelExtraDefs 的返回值需要标注 SettingDef[]，读 meta 时也用得上
import type { SettingDef } from '@/services/settings'
import { useWorkspacesStore } from '@/stores/workspaces' // 工作区的全局状态
import SettingField from '@/components/settings/SettingField.vue' // 单个设置项的控件渲染器
import SettingSection from '@/components/settings/SettingSection.vue' // 单个分区的容器
import ModelSection from '@/components/settings/ModelSection.vue' // 模型分区的复合控件
import WorkspaceSection from '@/components/settings/WorkspaceSection.vue' // 工作区分区的管理面板
import SkillSection from '@/components/settings/SkillSection.vue' // 技能分区：列表 + 启停 + 重扫
import McpSection from '@/components/settings/McpSection.vue' // MCP 分区：连接状态 + 重连 + 单条测试
import MemorySection from '@/components/settings/MemorySection.vue' // 记忆分区：列表 + 检索 + 增删
import TransferSection from '@/components/settings/TransferSection.vue' // 配置迁移：导出脱敏 JSON / 导入配置（OPS-5）

const settingsStore = useSettingsStore()
const workspacesStore = useWorkspacesStore()

/** 第一次进入页面 + KeepAlive 缓存页被再次激活时都重新拉一次数据 */
onMounted(async () => {
  await Promise.all([settingsStore.loadAll(), workspacesStore.loadAll()])
})
onActivated(async () => {
  // KeepAlive 缓存页被激活时再拉一次；后台可能改了设置
  await Promise.all([settingsStore.loadAll(), workspacesStore.loadAll()])
})

/** 手动刷新按钮：与初次进入等价 */
async function handleRefresh(): Promise<void> {
  await Promise.all([settingsStore.loadAll(), workspacesStore.loadAll()])
}

/**
 * meta 分区列表（按出现顺序保留）：用于遍历渲染 SettingSection。
 * 直接拿 store.metaByCategory 的 keys，避免引入硬编码的 category 列表。
 */
const categories = computed<string[]>(() => Object.keys(settingsStore.metaByCategory))

/**
 * 设置分组：把十几个 category 收成 7 组。
 *
 * 为什么还需要这一层（后端已经按 category 分过区了）：
 *   五十个键平铺成十四张卡片，用户根本不知道从哪看起。
 *   分组回答的是"我该先看哪一块"：先外观、再模型、再安全，扩展与诊断放后面。
 *   组内顺序就是数组顺序，不依赖字母序（字母序会把"预算保护"排到"外观"前面）。
 */
const GROUPS: Array<{ title: string; hint: string; categories: string[] }> = [
  { title: '外观与输入', hint: '先把它调成你顺手的样子', categories: ['theme', 'input'] },
  { title: '模型', hint: '决定回答质量与花费', categories: ['model'] },
  { title: '安全与预算', hint: 'AI 能做什么、最多花多少', categories: ['permission', 'cost'] },
  { title: '任务与上下文', hint: '复杂任务怎么拆、上下文怎么管', categories: ['task', 'context', 'agent', 'tools'] },
  { title: '扩展能力', hint: '技能、外部 MCP 服务与本地 Office 引擎', categories: ['skill', 'mcp', 'office'] },
  { title: '记忆', hint: 'AI 关于这个工作区记住了什么（看得见、能删、能补）', categories: ['memory'] },
  { title: '工作区', hint: '允许读写的目录', categories: ['workspace'] },
  { title: '诊断与维护', hint: '平时不用动，出问题再看', categories: ['diagnostic', 'advanced'] },
]

/**
 * 按分组整理后的渲染计划。
 *
 * 两件事：
 *   1. 组内只保留**后端真的返回了**的 category（某个模块没注册时不该出现空标题）；
 *   2. 后端新增了没登记过的 category → 收进最后的「其它」，不会静默消失。
 */
const groupedCategories = computed(() => {
  const available = new Set(categories.value)
  const known = new Set(GROUPS.flatMap((group) => group.categories))

  const groups = GROUPS
    .map((group) => ({
      title: group.title,
      hint: group.hint,
      categories: group.categories.filter((cat) => available.has(cat)),
    }))
    .filter((group) => group.categories.length > 0)

  const rest = categories.value.filter((cat) => !known.has(cat)).sort()
  if (rest.length) {
    groups.push({ title: '其它', hint: '后端新增的设置项', categories: rest })
  }
  return groups
})

/**
 * 决定某个 category 用哪种渲染方式：
 *   - model：ModelSection（联动下拉 + 测试连接）
 *   - workspace：WorkspaceSection（CRUD）；后端 workspaces.* 键的 category 是单数 "workspace"
 *   - 其它：用 SettingField 列表，按 meta 遍历渲染
 */
function renderMode(
  category: string,
): 'model' | 'workspaces' | 'skills' | 'mcp' | 'memory' | 'fields' {
  if (category === 'model') return 'model'
  if (category === 'workspace') return 'workspaces'
  // 技能是"列表型"数据（名字/描述/解析错误），meta 驱动的字段渲染不出来
  if (category === 'skill') return 'skills'
  // MCP 同理：连接状态、工具清单、失败原因都不是"一个值"
  if (category === 'mcp') return 'mcp'
  // 记忆是最典型的"列表型"：条数、正文、重要度，一个输入框表达不了
  if (category === 'memory') return 'memory'
  return 'fields'
}

/**
 * 「模型」分区里已经由 ModelSection 单独渲染的三个键。
 *
 * 为什么要排除它们：provider/model/base_url 三者互相联动（换供应商要顺带换模型、
 * base_url 要配合供应商），如果再让 SettingField 各渲染一个输入框，
 * 同一个值就有了两个控件，用户改了 A 框 B 框不刷新，看起来像「设置没生效」。
 */
const MODEL_SECTION_KEYS = new Set(['llm.provider', 'llm.model', 'llm.base_url'])

/**
 * 模型分区里「交给普通 SettingField 渲染」的键：温度、单轮输出上限、自定义模型/端点 JSON。
 *
 * @param category 设置项分类（"model"）
 * @return 该分类下未由 ModelSection 接管的 SettingDef 列表（保持后端声明顺序）
 */
function modelExtraDefs(category: string): SettingDef[] {
  return (settingsStore.metaByCategory[category] ?? []).filter(
    (def) => !MODEL_SECTION_KEYS.has(def.key),
  )
}
</script>

<template>
  <section class="settings-view">
    <header class="settings-view__head">
      <h1>设置</h1>
      <p class="muted">
        按用途分组的全部配置；改动即时生效，不需要重启应用。
      </p>
      <div class="settings-view__bar">
        <van-button size="small" plain :loading="settingsStore.loading" @click="handleRefresh">
          刷新
        </van-button>
      </div>
    </header>

    <!-- 整页加载失败的兜底提示 -->
    <div v-if="settingsStore.loadError" class="settings-view__error">
      加载失败：{{ settingsStore.loadError }}
    </div>

    <!-- 加载中（首屏） -->
    <div v-else-if="settingsStore.loading && settingsStore.meta.length === 0" class="settings-view__loading">
      加载中…
    </div>

    <!-- 正常渲染：先按「分组」分块，块内再按 category 出卡片 -->
    <template v-else>
      <div v-for="group in groupedCategories" :key="group.title" class="settings-view__group">
        <div class="settings-view__group-head">
          <h2 class="settings-view__group-title">{{ group.title }}</h2>
          <p class="settings-view__group-hint">{{ group.hint }}</p>
        </div>

        <SettingSection
          v-for="category in group.categories"
          :key="category"
          :category="category"
        >
        <!-- 模型分区：联动控件（供应商/模型名/密钥/测连通）+ 其余模型设置项 -->
        <template v-if="renderMode(category) === 'model'">
          <ModelSection />
          <!--
            温度、单轮输出上限、自定义模型/端点 JSON 都还是普通键，必须继续渲染出来；
            否则「设置页里没有能调模型的地方」——只能选个名字，却改不了任何参数。
          -->
          <SettingField
            v-for="def in modelExtraDefs(category)"
            :key="def.key"
            :def="def"
          />
        </template>

        <!-- 工作区分区：CRUD 面板 -->
        <WorkspaceSection v-else-if="renderMode(category) === 'workspaces'" />

        <!-- MCP 分区：先列连接状态，再渲染开关与 server JSON -->
        <template v-else-if="renderMode(category) === 'mcp'">
          <McpSection />
          <SettingField
            v-for="def in settingsStore.metaByCategory[category]"
            :key="def.key"
            :def="def"
          />
        </template>

        <!-- 记忆分区：先列记忆（可检索/增删），再渲染开关与阈值等设置项 -->
        <template v-else-if="renderMode(category) === 'memory'">
          <MemorySection />
          <SettingField
            v-for="def in settingsStore.metaByCategory[category]"
            :key="def.key"
            :def="def"
          />
        </template>

        <!-- 技能分区：先列已安装技能，再渲染开关与目录等设置项 -->
        <template v-else-if="renderMode(category) === 'skills'">
          <SkillSection />
          <SettingField
            v-for="def in settingsStore.metaByCategory[category]"
            :key="def.key"
            :def="def"
          />
        </template>

        <!-- 其它分区：每个 SettingDef 渲染一个 SettingField -->
        <template v-else>
          <SettingField
            v-for="def in settingsStore.metaByCategory[category]"
            :key="def.key"
            :def="def"
          />
        </template>
        </SettingSection>
      </div>

      <!-- 兜底：万一 meta 是空数组，提示用户「后端没注册任何设置项」 -->
      <div v-if="groupedCategories.length === 0" class="settings-view__empty">
        后端尚未注册任何设置项。
      </div>

      <!--
        配置导入导出（OPS-5）：不属于任何后端 category，固定挂在最后一块。
        放在最下面是因为它是一次性操作（换机器/重装前才用），不该抢首屏注意力。
      -->
      <div class="settings-view__group">
        <div class="settings-view__group-head">
          <h2 class="settings-view__group-title">配置迁移</h2>
          <p class="settings-view__group-hint">换机器或重装系统前导出一份；导入时密钥不会被带过去</p>
        </div>
        <SettingSection category="transfer">
          <TransferSection />
        </SettingSection>
      </div>
    </template>
  </section>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-view__head h1 {
  margin: 0 0 4px;
  font-size: 24px;
}

.settings-view__group {
  margin-bottom: 8px;
}

.settings-view__group-head {
  margin: 22px 0 8px;
}

.settings-view__group-head:first-child {
  margin-top: 0;
}

.settings-view__group-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--color-text-muted);
  text-transform: uppercase;
}

.settings-view__group-hint {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
  opacity: 0.8;
}

.settings-view__bar {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.settings-view__loading,
.settings-view__empty {
  text-align: center;
  padding: 40px;
  color: var(--color-text-muted, #94a3b8);
}

.settings-view__error {
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid var(--color-danger, #ef4444);
  border-radius: 8px;
  color: var(--color-danger, #ef4444);
}
</style>