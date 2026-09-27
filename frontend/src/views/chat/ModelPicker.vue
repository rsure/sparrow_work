<!--
  views/chat/ModelPicker.vue —— 输入栏旁的「模型」选择面板（UX 收尾：模型胶囊）。
  为什么放在对话页而不是只在设置页：
    换模型是聊天过程中最高频的调整（便宜模型先问、难问题换强模型），
    每次都要跳到设置页、滚到模型区、保存、再跳回来，太远了。
  改的是同一份后端设置（llm.provider / llm.model），所以两边永远一致，不存在"两套配置"。
-->
<script setup lang="ts">
// Vue：computed 派生当前供应商的模型清单，ref 存本地选择，watch 在面板打开时加载数据
import { computed, ref, watch } from 'vue'
// Vant：加载失败 / 保存成功的一次性提示
import { showToast } from 'vant'
// 设置 store：读写 llm.provider / llm.model —— 必须走它而不是直接调接口，
// 否则顶栏模型 chip（读同一个 store）不会跟着变，「三处同步」就断了
import { useSettingsStore } from '@/stores/settings'
// 设置接口：供应商与模型清单（带上下文窗口、价格）
import { fetchProviders, type LlmModel, type LlmProvider } from '@/services/settings'

/** 面板是否展开（由父组件用 store.modelPickerOpen 传进来） */
const props = defineProps<{
  /** true=展开；false=整块不渲染 */
  open: boolean
}>()

/** 关闭面板：点遮罩、点关闭按钮、保存成功后都会抛给父组件去改 store */
const emit = defineEmits<{
  /** 请求关闭面板 */
  (event: 'close'): void
}>()

/** 全部可用供应商（含自定义）；空数组表示还没加载或加载失败 */
const providers = ref<LlmProvider[]>([])
/** 当前选中的供应商 id */
const providerId = ref('')
/** 当前选中的模型名 */
const modelId = ref('')
/** 是否正在加载供应商清单 */
const loading = ref(false)
/** 是否正在保存 */
const saving = ref(false)
/** 加载失败原因；空串表示没失败（面板里直接显示，不做弹窗） */
const loadError = ref('')

// 设置 store：全局唯一的一份「当前设置值」，顶栏 chip 与设置页读的是它
const settings = useSettingsStore()

/** 当前供应商对象（找不到时 null，模板里要判空） */
const current = computed<LlmProvider | null>(
  () => providers.value.find((item) => item.id === providerId.value) ?? null,
)

/** 当前供应商下的模型清单；自定义端点没配好时为 [] */
const models = computed<LlmModel[]>(() => current.value?.models ?? [])

/** 当前选中模型的元数据（用来显示上下文窗口与价格） */
const currentModel = computed<LlmModel | null>(
  () => models.value.find((item) => item.model === modelId.value) ?? null,
)

/**
 * 拉取供应商清单 + 当前设置，初始化两个下拉框。
 *
 * 两个请求互不依赖，用 Promise.all 并行；任一失败都显示同一句提示，
 * 因为对用户来说"面板打不开"就是一个问题，没必要分两种说法。
 */
async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    // 设置已在 AppShell 启动时加载过，这里只在为空时补一次（例如热重载后直接打开面板）
    const [list] = await Promise.all([
      fetchProviders(),
      settings.meta.length > 0 ? Promise.resolve() : settings.loadAll(),
    ])
    providers.value = list.providers
    providerId.value = String(settings.values['llm.provider'] ?? list.providers[0]?.id ?? '')
    modelId.value = String(settings.values['llm.model'] ?? '')
  } catch (error) {
    console.error('加载模型清单失败:', error)
    loadError.value = '加载模型清单失败，请检查后端是否在运行'
  } finally {
    loading.value = false
  }
}

// 每次打开面板都重新拉一次：用户在设置页可能刚改过，缓存会显示过期数据
watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
  { immediate: true },
)

/**
 * 换供应商：把模型切到该供应商的第一个，避免"供应商是 A、模型却是 B 家的"这种脏组合。
 *
 * @param event 下拉框的 change 事件
 */
function onProviderChange(event: Event): void {
  const id = (event.target as HTMLSelectElement).value
  providerId.value = id
  const first = providers.value.find((item) => item.id === id)?.models[0]
  modelId.value = first?.model ?? ''
}

