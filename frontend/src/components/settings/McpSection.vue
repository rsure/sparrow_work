<!--
  components/settings/McpSection.vue —— 设置页「MCP」分区（EXT-2）。
  为什么需要自定义组件：
    server 是一个**列表**（连接状态、工具数、失败原因），meta 驱动的 SettingField
    只能渲染"开关 / 文本 / JSON"，表达不了"这个 server 连没连上"。

  交互：
    - 顶部：总工具数 + 「重连」按钮
    - 每个 server 一张卡片：状态点 + 名字 + 传输方式 + 工具清单 + 失败原因 +「单独测试」
    - 配置本身仍然走下面的 SettingField（mcp.servers 是 JSON 文本框），
      这样"改配置"与"看状态"分离，不用为配置写一套表单
-->
<script setup lang="ts">
/**
 * McpSection —— MCP server 状态与重连。
 *
 * 数据来源：`GET /api/mcp/servers`；重连走 `POST /api/mcp/reload`。
 */
// Vue：computed 派生展示数据，onMounted 拉一次，ref 存加载状态
import { computed, onMounted, ref } from 'vue'
// Vant：轻提示
import { showToast } from 'vant'
// MCP 接口：状态 / 重连 / 单条测试
import {
  fetchMcpServers,
  reloadMcpServers,
  testMcpServer,
  type McpSnapshot,
} from '@/services/mcp'
// 设置 store：读 mcp.servers（单条测试要用原始配置）
import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()

/** 当前快照；null 表示还没加载 */
const snapshot = ref<McpSnapshot | null>(null)
/** 是否正在请求（按钮 loading 用） */
const loading = ref(false)
/** 正在单独测试的 server 名；空串表示没有 */
const testing = ref('')

/** 已连接的 server 数 */
const connectedCount = computed(
  () => (snapshot.value?.servers ?? []).filter((item) => item.ok).length,
)

/** 已保存的 server 配置（用于「单独测试」） */
const savedConfigs = computed<Array<Record<string, unknown>>>(() => {
  const value = settings.entries['mcp.servers']?.value
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : []
})

onMounted(load)

/** 拉取状态；失败只提示，不影响同页其它分区 */
async function load(): Promise<void> {
  loading.value = true
  try {
    snapshot.value = await fetchMcpServers()
  } catch (error) {
    console.error('加载 MCP 状态失败:', error)
    showToast('加载 MCP 状态失败')
  } finally {
    loading.value = false
  }
}

/** 重连全部 server（改完 JSON 配置后点它；保存配置只写了库，不会自动连） */
async function reload(): Promise<void> {
  loading.value = true
  try {
    snapshot.value = await reloadMcpServers()
    const failed = snapshot.value.servers.filter((item) => !item.ok).length
    showToast(failed ? `已重连，${failed} 个 server 失败` : `已重连，共 ${snapshot.value.tool_count} 个工具`)
  } catch (error) {
    console.error('重连 MCP 失败:', error)
    showToast('重连失败')
  } finally {
    loading.value = false
  }
}

/**
 * 单独试连某个 server（读已保存的配置，不影响其它 server）。
 *
 * @param name server 名
 */
async function testOne(name: string): Promise<void> {
  const config = savedConfigs.value.find((item) => item.name === name)
  if (!config) {
    showToast('配置里找不到这个 server，请先保存')
    return
  }
  testing.value = name
  try {
    const result = await testMcpServer(config)
    showToast(
      result.ok
        ? `连接成功，${result.tools.length} 个工具（${result.duration_ms}ms）`
        : `连接失败：${result.error.slice(0, 80)}`,
    )
  } catch (error) {
    console.error('测试 MCP server 失败:', error)
    showToast('测试失败')
  } finally {
    testing.value = ''
  }
}
</script>

