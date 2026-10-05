<!--
  components/settings/ModelSection.vue
  设置页里「模型」分区的特殊壳：
    - 供应商下拉（来自 /api/llm/providers，标注本地/自定义）
    - 模型名输入框（datalist 下拉建议 + 可自由手写；清单外的名字会自动登记为自定义模型）
    - 密钥输入（用 SecretField，永不回显明文）
    - 测试连接按钮（调 /api/llm/probe，按 error_kind 给不同提示）

  与 meta 驱动的普通 SettingField 不同：本分区包含「联动两个下拉 + 测连通」这种业务逻辑，
  所以单独抽出来；它**仍然**把 provider/model/base_url 这三个键的写入交给 store.saveOne。
-->
<script setup lang="ts">
/**
 * ModelSection —— 「模型」分区的复合控件。
 *
 * 关键设计：
 *   - 「供应商」「模型」下拉来自 /api/llm/providers（内置 + 自定义）
 *   - 「供应商」与 settings.llm.provider 是双向联动：选完供应商会立即写 store，
 *     store 里的变化也会同步到下拉（用于刷新页后保留上次选择）
 *   - 「模型」下拉：内置供应商从 providers[i].models 取；自定义端点允许文本输入（自由模型名）
 *   - 「测试连接」按 probe.error_kind 给三种中文提示，符合 doc/21 ARCH-1 §1.5.C 的设计
 */
import { computed, onMounted, ref, watch } from 'vue' // 响应式工具：ref 存本地态（base_url draft、probe 结果），computed/watch 联动
import { showToast } from 'vant' // Vant 反馈：测试连接的轻提示
import {
  fetchProviders,
  probeLlm,
  type LlmModel,
  type LlmProvider,
  type LlmProbeResult,
} from '@/services/settings' // 接口封装：供应商清单 + 测试连接
import { useSettingsStore, DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW } from '@/stores/settings' // 写入 llm.* 走 store；默认窗口常量用于「手写新模型」的提示文案
import SecretField from './SecretField.vue' // 密钥控件：复用，不重写

const store = useSettingsStore()

// ----------------------------------------------------------------------------
// 1. 数据加载
// ----------------------------------------------------------------------------
/** 全部供应商（内置 + 自定义） */
const providers = ref<LlmProvider[]>([])
/** 是否正在拉供应商清单 */
const loadingProviders = ref(false)
/** 供应商清单拉取失败的错误文案 */
const providersError = ref('')

/** 当前选中的供应商（与 store.entries['llm.provider'].value 保持同步） */
const providerDraft = ref<string>('')

/** base_url 的本地 draft（输入框用，失焦时提交） */
const baseUrlDraft = ref<string>('')

/** 模型名的本地 draft（输入框用，回车/失焦时提交；允许写清单里没有的新模型名） */
const modelDraft = ref<string>('')

/** 测试连接的运行结果（最后一次），用于在按钮下方展示状态 */
const probeResult = ref<LlmProbeResult | null>(null)
/** 是否正在测试（按钮 loading） */
const probing = ref(false)

/** 拉一遍供应商清单（内置 + 自定义）；登记完新模型后也用它刷新，让下拉立刻出现新名字 */
async function loadProviders(): Promise<void> {
  loadingProviders.value = true
  providersError.value = ''
  try {
    const data = await fetchProviders()
    providers.value = data.providers
  } catch (err) {
    providersError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingProviders.value = false
  }
}

/** 进入页面：拉供应商清单；同时把 store 里的 llm.provider / llm.model / llm.base_url 同步到本地 draft */
onMounted(async () => {
  await loadProviders()
  // 同步 store 的当前值到本地 draft
  providerDraft.value = String(store.entries['llm.provider']?.value ?? 'deepseek')
  baseUrlDraft.value = String(store.entries['llm.base_url']?.value ?? '')
  modelDraft.value = String(store.entries['llm.model']?.value ?? '')
})