/**
 * 保存选择并关闭面板。
 *
 * 换模型时输入框只改本地 modelId、**不立即保存**：面板打开后是连续的挑选过程，
 * 真正落库放在用户点「使用这个模型」这一刻。
 *
 * 保存成功后**不需要**刷新页面：下一轮聊天后端会重新读设置
 * （chat_controller 每轮开头都取一次 llm.provider / llm.model），
 * 所以立刻生效；正在跑的那一轮不受影响，这在 UI 上是可预期的。
 *
 * 写入口走 store.selectModel：它一并处理「手写的模型名不在预置清单里」的情况
 * （自动登记进 llm.custom_models，否则内置供应商后端会报「没有这个模型」），
 * 并把后端返回的全量值写回 store，顶栏 chip 因此立即更新，不用等下一次刷新。
 */
async function save(): Promise<void> {
  if (!providerId.value || saving.value) return
  const name = modelId.value.trim()
  if (!name) {
    showToast('请选择或输入一个模型名')
    return
  }
  saving.value = true
  try {
    const result = await settings.selectModel(
      providerId.value,
      name,
      models.value.map((item) => item.model),
      current.value?.is_custom ?? false,
    )
    // selectModel 内部走 saveMany：失败会写进对应键的 entry.error（不抛异常），读出来判断是否真存下去了
    const failure = settings.entries['llm.provider']?.error ?? settings.entries['llm.model']?.error ?? ''
    if (failure) {
      showToast(failure)
      return
    }
    // 手写过的新模型名会被登记成自定义模型，提醒一句窗口值是估算的，别以为它知道真实大小
    showToast(
      result.registered
        ? `已使用 ${name}（已登记为自定义模型，请在设置页确认上下文窗口）`
        : `已切换到 ${name}`,
    )
    emit('close')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-if="open" class="mp" @click.self="emit('close')">
    <section class="mp__panel" role="dialog" aria-label="选择模型">
      <header class="mp__head">
        <h3 class="mp__title">选择模型</h3>
        <button type="button" class="mp__close" title="关闭" @click="emit('close')">✕</button>
      </header>

      <p v-if="loadError" class="mp__error">{{ loadError }}</p>
      <p v-else-if="loading" class="mp__hint">加载中…</p>

      <template v-else>
        <label class="mp__field">
          <span class="mp__label">供应商</span>
          <select class="mp__select" :value="providerId" @change="onProviderChange">
            <option v-for="item in providers" :key="item.id" :value="item.id">
              {{ item.label }}{{ item.is_custom ? '（自定义）' : '' }}
            </option>
          </select>
        </label>

        <label class="mp__field">
          <span class="mp__label">模型</span>
          <!-- 下拉建议来自供应商预置清单，但允许直接手写（新发布的模型、中转站别名） -->
          <input
            class="mp__select"
            :value="modelId"
            list="mp-model-options"
            placeholder="可下拉选择，也可直接输入模型名"
            @input="modelId = ($event.target as HTMLInputElement).value"
          />
          <datalist id="mp-model-options">
            <option v-for="item in models" :key="item.model" :value="item.model">
              {{ item.label }}
            </option>
          </datalist>
        </label>

        <!-- 选中模型的元数据：换模型前先看清"窗口多大、多少钱"，比只给一个名字有用 -->
        <ul v-if="currentModel" class="mp__meta">
          <li>上下文窗口：{{ currentModel.context_window.toLocaleString() }} token</li>
          <li>价格：输入 ¥{{ currentModel.price_in }} / 百万 token，输出 ¥{{ currentModel.price_out }}</li>
          <li>
            能力：{{ currentModel.supports_tools ? '支持工具调用' : '不支持工具调用' }} ·
            {{ currentModel.supports_vision ? '支持图片输入' : '不支持图片输入' }}
          </li>
        </ul>

        <footer class="mp__foot">
          <button type="button" class="mp__btn" @click="emit('close')">取消</button>
          <button
            type="button"
            class="mp__btn mp__btn--primary"
            :disabled="!providerId || saving"
            @click="save"
          >
            {{ saving ? '保存中…' : '使用这个模型' }}
          </button>
        </footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.mp {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.32);
}

.mp__panel {
  width: min(420px, calc(100vw - 40px));
  padding: 14px 16px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius, 14px);
  background: var(--color-surface);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
}

.mp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
}

.mp__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.mp__close {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 14px;
  cursor: pointer;
}

.mp__error {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--color-danger);
}

.mp__hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.mp__field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
}

.mp__label {
  flex: none;
  width: 56px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.mp__select {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface-2);
  color: var(--color-text);
  font: inherit;
  font-size: 12px;
}

.mp__meta {
  list-style: none;
  margin: 8px 0 0;
  padding: 8px 10px;
  border: 1px dashed var(--color-border);
  border-radius: 10px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.mp__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
}

.mp__btn {
  padding: 6px 14px;
  border: 1px solid var(--color-border);
  border-radius: 9px;
  background: transparent;
  color: var(--color-text);
  font-size: 12px;
  cursor: pointer;
}

.mp__btn--primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 600;
}

.mp__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
