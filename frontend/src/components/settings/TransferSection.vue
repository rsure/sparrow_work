<!--
  components/settings/TransferSection.vue
  配置迁移（OPS-5）：把设置导出成一个 JSON 文件，或从 JSON 文件导入。
  - 导出：调后端 GET /api/settings/export，拿到的是**已脱敏**的快照，直接存成文件；
  - 导入：读用户选的 JSON，确认后 POST /api/settings/import，后端逐键校验只写合法的那些。
  为什么脱敏在后端做：哪些键算密钥只有后端知道（密钥名散落在各供应商声明里），
  前端自己拼 JSON 很容易把 MCP 的 env / headers 里的 token 一起导出去。
-->
<script setup lang="ts">
/**
 * TransferSection —— 设置页里的「配置导入导出」卡片。
 *
 * 三个约束（都来自 OPS-5 的验收项）：
 *   1. 导出文件里不能有密钥——由后端保证，本组件只负责落盘；
 *   2. 导入必须让用户确认，因为它会覆盖本机配置；
 *   3. 导入后要把「跳过哪些键、为什么」如实告诉用户，不能只弹「导入成功」。
 */
import { ref } from 'vue' // 响应式工具：ref 存当前操作状态（导出中/导入中）与导入结果明细
import { showConfirmDialog, showToast } from 'vant' // 交互组件：确认对话框 + 轻提示
// 接口封装：导出脱敏配置、导入配置
import { exportSettings, importSettings, type SettingsImportSkipped } from '@/services/settings'
// 全局状态：导入后要刷新设置页，否则界面还显示导入前的旧值
import { useSettingsStore } from '@/stores/settings'
// 全局状态：工作区也在配置里（workspaces.list / workspaces.active_id），导入后同样要刷新
import { useWorkspacesStore } from '@/stores/workspaces'
// 文件下载工具：把字符串存成用户选目录下的文件（复用现有的 Blob + <a download> 实现）
import { download_text_file } from '@/utils/download'

const settingsStore = useSettingsStore()
const workspacesStore = useWorkspacesStore()

/** 导出请求进行中（按钮转圈 + 防重复点击） */
const exporting = ref(false)
/** 导入请求进行中（同上；导入会写库，重复点击更危险） */
const importing = ref(false)
/** 隐藏的文件选择框；点「导入配置」按钮时用脚本触发它 */
const fileInput = ref<HTMLInputElement | null>(null)
/** 最近一次导入被跳过的键与原因；导入后显示在卡片里，让用户知道哪几项没生效 */
const lastSkipped = ref<SettingsImportSkipped[]>([])
/** 最近一次导入真正写入的键数量（0 表示整份配置都没生效） */
const lastAppliedCount = ref(0)

/**
 * 把当前时间压成 `20261023-1530` 形式，用于文件名。
 * 用本地时间而不是 ISO：用户在自己的文件管理器里一眼就能看出先后。
 *
 * @param date 要格式化的时间，默认取当前时间
 * @returns 形如 "20261023-1530" 的字符串
 */
function stamp(date: Date = new Date()): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
    + `-${pad(date.getHours())}${pad(date.getMinutes())}`
}

/**
 * 导出配置：拉脱敏快照 → 序列化成带缩进的 JSON → 触发浏览器下载。
 * 缩进 2 空格是刻意的：这份文件用户会打开看，压成一行就没法读了。
 */
async function handleExport(): Promise<void> {
  if (exporting.value) return
  exporting.value = true
  try {
    const snapshot = await exportSettings()
    const filename = `settings-${snapshot.app_version}-${stamp()}.json`
    download_text_file(filename, JSON.stringify(snapshot, null, 2), 'application/json;charset=utf-8')
    // 密钥不会随配置导出，所以这里要明说一句，避免用户以为备份是完整的
    const secretCount = snapshot.secrets.filter((item) => item.set).length
    showToast(
      secretCount > 0
        ? `已导出 ${filename}（${secretCount} 个密钥未包含，需单独填写）`
        : `已导出 ${filename}`,
    )
  } catch (error) {
    showToast(`导出失败：${String(error)}`)
  } finally {
    exporting.value = false
  }
}

