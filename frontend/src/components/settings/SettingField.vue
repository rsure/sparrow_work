<!--
  components/settings/SettingField.vue
  单个设置项的「按 type 分派控件」渲染器：
    bool   → van-switch
    int    → van-field(type=number, 含 min/max)
    float  → van-field(type=number, step=0.1)
    string → van-field
    select → van-dropdown-menu（取 SettingDef.options）
    json   → van-field(type=textarea) + 「保存」按钮（避免每按一个键都打后端）

  本组件完全由 SettingDef 驱动：拿到 def + current + onChange 三个输入，渲染出合适的控件。
  这样后端以后加新键、新 type，只需要在渲染器表里加一支，无需改调用方。
-->
<script setup lang="ts">
/**
 * SettingField —— 把 SettingDef + current value 转成合适的 Vant 控件，并把改动上报。
 *
 * 改动策略（与 type 有关）：
 *   - bool / select：用户改完立刻 commit（onChange → saveOne），无需「保存」按钮
 *   - int / float / string：使用本地 draft 缓冲输入，回车或失焦时 commit
 *   - json：textarea 一段文本，单独一个「保存」按钮（编辑成本高，按钮更明确）
 */
import { computed, ref, watch } from 'vue' // 响应式工具：ref 存本地 draft，watch 同步外部值，computed 派生展示文案
import { useSettingsStore } from '@/stores/settings' // 写入走 store：saveOne / saveMany 都在那
import type { SettingDef } from '@/services/settings' // 设置项的 schema

const props = defineProps<{
  /** 单个设置项的 schema（键、类型、默认值、范围、提示） */
  def: SettingDef
}>()

const store = useSettingsStore()

/** 当前值的运行时状态（pending/error/lastSavedAt）；store 里没有时回落到本地构造一个 */
const entry = computed(() => store.entries[props.def.key])

/** 把 unknown 转成控件需要的字符串版本（textarea / 文本输入框用） */
function toText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  // 数字 / 布尔直接字符串化；对象 / 数组用 JSON 序列化（json 类型专用）
  return JSON.stringify(value, null, 2)
}

/** 把字符串转成对应的基础类型（解析失败时返回原值，校验交给后端） */
function fromText(text: string, type: string): unknown {
  if (type === 'int') return Number.parseInt(text, 10)
  if (type === 'float') return Number.parseFloat(text)
  return text
}

/** 本地草稿：text / number / string 控件的输入框用它，避免每按一键就调后端 */
const draft = ref(toText(entry.value?.value ?? props.def.default))
/** bool 控件的本地草稿（开关的「瞬时态」也要单独存一份，便于在 pending 期间反馈） */
const boolDraft = ref(Boolean(entry.value?.value ?? props.def.default))

// 当 store 里值变化时（例如别人改了设置页），把 draft 同步过去（但用户在编辑时不打断）
watch(
  () => entry.value?.value,
  (newVal) => {
    if (newVal === undefined) return
    // 控件类型为文本/数字时同步 draft；bool/select 不需要 draft 同步
    if (props.def.type === 'bool') {
      boolDraft.value = Boolean(newVal)
    } else if (props.def.type !== 'select') {
      draft.value = toText(newVal)
    }
  },
)

/** json 类型专用：textarea 内容（保存前不动 store，避免一边输入一边显示「已保存」） */
const jsonDraft = ref(toText(entry.value?.value ?? props.def.default))
watch(
  () => entry.value?.value,
  (newVal) => {
    if (newVal === undefined) return
    jsonDraft.value = toText(newVal)
  },
)

// ----------------------------------------------------------------------------
// 1. bool：van-switch
// ----------------------------------------------------------------------------
/** switch 切换时立即保存（设置项都是单键的 bool，开关本身就是意图） */
async function onBoolChange(value: boolean): Promise<void> {
  boolDraft.value = value
  await store.saveOne(props.def.key, value)
}

