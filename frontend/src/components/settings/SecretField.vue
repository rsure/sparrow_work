<!--
  components/settings/SecretField.vue
  密钥输入控件 —— 永不回显明文：
    - 已设置时显示脱敏值（形如 sk-****abcd）+ 「覆盖写入」「删除」两个按钮
    - 未设置时显示「未配置」+ 一个「设置」按钮
    - 写入 / 删除失败时把错误显示在控件下方

  设计动机：后端从不返回密钥明文，前端也「只进不出」——本组件输入框只用来「新增/覆盖」，
  从不显示已有内容。即使内存里曾经短暂出现过明文（用户在 input 框敲的时候），
  保存后组件立刻关掉输入框，只留脱敏展示。
-->
<script setup lang="ts">
/**
 * SecretField —— 密钥的可视化控件。
 * 上层（ModelSection 等）传入密钥的 key 与该供应商是否需要 key；
 * 控件内部维护「输入框展开/折叠」「输入框内容」两个本地状态，
 * 提交 / 删除后从 store 拉一次最新脱敏值刷新显示。
 */
import { computed, onMounted, ref } from 'vue' // 响应式工具：ref 存折叠态与输入值，computed 派生当前状态文案
import { showConfirmDialog, showToast } from 'vant' // Vant 反馈：删除前二次确认，操作结果轻提示
import { useSettingsStore } from '@/stores/settings' // 读写密钥状态走 store：loadSecretStatus / saveSecretValue / removeSecret

const props = defineProps<{
  /** 密钥名（不带 "secrets." 前缀），如 "deepseek.api_key" */
  secretKey: string
  /** 给用户看的密钥展示名（默认直接用 secretKey） */
  label?: string
}>()

const store = useSettingsStore()

/** 当前的密钥脱敏状态；store 里没有时回落为未设置 */
const status = computed(() => store.secretStatuses[props.secretKey] ?? { set: false, masked: null })

/** 是否展开「写入新密钥」输入框（覆盖写入与首次设置共用同一个输入框） */
const editing = ref(false)
/** 输入框里的明文内容；保存成功后立刻清掉，避免在内存里残留 */
const draft = ref('')
/** 是否正在保存（按钮显示 loading，避免重复提交） */
const saving = ref(false)
/** 是否正在删除 */
const deleting = ref(false)
/** 最近一次失败的错误文案；空串表示没有错误 */
const errorText = ref('')

// 进入页面时拉一次当前状态（首次显示「未设置」或「已设置 sk-****abcd」）
onMounted(async () => {
  await store.loadSecretStatus(props.secretKey)
})

/** 标题文案：优先用 label，否则用 secretKey */
const title = computed(() => props.label ?? props.secretKey)

/** 展开输入框（覆盖写入或首次设置都从这里进入） */
function startEdit(): void {
  editing.value = true
  draft.value = ''
  errorText.value = ''
}

/** 取消编辑：折叠输入框 + 清掉草稿 */
function cancelEdit(): void {
  editing.value = false
  draft.value = ''
  errorText.value = ''
}

/**
 * 提交写入：把 draft 推到后端；保存成功后从 store 拿回最新的脱敏状态。
 * 失败时把错误显示在控件下方，不弹全局 toast（避免打扰用户在做的其它设置）。
 */
async function submit(): Promise<void> {
  const value = draft.value.trim()
  if (!value) {
    errorText.value = '密钥不能为空'
    return
  }
  saving.value = true
  errorText.value = ''
  try {
    await store.saveSecretValue(props.secretKey, value)
    // 保存成功：清掉草稿（**明文不再保留在内存**），折叠输入框
    draft.value = ''
    editing.value = false
    showToast('密钥已保存')
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

/** 删除密钥：先弹确认框（删除是不可恢复操作），用户确认后再调接口 */
async function remove(): Promise<void> {
  try {
    await showConfirmDialog({
      title: '删除密钥',
      message: `确认删除「${title.value}」？删除后该供应商将无法调用。`,
    })
  } catch {
    // 用户在弹窗点了取消：showConfirmDialog 抛错，静默忽略
    return
  }
  deleting.value = true
  errorText.value = ''
  try {
    await store.removeSecret(props.secretKey)
    showToast('密钥已删除')
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="secret-field">
    <div class="secret-field__head">
      <span class="secret-field__label">{{ title }}</span>
      <!-- 状态展示：已设置 → 脱敏值；未设置 → 灰字「未配置」 -->
      <span v-if="status.set" class="secret-field__masked">{{ status.masked }}</span>
      <span v-else class="secret-field__missing">未配置</span>
    </div>

    <!-- 非编辑态：覆盖写入 + 删除（删除仅在已设置时显示） -->
    <div v-if="!editing" class="secret-field__actions">
      <van-button size="small" plain type="primary" @click="startEdit">
        {{ status.set ? '覆盖写入' : '设置密钥' }}
      </van-button>
      <van-button
        v-if="status.set"
        size="small"
        plain
        type="danger"
        :loading="deleting"
        :disabled="deleting || saving"
        @click="remove"
      >
        删除
      </van-button>
    </div>

    <!-- 编辑态：输入框 + 保存 + 取消；输入框写「输入即写入」文案，明确告知用户行为 -->
    <div v-else class="secret-field__editor">
      <van-field
        v-model="draft"
        type="password"
        :placeholder="status.set ? '输入新密钥覆盖' : '输入密钥'"
        :disabled="saving"
        autocomplete="off"
      />
      <div class="secret-field__editor-actions">
        <van-button size="small" type="primary" :loading="saving" :disabled="saving" @click="submit">
          保存
        </van-button>
        <van-button size="small" plain :disabled="saving" @click="cancelEdit">取消</van-button>
      </div>
    </div>

    <!-- 错误提示：紧贴控件下方 -->
    <p v-if="errorText" class="secret-field__error">{{ errorText }}</p>
  </div>
</template>

<style scoped>
.secret-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0;
  border-bottom: 1px dashed var(--color-border, #1f2937);
}
.secret-field:last-child {
  border-bottom: none;
}

.secret-field__head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.secret-field__label {
  font-weight: 600;
  font-size: 14px;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
}

.secret-field__masked {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  font-size: 13px;
  color: var(--color-primary, #38bdf8);
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 4px;
  padding: 2px 8px;
}

.secret-field__missing {
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 4px;
  padding: 2px 8px;
}

.secret-field__actions,
.secret-field__editor-actions {
  display: flex;
  gap: 8px;
}

.secret-field__editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.secret-field__error {
  margin: 0;
  font-size: 12px;
  color: var(--color-danger, #ef4444);
}
</style>