// store 里的值变化（用户在别处改了设置）时同步 draft
watch(
  () => store.entries['llm.provider']?.value,
  (v) => {
    if (v !== undefined) providerDraft.value = String(v)
  },
)
watch(
  () => store.entries['llm.base_url']?.value,
  (v) => {
    if (v !== undefined) baseUrlDraft.value = String(v)
  },
)
watch(
  () => store.entries['llm.model']?.value,
  (v) => {
    if (v !== undefined) modelDraft.value = String(v)
  },
)

// ----------------------------------------------------------------------------
// 2. 下拉联动
// ----------------------------------------------------------------------------
/** 当前供应商对象（找不到时为 null） */
const currentProvider = computed<LlmProvider | null>(() => {
  return providers.value.find((p) => p.id === providerDraft.value) ?? null
})

/** 当前供应商预置清单里的模型（用于 <datalist> 的下拉建议；同时允许手写清单外的名字） */
const modelOptions = computed<Array<{ text: string; value: string }>>(() => {
  const provider = currentProvider.value
  if (!provider) return []
  return provider.models.map((m: LlmModel) => ({ text: m.label || m.model, value: m.model }))
})

/** 供应商下拉选项数组：[{ text, value }] */
const providerOptions = computed<Array<{ text: string; value: string }>>(() => {
  return providers.value.map((p) => ({
    text: `${p.label}${p.is_custom ? '（自定义）' : p.id === 'ollama' ? '（本地）' : ''}`,
    value: p.id,
  }))
})

/** 选完供应商：保存到 store；若当前模型名不属于新供应商，顺带切到它的第一个模型 */
async function onProviderChange(value: unknown): Promise<void> {
  if (typeof value !== 'string') return
  providerDraft.value = value
  const provider = providers.value.find((p) => p.id === value) ?? null
  const currentName = String(store.entries['llm.model']?.value ?? '')
  // 自定义端点接受任意模型名，保持不动；内置供应商的模型名各家不同，
  // 「供应商是 OpenAI、模型还是 deepseek-flash」这种组合后端必然报错，不如当场顺带纠正
  if (provider && !provider.is_custom && !provider.models.some((m) => m.model === currentName)) {
    const fallback = provider.models[0]?.model ?? ''
    if (fallback) {
      await store.selectModel(provider.id, fallback, provider.models.map((m) => m.model), false)
      showToast(`已切换供应商；模型顺带改为 ${fallback}`)
      return
    }
  }
  await store.saveOne('llm.provider', value)
}

/** 当前生效的模型名（读 store，避免本地 draft 与 store 不同步）；测试连接用它 */
const currentModel = computed<string>(() => {
  return String(store.entries['llm.model']?.value ?? 'deepseek-flash')
})

/** 当前模型在清单里的元数据；手写过、但还没登记成自定义模型时为 null */
const currentModelMeta = computed<LlmModel | null>(() => {
  const provider = currentProvider.value
  if (!provider) return null
  return provider.models.find((m) => m.model === currentModel.value) ?? null
})

/** 把模型元数据拼成一行人类可读的说明：窗口多大、多少钱、支持什么能力 */
function modelMetaText(model: LlmModel): string {
  // 单价为 0 通常是「我们也不知道这家怎么计费」，说明白比显示 ¥0 更诚实
  const price =
    model.price_in > 0 || model.price_out > 0
      ? `输入 ¥${model.price_in} / 输出 ¥${model.price_out}（每百万 token）`
      : '价格未登记'
  const ability = `${model.supports_tools ? '支持工具调用' : '不支持工具调用'} · ${
    model.supports_vision ? '支持图片输入' : '不支持图片输入'
  }`
  return `上下文窗口 ${model.context_window.toLocaleString()} token · ${price} · ${ability}`
}

