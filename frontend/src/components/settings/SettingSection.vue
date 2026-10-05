<!--
  components/settings/SettingSection.vue
  单个设置分区的容器：标题 + 一句说明 + 槽位里的具体设置项。
  本组件本身不渲染任何设置项，只负责把「分区壳」与「里面的内容」分开，
  让 SettingsView.vue 写起来就是「遍历 metaByCategory、每个 category 一个 SettingSection」的扁平结构。
-->
<script setup lang="ts">
/**
 * SettingSection —— 设置页里「同一个 category 下」的所有控件的容器。
 *
 * 两件事：
 *   1. 把 category 翻成中文标题 + 一句人话说明（用户不该看到 `theme.preset` 这种内部名）；
 *   2. 提供卡片外观。**颜色必须走主题变量**——这里曾经写成 `--color-surface-1`（不存在的变量），
 *      导致卡片永远回落到深色，浅色主题下整页发黑。改动这里时请确认变量名在 main.css 里存在。
 */
import { computed } from 'vue' // 响应式工具：computed 派生 category 的中文标题

/** 分区元信息：中文标题 + 人话说明（新增 category 时在这里补一条，否则标题会显示英文 id） */
const CATEGORY_META: Record<string, { title: string; hint: string }> = {
  theme: { title: '外观', hint: '配色、圆角与字号；改完立即生效，不需要重启' },
  input: { title: '输入', hint: '输入框的回车行为与快捷操作' },
  model: { title: '模型', hint: '用哪个供应商、哪个模型，以及调用参数' },
  permission: { title: '权限', hint: 'AI 动你的文件或执行命令之前，要不要先问你' },
  cost: { title: '预算保护', hint: '单个任务的花费、时长与 token 上限，超出会暂停询问' },
  task: { title: '复杂任务拆分', hint: '多步任务自动拆成子任务逐个执行，并做冲突与校验保护' },
  context: { title: '上下文', hint: '长对话如何压缩、工具输出多长会被截断' },
  agent: { title: 'Agent 行为', hint: '单轮能走多少步、能否中途插话、是否启用子 agent' },
  tools: { title: '工具', hint: '内置能力的开关（联网工具默认关闭）' },
  skill: { title: '技能', hint: '把「怎么做」写成说明书交给模型，可随时安装/停用' },
  mcp: { title: 'MCP 服务', hint: '接入外部 MCP server 的工具，默认每次调用都要确认' },
  office: { title: '本地 Office 引擎', hint: '用已打开的 Word/Excel/PPT 读原文；关掉后改用内置解析器' },
  memory: { title: '记忆明细', hint: '记忆的开关与阈值；上面的列表是当前工作区已经记住的内容' },
  diagnostic: { title: '诊断', hint: '日志级别与执行轨迹留存；出问题时用来取证' },
  advanced: { title: '高级', hint: '不常改的开关，改动前建议先了解影响' },
  // 后端 workspaces.* 键的 category 是单数 "workspace"，渲染时统一显示「工作区」
  workspace: { title: '工作区', hint: '允许 AI 读写的目录范围；切换后立即生效' },
  // 配置导入导出（OPS-5）不是后端 category，而是设置页里固定的一块卡片
  transfer: { title: '配置导入导出', hint: '备份当前配置，或迁移到另一台机器' },
}

const props = defineProps<{
  /** 分区 id（category 字符串）；同时作为标题与锚点 */
  category: string
}>()

/** 分区元信息：没登记过的 category 用兜底（标题显示 id，说明留空） */
const meta = computed(
  () => CATEGORY_META[props.category] ?? { title: props.category, hint: '' },
)
</script>

<template>
  <section class="setting-section">
    <header class="setting-section__head">
      <h2 class="setting-section__title">{{ meta.title }}</h2>
      <p v-if="meta.hint" class="setting-section__hint">{{ meta.hint }}</p>
      <!-- 默认插槽：父组件把 SettingField 列表塞到这里；用 <div> 包裹避免样式塌陷 -->
      <div class="setting-section__body">
        <slot />
      </div>
    </header>
  </section>
</template>

<style scoped>
.setting-section {
  /* 卡片外形：圆角 + 边框 + 主题卡片色。
     注意：变量名必须是 main.css 里真实存在的（--color-surface，不是 --color-surface-1） */
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 16px;
}

.setting-section__title {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  color: var(--color-text);
}

.setting-section__hint {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-muted);
}

.setting-section__body {
  /* body 里直接放 <SettingField>，每个 SettingField 内部自带 spacing */
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
}
</style>