/** 打开系统文件选择框（只接受 .json） */
function pickFile(): void {
  fileInput.value?.click()
}

/**
 * 读用户选中的 JSON 并导入：解析 → 二次确认 → 提交 → 刷新设置页。
 *
 * 解析失败不弹确认框：连 JSON 都不是的文件，没必要让用户再确认一次。
 *
 * @param event 文件输入框的 change 事件
 */
async function handleFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 无论成功失败都清空选择：否则用户再选同一个文件不会触发 change 事件
  input.value = ''
  if (!file) return

  let payload: { format?: string; values?: Record<string, unknown>; redacted_keys?: string[] }
  try {
    payload = JSON.parse(await file.text())
  } catch {
    showToast('这个文件不是合法的 JSON')
    return
  }
  if (!payload || typeof payload.values !== 'object' || payload.values === null) {
    showToast('文件里没有 values 字段，不像是配置备份')
    return
  }
  // 先取到局部变量：payload.values 是可选的，直接往下传时 TS 会认为它可能还是 undefined
  const values = payload.values

  const keyCount = Object.keys(values).length
  try {
    // 导入会覆盖本机同名配置，必须让用户明确点一次
    await showConfirmDialog({
      title: '导入配置',
      message: `将用这份文件里的 ${keyCount} 个设置项覆盖本机配置。\n`
        + '密钥不会随配置文件导入，需要在本页单独填写。',
      confirmButtonText: '导入',
      cancelButtonText: '取消',
    })
  } catch {
    // 用户点了取消：showConfirmDialog 会 reject，这里静默返回即可
    return
  }

  importing.value = true
  try {
    const result = await importSettings({
      format: payload.format,
      values,
      redacted_keys: payload.redacted_keys,
    })
    lastAppliedCount.value = result.applied.length
    lastSkipped.value = result.skipped
    // 导入后必须重新拉：主题、模型、工作区白名单都可能变了，页面上的旧值不能信
    await Promise.all([settingsStore.loadAll(), workspacesStore.loadAll()])
    showToast(
      result.skipped.length > 0
        ? `已导入 ${result.applied.length} 项，跳过 ${result.skipped.length} 项`
        : `已导入 ${result.applied.length} 项`,
    )
  } catch (error) {
    showToast(`导入失败：${String(error)}`)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="transfer">
    <p class="transfer__hint">
      导出的是一份<strong>脱敏</strong>的 JSON：里面没有任何 API Key，
      含密钥的设置项（如 MCP 服务的 env）会被抹成占位符，导入时整项跳过。
      换机器时请先导出，在新机器上导入后再单独填密钥。
    </p>

    <div class="transfer__actions">
      <van-button size="small" type="primary" :loading="exporting" @click="handleExport">
        导出配置
      </van-button>
      <van-button size="small" plain :loading="importing" @click="pickFile">
        导入配置
      </van-button>
      <!-- 隐藏的文件选择框：只接受 JSON；点上面那个按钮时由脚本触发 -->
      <input
        ref="fileInput"
        class="transfer__file"
        type="file"
        accept="application/json,.json"
        @change="handleFileChange"
      >
    </div>

    <!-- 上一次导入的结果明细：让用户知道哪些键没生效、为什么 -->
    <div v-if="lastSkipped.length > 0" class="transfer__skipped">
      <p class="transfer__skipped-title">上次导入跳过了 {{ lastSkipped.length }} 项：</p>
      <ul class="transfer__skipped-list">
        <li v-for="item in lastSkipped" :key="item.key">
          <code>{{ item.key }}</code> —— {{ item.reason }}
        </li>
      </ul>
    </div>
    <p v-else-if="lastAppliedCount > 0" class="transfer__ok">
      上次导入写入 {{ lastAppliedCount }} 项，全部生效。
    </p>
  </div>
</template>

<style scoped>
.transfer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.transfer__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.transfer__actions {
  display: flex;
  gap: 8px;
}

/* 隐藏原生文件输入框：它的样式无法统一，统一用上面的按钮触发 */
.transfer__file {
  display: none;
}

.transfer__skipped {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 8px 12px;
  background: var(--color-surface-2, rgba(148, 163, 184, 0.08));
}

.transfer__skipped-title {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.transfer__skipped-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.transfer__ok {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