/**
 * 提交模型名（回车或失焦时调用）。
 *
 * 三种情况：
 *   - 名字没变：什么都不做（避免每次失焦都发一次保存请求）
 *   - 名字在预置清单里：只写 llm.model
 *   - 名字不在清单里（新发布的模型、中转站的别名）：交给 store.selectModel 顺带登记到
 *     llm.custom_models——否则后端「内置供应商不接受清单外模型名」会直接报错
 */
async function commitModel(): Promise<void> {
  const name = modelDraft.value.trim()
  const provider = currentProvider.value
  // 空名字直接忽略：清空输入框不等于「想用一个没有名字的模型」
  if (!name || !provider) return
  if (name === currentModel.value) return

  const result = await store.selectModel(
    provider.id,
    name,
    provider.models.map((m) => m.model),
    provider.is_custom,
  )
  // saveMany 把失败写进对应键的 error（不抛异常），这里读出来就地提示
  const failure = store.entries['llm.model']?.error ?? ''
  if (failure) {
    showToast(failure)
    return
  }
  modelDraft.value = name
  if (result.registered) {
    // 登记后重新拉一次清单，让下面的下拉建议与窗口/价格提示立刻反映这条新模型
    await loadProviders()
    showToast(
      `已登记为自定义模型：${name}（上下文窗口先按 ${DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW.toLocaleString()} token 估算，可在下方「自定义模型」里改准）`,
    )
  }
}

/** base_url 失焦时保存 */
async function commitBaseUrl(): Promise<void> {
  const current = String(store.entries['llm.base_url']?.value ?? '')
  if (baseUrlDraft.value === current) return
  await store.saveOne('llm.base_url', baseUrlDraft.value)
}

/** 当前供应商的密钥键（Ollama 不需要密钥，requires_key=false 时隐藏 SecretField） */
const secretKey = computed<string>(() => {
  const provider = currentProvider.value
  if (!provider) return ''
  // 内置供应商密钥键：deepseek -> deepseek.api_key 等
  // 自定义供应商密钥键：custom-<id>.api_key（与后端 secret_key_for 一致）
  return provider.requires_key ? `${provider.id}.api_key` : ''
})

// ----------------------------------------------------------------------------
// 3. 测试连接
// ----------------------------------------------------------------------------
/**
 * 把 probe.error_kind 映射成中文提示文案：
 *  - secret  → 「请检查 API Key 是否正确或已配置」
 *  - model   → 「该供应商下没有这个模型名，请重新选择」
 *  - network → 「请检查网络或代理设置」
 *  - 其它    → 用后端给的 error 文案
 */
function probeHintText(result: LlmProbeResult): string {
  if (result.ok) return ''
  switch (result.error_kind) {
    case 'secret':
      return '请检查 API Key 是否正确或已配置'
    case 'model':
      return '该供应商下没有这个模型名，请重新选择'
    case 'network':
      return '请检查网络或代理设置'
    default:
      return result.error ?? '未知错误'
  }
}

/** 点击「测试连接」：调 probe，按 result 弹 toast / 写提示 */
async function handleProbe(): Promise<void> {
  probing.value = true
  probeResult.value = null
  try {
    const result = await probeLlm({
      provider: providerDraft.value,
      model: currentModel.value,
      base_url: baseUrlDraft.value || null,
    })
    probeResult.value = result
    if (result.ok) {
      showToast(`连接成功（${result.latency_ms} ms）`)
    } else {
      showToast(probeHintText(result))
    }
  } catch (err) {
    // 请求层面的失败（HTTP 错、ApiError）；这里直接展示通用兜底
    probeResult.value = {
      ok: false,
      latency_ms: 0,
      error: err instanceof Error ? err.message : String(err),
      error_kind: null,
    }
    showToast('测试失败，请检查后端是否启动')
  } finally {
    probing.value = false
  }
}
</script>