// ----------------------------------------------------------------------------
// 2. int / float / string：van-field(number/text)
// ----------------------------------------------------------------------------
/** 输入框失焦或回车时尝试保存：只有值真的变了才调后端，避免空操作 */
async function commitDraft(): Promise<void> {
  if (!entry.value) return
  const text = draft.value
  const parsed = fromText(text, props.def.type)
  // 比较时统一成字符串，避免「数字 1 vs 字符串 "1」之类的不必要请求
  if (String(parsed) === String(entry.value.value)) return
  await store.saveOne(props.def.key, parsed)
}

// ----------------------------------------------------------------------------
// 3. select：van-dropdown-menu
// ----------------------------------------------------------------------------
/**
 * select 类型的下拉选项数组（[{ text, value }]）。
 * text 优先取后端给的中文标签（`option_labels`），没有就退回原值——
 * 值本身是存库契约（英文），绝不能为了显示去改它。
 */
const selectOptions = computed<Array<{ text: string; value: string }>>(() => {
  const opts = props.def.options ?? []
  const labels = props.def.option_labels ?? []
  return opts.map((opt, index) => ({ text: labels[index] || opt, value: opt }))
})
/** select 当前值（string）；meta 里没值时回落 default（兜底也应为 string） */
const selectValue = computed<string>(() => {
  const v = entry.value?.value
  return typeof v === 'string' ? v : String(props.def.default ?? '')
})
/** 下拉切换时立即保存 */
async function onSelectChange(value: unknown): Promise<void> {
  if (typeof value !== 'string') return
  if (value === selectValue.value) return
  await store.saveOne(props.def.key, value)
}

// ----------------------------------------------------------------------------
// 4. json：textarea + 「保存」按钮
// ----------------------------------------------------------------------------
/** json 是否正在「未保存」状态（textarea 内容与当前值不一致） */
const jsonDirty = computed(() => {
  if (!entry.value) return false
  return jsonDraft.value !== toText(entry.value.value)
})
/** 点击「保存」按钮：解析 → saveMany（一次只写一个键也行，但 saveMany 内部走同一接口） */
async function commitJson(): Promise<void> {
  let parsed: unknown
  try {
    parsed = JSON.parse(jsonDraft.value)
  } catch {
    // 解析失败不写库，让 entry.error 显示一行提示
    if (entry.value) entry.value.error = 'JSON 解析失败：请检查括号/逗号/引号'
    return
  }
  await store.saveMany({ [props.def.key]: parsed })
}

// ----------------------------------------------------------------------------
// 5. 数值类型提示文案
// ----------------------------------------------------------------------------
/** 数值控件的 min/max 限制（Vant 用 string 接收） */
const numAttrs = computed(() => {
  if (props.def.type === 'int' || props.def.type === 'float') {
    return {
      min: props.def.min ?? undefined,
      max: props.def.max ?? undefined,
      step: props.def.type === 'float' ? 0.1 : 1,
    }
  }
  return null
})
</script>