<template>
  <div class="mcp">
    <div class="mcp__bar">
      <span class="mcp__count">
        <template v-if="snapshot">
          {{ connectedCount }} / {{ snapshot.servers.length }} 个 server 已连接 ·
          {{ snapshot.tool_count }} 个工具
        </template>
        <template v-else>加载中…</template>
      </span>
      <div class="mcp__actions">
        <button type="button" class="mcp__btn" :disabled="loading" @click="reload">
          {{ loading ? '连接中…' : '重连' }}
        </button>
        <button type="button" class="mcp__btn" @click="load">刷新状态</button>
      </div>
    </div>

    <p v-if="snapshot && !snapshot.servers.length" class="mcp__empty">
      还没有配置 MCP server。在下面的 <code>mcp.servers</code> 里加一条（JSON 数组），
      保存后点「重连」即可接入。示例见上方说明。
    </p>

    <ul v-else class="mcp__list">
      <li v-for="server in snapshot?.servers ?? []" :key="server.name" class="server">
        <span class="server__dot" :class="server.ok ? 'server__dot--ok' : 'server__dot--bad'" />
        <div class="server__main">
          <div class="server__name">
            {{ server.name }}
            <span class="server__transport">{{ server.description }}</span>
          </div>
          <div v-if="server.ok" class="server__meta">
            {{ server.tool_count }} 个工具 · {{ server.duration_ms }}ms
          </div>
          <div v-else class="server__error">{{ server.error || '未连接' }}</div>
          <ul v-if="server.ok && server.tools.length" class="server__tools">
            <li v-for="tool in server.tools" :key="tool.name" :title="tool.description">
              {{ tool.raw_name }}
            </li>
          </ul>
        </div>
        <button
          type="button"
          class="server__link"
          :disabled="testing === server.name"
          @click="testOne(server.name)"
        >
          {{ testing === server.name ? '测试中…' : '单独测试' }}
        </button>
      </li>
    </ul>

    <!-- 配置级错误（JSON 写错、缺字段）：与连接错误分开显示，用户知道该改格式还是改网络 -->
    <div v-if="snapshot?.errors.length" class="mcp__errors">
      <p class="mcp__errors-title">有 {{ snapshot.errors.length }} 条配置没能解析：</p>
      <p v-for="(item, index) in snapshot.errors" :key="index" class="mcp__error">{{ item }}</p>
    </div>

    <p v-if="snapshot" class="mcp__hint">
      MCP 工具默认<b>每次调用都要确认</b>；确认框里会显示它来自哪个 server。
      信任某个 server 时，把它加进 <code>mcp.auto_approve_tools</code>（如
      <code>["filesystem"]</code>）。外部 server 提供的工具同样会走审计与输出截断。
    </p>
  </div>
</template>

<style scoped>
.mcp {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 12px;
}

.mcp__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.mcp__count {
  font-size: 12px;
  color: var(--color-text-muted);
}

.mcp__actions {
  display: flex;
  gap: 8px;
}

.mcp__btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 7px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.mcp__btn:hover:not(:disabled) {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.mcp__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mcp__empty,
.mcp__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--color-text-muted);
}

.mcp__empty code,
.mcp__hint code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-primary);
}

.mcp__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.server {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 6px;
  border-radius: 8px;
}

.server:hover {
  background: var(--color-surface-2);
}

.server__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex: none;
}

.server__dot--ok {
  background: var(--color-success, #22c55e);
}

.server__dot--bad {
  background: var(--color-danger);
}

.server__main {
  flex: 1;
  min-width: 0;
}

.server__name {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--color-text);
}

.server__transport {
  margin-left: 8px;
  font-family: inherit;
  font-weight: 400;
  font-size: 11px;
  color: var(--color-text-muted);
  word-break: break-all;
}

.server__meta {
  font-size: 11px;
  color: var(--color-text-muted);
}

.server__error {
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-danger);
  word-break: break-all;
}

.server__tools {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-muted);
}

.server__link {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 0;
  white-space: nowrap;
}

.server__link:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mcp__errors {
  padding: 10px;
  border: 1px dashed var(--color-danger);
  border-radius: 8px;
  background: var(--color-surface-2);
}

.mcp__errors-title {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--color-danger);
}

.mcp__error {
  margin: 0 0 6px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-text-muted);
  word-break: break-all;
}
</style>