<template>
  <div class="model-section">
    <p v-if="providersError" class="model-section__error">供应商清单加载失败：{{ providersError }}</p>

    <!-- 供应商 -->
    <div class="model-section__row">
      <label class="model-section__label">供应商</label>
      <!-- 原生 select：弹层由系统绘制，不会被卡片/滚动容器裁切 -->
      <select
        class="model-section__select"
        :value="providerDraft"
        :disabled="loadingProviders || providers.length === 0"
        @change="onProviderChange(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
          {{ opt.text }}
        </option>
      </select>
    </div>

    <!-- 模型：可下拉选（预置清单），也可直接手写（新模型/中转站别名）；回车或失焦生效 -->
    <div class="model-section__row">
      <label class="model-section__label">模型</label>
      <input
        v-model="modelDraft"
        class="model-section__select"
        type="text"
        list="llm-model-options"
        placeholder="可下拉选择，也可直接输入模型名（如 deepseek-flash）"
        @change="commitModel"
        @blur="commitModel"
        @keyup.enter="commitModel"
      />
      <!-- 原生 datalist：下拉由系统绘制（不会被卡片裁切），又允许输入清单外的名字 -->
      <datalist id="llm-model-options">
        <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
          {{ opt.text }}
        </option>
      </datalist>
      <!-- 选中模型的元数据：换模型前先看清「窗口多大、多少钱」，比只给一个名字有用 -->
      <p v-if="currentModelMeta" class="model-section__meta">{{ modelMetaText(currentModelMeta) }}</p>
      <p v-else-if="currentModel" class="model-section__meta">
        当前模型名不在预置清单里；保存后会自动登记成自定义模型（上下文窗口先按估算值填，可在下方改准）
      </p>
    </div>

    <!-- base_url -->
    <div class="model-section__row">
      <label class="model-section__label">接口地址（base_url）</label>
      <van-field
        v-model="baseUrlDraft"
        type="text"
        placeholder="留空使用供应商官方地址"
        @blur="commitBaseUrl"
      />
    </div>

    <!-- 密钥（Ollama 等不需要密钥的供应商隐藏这一项） -->
    <div v-if="secretKey" class="model-section__row">
      <SecretField :secret-key="secretKey" :label="`密钥（${providerDraft}.api_key）`" />
    </div>

    <!-- 测试连接 -->
    <div class="model-section__probe">
      <van-button
        size="small"
        type="primary"
        :disabled="probing || !providerDraft"
        :loading="probing"
        @click="handleProbe"
      >
        测试连接
      </van-button>
      <span v-if="probeResult" class="model-section__probe-result" :class="{ ok: probeResult.ok }">
        <template v-if="probeResult.ok">
          ✓ 连接成功（{{ probeResult.latency_ms }} ms）
        </template>
        <template v-else>
          ✗ {{ probeHintText(probeResult) }}
          <span v-if="probeResult.error" class="model-section__probe-detail">{{ probeResult.error }}</span>
        </template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.model-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.model-section__select {
  width: 100%;
  max-width: 320px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text);
  font-size: 13px;
  /* 这个类同时用在 <select>（供应商）与 <input>（模型名）上：input 不会自动继承字体，显式指定 */
  font-family: inherit;
  outline: none;
  cursor: pointer;
}

.model-section__select:focus {
  border-color: var(--color-primary);
}

/* 选中模型的一行元数据（窗口/价格/能力）：比正文小一号，不抢控件的注意力 */
.model-section__meta {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-text-muted, #94a3b8);
}

.model-section__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--color-border, #1f2937);
}
.model-section__row:last-of-type {
  border-bottom: none;
}

.model-section__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text, #e5e7eb);
}

.model-section__probe {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 8px;
}

.model-section__probe-result {
  font-size: 12px;
  color: var(--color-danger, #ef4444);
}
.model-section__probe-result.ok {
  color: #22c55e;
}
.model-section__probe-detail {
  margin-left: 8px;
  font-size: 11px;
  color: var(--color-text-muted, #94a3b8);
}

.model-section__error {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--color-danger, #ef4444);
}
</style>