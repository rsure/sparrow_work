<script setup lang="ts">
/**
 * 关于页：静态分层说明 + 桌面版本信息 + 自动更新入口（OPS-4）。
 *
 * 本页原来只讲"这个外壳分几层"，现在补两块与运行环境有关的信息：
 *   1. 当前应用版本号（主进程 app.getVersion()，只有桌面壳里读得到）；
 *   2. 自动更新状态与「检查更新 / 立即重启安装」按钮。
 * 浏览器调试时 window.desktop 不存在，这两块自动降级成一段说明文字，不报错。
 */
// Vue 响应式：ref 存版本号与更新状态，computed 派生文案与按钮可用性，
// onMounted 里建立订阅，onBeforeUnmount 里取消（否则来回切页面会叠加监听）
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
// Vant 轻提示：手动检查更新的结果（已是最新 / 失败原因）需要即时反馈
import { showToast } from 'vant'

/** 分层说明数据：name=层名，detail=该层用的技术栈与职责；渲染成下方的卡片列表 */
const layers = [
  { name: '渲染层', detail: 'Vue3 + TypeScript + Vue Router（hash 模式，适配 file://）' },
  { name: '桌面壳', detail: 'Electron 主进程 / 预加载脚本，负责起停本地后端（默认 Java，可切 Python）' },
  { name: '接口层（默认）', detail: 'Spring Boot：Controller → Service → Agent/LLM（LangChain4j + LangGraph4j）' },
  { name: '接口层（保留）', detail: 'FastAPI：app/api → app/controllers → app/services → app/schemas' },
  { name: '依赖管理', detail: 'Maven Wrapper / uv（后端）+ pnpm workspace（JS/TS）' },
]

/** 桌面壳能力；浏览器打开页面时为 undefined，版本与更新两块据此降级 */
const desktop = window.desktop

/** 应用版本号；读取失败或不在桌面壳里时为 null */
const appVersion = ref<string | null>(null)

/** 自动更新状态；null 表示还没拿到（页面刚打开、或不在桌面壳里） */
const updateState = ref<DesktopUpdateState | null>(null)

/** 是否正在手动检查更新（让按钮显示 loading，并防止连点） */
const checking = ref(false)

/** 取消订阅更新状态的回调，页面卸载时调用；null 表示还没订阅 */
let offUpdateState: (() => void) | null = null

/** 把更新状态翻译成一句人话，直接显示在「自动更新」那一行 */
const statusText = computed<string>(() => {
  const state = updateState.value
  if (!state) return '尚未检查'
  switch (state.status) {
    case 'idle':
      return '尚未检查'
    case 'disabled':
      return state.message || '当前环境不支持自动更新'
    case 'checking':
      return '正在检查更新…'
    case 'available':
      return state.version ? `发现新版本 ${state.version}，正在等待确认下载` : '发现新版本'
    case 'downloading':
      return `正在下载 ${state.percent}%（可在后台继续使用）`
    case 'downloaded':
      return state.version ? `新版本 ${state.version} 已下载完成，重启即可安装` : '新版本已下载完成'
    case 'not-available':
      return '已是最新版本'
    case 'error':
      return state.message || '检查更新失败'
    default:
      // 理论上不会走到这里；留个兜底，避免状态新增后页面显示空白
      return state.message
  }
})

/** 是否允许点「立即重启安装」：只有下载完成这一种状态可以装 */
const canInstall = computed(() => updateState.value?.status === 'downloaded')

/** 检查/下载进行中：此时禁用按钮，避免重复发起请求 */
const busy = computed(
  () => checking.value || updateState.value?.status === 'checking' || updateState.value?.status === 'downloading',
)

/** 页面挂载：订阅更新状态，并补读一次版本号与当前状态（补上启动时自动检查的结果） */
onMounted(async () => {
  if (!desktop) return
  offUpdateState = desktop.updates.onState((state) => {
    updateState.value = state
  })
  try {
    appVersion.value = await desktop.getAppVersion()
  } catch {
    // 老版本 preload 没有这个通道时保持 null，页面显示"未知"
    appVersion.value = null
  }
  try {
    updateState.value = await desktop.updates.getState()
  } catch {
    // 读不到状态不影响页面其余部分，保持"尚未检查"
    updateState.value = null
  }
})

/** 页面卸载：取消订阅，避免重复进入页面时监听器越叠越多 */
onBeforeUnmount(() => {
  offUpdateState?.()
  offUpdateState = null
})

/** 手动检查更新：结果直接反映在状态行里，失败再补一个 toast */
async function checkUpdate(): Promise<void> {
  if (!desktop || checking.value) return
  checking.value = true
  try {
    const state = await desktop.updates.check()
    updateState.value = state
    if (state.status === 'error') showToast(state.message || '检查更新失败')
    else if (state.status === 'not-available') showToast('已是最新版本')
    else if (state.status === 'disabled') showToast(state.message || '当前环境不支持自动更新')
  } catch (error) {
    showToast(`检查更新失败：${String(error)}`)
  } finally {
    checking.value = false
  }
}

/** 安装已下载的新版本：主进程会退出应用并启动安装程序 */
async function installUpdate(): Promise<void> {
  if (!desktop) return
  await desktop.updates.install()
}
</script>

<template>
  <section class="about">
    <h1>关于这个外壳</h1>
    <p class="muted">一份代码多端运行：浏览器单页调试、Electron 桌面应用（Windows / macOS / Linux）。</p>

    <section class="card about__update">
      <div class="about__row">
        <strong>当前版本</strong>
        <span class="muted">{{ appVersion ? `v${appVersion}` : desktop ? '读取中…' : '浏览器模式（无桌面版本号）' }}</span>
      </div>
      <div v-if="desktop" class="about__row">
        <strong>自动更新</strong>
        <span class="muted">{{ statusText }}</span>
      </div>
      <div v-if="desktop" class="about__actions">
        <van-button size="small" type="primary" :loading="checking" :disabled="busy" @click="checkUpdate">
          检查更新
        </van-button>
        <van-button v-if="canInstall" size="small" type="success" @click="installUpdate">立即重启安装</van-button>
      </div>
      <p class="muted about__hint">
        {{
          desktop
            ? '更新源由 electron-builder.yml 的 publish 决定；开发态不检查更新，设置页可以关掉启动时的自动检查。'
            : '自动更新只在打包后的桌面应用里可用；浏览器调试时没有这个能力。'
        }}
      </p>
    </section>

    <ul class="about__list">
      <li v-for="layer in layers" :key="layer.name" class="card about__item">
        <strong>{{ layer.name }}</strong>
        <span class="muted">{{ layer.detail }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.about__list {
  list-style: none;
  padding: 0;
  margin: 20px 0 0;
  display: grid;
  gap: 12px;
}

.about__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 20px;
}

.about__update {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  margin-top: 20px;
}

/* 一行标签 + 值：标签定宽，值占满剩余宽度并允许换行 */
.about__row {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.about__row strong {
  flex: 0 0 84px;
  font-weight: 600;
}

/* 按钮排一行，空间不够时自动换行 */
.about__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.about__hint {
  margin: 0;
  font-size: var(--font-size-sm, 12px);
  line-height: 1.6;
}
</style>
