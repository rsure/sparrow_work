<!--
  components/layout/TopBar.vue —— 顶栏：页面标题 + 当前模型 + 主题切换 + 右栏开关。
  为什么顶栏不再放导航：导航已在左栏；顶栏只保留"与当前页面有关"的全局操作，
  这样中栏顶部的空间才不会被导航挤掉（CC 式布局的分工）。
-->
<script setup lang="ts">
/**
 * TopBar —— 应用顶栏。
 *
 * 三个控件：
 *   1. 当前模型 chip（只读展示，切换模型仍在设置页 —— 避免输入焦点被打断）
 *   2. 主题菜单：明暗切换 + 配色预设（写入 `theme.*` 设置，持久化）
 *   3. 右栏开关：把上下文面板收起，给对话区更多宽度
 */
// Vue：computed 派生标题与主题状态
import { computed, ref } from 'vue'
// Vue Router：RouterLink 渲染设置入口，useRoute 从当前路由的 meta 里取页面标题
import { RouterLink, useRoute } from 'vue-router'
// 设置 store：当前模型（llm.provider / llm.model）
import { useSettingsStore } from '@/stores/settings'
// 主题 store：明暗、预设与切换动作
import { useThemeStore } from '@/stores/theme'

const props = defineProps<{
  /** 右栏是否展开（受控，由 AppShell 持有状态） */
  contextOpen: boolean
}>()

/** 组件事件 */
const emit = defineEmits<{
  /** 切换右栏展开状态 */
  (e: 'toggle-context'): void
}>()

const route = useRoute()
const settings = useSettingsStore()
const theme = useThemeStore()

/** 页面标题：取路由 meta.title，未声明时留空 */
const title = computed<string>(() => (route.meta.title as string | undefined) ?? '')

/** 当前模型摘要：供应商 / 模型名 */
const modelLabel = computed<string>(() => {
  const provider = String(settings.entries['llm.provider']?.value ?? 'deepseek')
  // 兜底值只用于「设置还没加载完」的那一瞬间，跟后端 llm.model 的默认值保持一致
  const model = String(settings.entries['llm.model']?.value ?? 'deepseek-flash')
  return `${provider} / ${model}`
})

/** 主题菜单是否展开 */
const menuOpen = ref(false)

/** 主题菜单里展示的预设（来自 store，后端加了预设也不用改这里） */
const presets = computed(() => theme.presets)

/**
 * 选择预设并关闭菜单。
 *
 * @param id 预设 id
 */
async function pickPreset(id: string): Promise<void> {
  menuOpen.value = false
  await theme.setPreset(id)
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__left">
      <h2 class="topbar__title">{{ title }}</h2>
    </div>

    <div class="topbar__right">
      <!-- 当前模型：只读 chip，点它去设置页改（不在对话中弹下拉，免得抢焦点） -->
      <RouterLink to="/settings" class="chip" :title="`当前模型：${modelLabel}（点击去设置页切换）`">
        {{ modelLabel }}
      </RouterLink>

      <!-- 主题：一个按钮切换明暗，旁边的小箭头展开预设菜单 -->
      <div class="theme">
        <button
          type="button"
          class="icon-btn"
          :title="theme.isDark ? '切换到浅色' : '切换到深色'"
          @click="theme.toggleMode()"
        >
          {{ theme.isDark ? '☾' : '☀' }}
        </button>
        <button type="button" class="icon-btn" title="主题预设" @click="menuOpen = !menuOpen">
          ▾
        </button>

        <div v-if="menuOpen" class="theme__menu">
          <p class="theme__menu-title">配色预设</p>
          <button
            v-for="preset in presets"
            :key="preset.id"
            type="button"
            class="theme__item"
            :class="{ 'theme__item--active': preset.id === theme.presetId }"
            :title="preset.description"
            @click="pickPreset(preset.id)"
          >
            {{ preset.label }}
          </button>
          <p class="theme__menu-hint">
            更多外观选项（主色 / 圆角 / 字号 / 代码主题）在设置页「外观」分区。
          </p>
        </div>
      </div>

      <button
        type="button"
        class="icon-btn"
        :title="props.contextOpen ? '收起右侧面板' : '展开右侧面板'"
        @click="emit('toggle-context')"
      >
        {{ props.contextOpen ? '⟩' : '⟨' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 46px;
  flex: 0 0 46px;
  padding: 0 20px 0 24px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.topbar__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.topbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chip {
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  text-decoration: none;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.icon-btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 7px;
  width: 26px;
  height: 26px;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.icon-btn:hover {
  color: var(--color-text);
  border-color: var(--color-primary);
}

.theme {
  position: relative;
  display: flex;
  gap: 4px;
}

.theme__menu {
  position: absolute;
  top: 32px;
  right: 0;
  z-index: 20;
  width: 200px;
  padding: 8px;
  border-radius: 10px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: 0 12px 30px rgba(2, 6, 23, 0.35);
}

.theme__menu-title {
  margin: 0 0 4px;
  font-size: 11px;
  color: var(--color-text-muted);
  padding: 0 4px;
}

.theme__item {
  display: block;
  width: 100%;
  text-align: left;
  appearance: none;
  border: none;
  background: transparent;
  color: var(--color-text);
  border-radius: 7px;
  padding: 5px 8px;
  font-size: 12px;
  cursor: pointer;
}

.theme__item:hover {
  background: var(--color-surface-2);
}

.theme__item--active {
  background: var(--color-primary-weak);
  color: var(--color-primary);
  font-weight: 600;
}

.theme__menu-hint {
  margin: 6px 4px 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--color-text-muted);
}
</style>