<template>
  <div class="setting-field" :class="{ 'setting-field--busy': entry?.pending }">
    <!-- 顶部：标题 + 说明 + 右侧状态徽标（保存中/已保存/出错） -->
    <div class="setting-field__head">
      <!-- 标题用中文名；key 作为次要信息放右边，排查配置时仍然能对上 -->
      <label class="setting-field__label" :for="`sf-${def.key}`">{{ def.label || def.key }}</label>
      <code v-if="def.label" class="setting-field__key">{{ def.key }}</code>
      <p v-if="def.description" class="setting-field__desc">{{ def.description }}</p>
    </div>
    <div class="setting-field__status">
      <span v-if="entry?.pending" class="badge badge--busy">保存中…</span>
      <span v-else-if="entry?.error" class="badge badge--error">保存失败</span>
      <span v-else-if="entry?.lastSavedAt" class="badge badge--ok">已保存 {{ entry.lastSavedAt }}</span>
    </div>

    <!-- 控件区：按 def.type 分派 -->
    <div class="setting-field__control">
      <!-- bool：开关 -->
      <van-switch
        v-if="def.type === 'bool'"
        :model-value="boolDraft"
        :loading="entry?.pending"
        :disabled="entry?.pending"
        @update:model-value="onBoolChange"
      />

      <!-- int / float：数字输入 -->
      <van-field
        v-else-if="def.type === 'int' || def.type === 'float'"
        :id="`sf-${def.key}`"
        :model-value="draft"
        type="number"
        :min="numAttrs?.min"
        :max="numAttrs?.max"
        :step="numAttrs?.step"
        placeholder=""
        :disabled="entry?.pending"
        @update:model-value="draft = String($event ?? '')"
        @blur="commitDraft"
        @keyup.enter="commitDraft"
      />

      <!-- string：单行文本 -->
      <van-field
        v-else-if="def.type === 'string'"
        :id="`sf-${def.key}`"
        :model-value="draft"
        type="text"
        placeholder=""
        :disabled="entry?.pending"
        @update:model-value="draft = String($event ?? '')"
        @blur="commitDraft"
        @keyup.enter="commitDraft"
      />

      <!-- select：原生下拉。
           为什么不用 van-dropdown-menu：它是"就地展开"的面板，会被卡片/滚动容器裁切，
           表现为"点开被切掉一半"；改用原生 select 后弹层由系统绘制，永远不会越界。 -->
      <select
        v-else-if="def.type === 'select'"
        :id="`sf-${def.key}`"
        class="setting-field__select"
        :value="selectValue"
        :disabled="entry?.pending"
        @change="onSelectChange(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="opt in selectOptions" :key="opt.value" :value="opt.value">
          {{ opt.text }}
        </option>
      </select>

      <!-- json：textarea + 单独「保存」按钮 -->
      <template v-else-if="def.type === 'json'">
        <van-field
          :id="`sf-${def.key}`"
          :model-value="jsonDraft"
          type="textarea"
          :rows="4"
          autosize
          placeholder='{"key":"value"}'
          :disabled="entry?.pending"
          @update:model-value="jsonDraft = String($event ?? '')"
        />
        <van-button
          size="small"
          type="primary"
          plain
          :disabled="!jsonDirty || entry?.pending"
          @click="commitJson"
        >
          保存 JSON
        </van-button>
      </template>
    </div>

    <!-- 错误提示：紧贴控件下方；只在有错时显示 -->
    <p v-if="entry?.error" class="setting-field__error">{{ entry.error }}</p>
  </div>
</template>

<style scoped>
.setting-field {
  /* 控件分组：标题 + 控件 + 错误提示 上下排列 */
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 0;
  border-bottom: 1px dashed var(--color-border, #1f2937);
}
.setting-field:last-child {
  border-bottom: none;
}

.setting-field--busy {
  /* 保存中：轻微灰化，让用户能感觉「操作正在生效」 */
  opacity: 0.85;
}

.setting-field__head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.setting-field__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text, #e5e7eb);
}

/* key 作为次要信息：小、灰、等宽，既能对上文档又不抢视线 */
.setting-field__key {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 10px;
  color: var(--color-text-muted, #94a3b8);
  opacity: 0.7;
  margin-top: -2px;
}

.setting-field__desc {
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  margin: 0;
  line-height: 1.5;
}

.setting-field__status {
  /* 状态徽标放在标题右侧：flex row 对齐靠右 */
  margin-left: auto;
  margin-top: -32px;
}

.setting-field__control {
  margin-top: 4px;
}

.setting-field__select {
  width: 100%;
  max-width: 320px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}

.setting-field__select:focus {
  border-color: var(--color-primary);
}

.setting-field__error {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-danger, #ef4444);
}

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid transparent;
}
.badge--busy {
  background: rgba(56, 189, 248, 0.12);
  color: var(--color-primary, #38bdf8);
  border-color: var(--color-primary, #38bdf8);
}
.badge--ok {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
  border-color: #22c55e;
}
.badge--error {
  background: rgba(239, 68, 68, 0.12);
  color: var(--color-danger, #ef4444);
  border-color: var(--color-danger, #ef4444);
}
</style>