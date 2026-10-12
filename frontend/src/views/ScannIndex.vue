<script setup lang="ts">
/**
 * 扫描模块的父级布局：只负责顶部导航 + 承载子路由的 <RouterView>。
 * 具体页面（扫描日志 / 扫描结果 / 导入历史）由 children 路由提供。
 */
import {computed, ref, watch} from "vue"; // 响应式工具：computed 派生路由参数，ref 记住最近任务，watch 跟随路由变化
import {RouterLink, RouterView, useRoute} from "vue-router"; // 路由能力：RouterLink 渲染导航、RouterView 渲染子页面、useRoute 读取当前 query

// 当前激活的路由对象：用来读取 query 里的 task_id / path
const route = useRoute();

// 当前路由上的任务信息（处于扫描结果页时非空）
const taskId = computed(() => (route.query.task_id as string | undefined) ?? '');
const path = computed(() => (route.query.path as string | undefined) ?? '');

// 记住最近一次打开过的任务：只要结果页加载过一次，就允许从顶部「扫描结果」入口再点开
const lastTaskId = ref('');
/** 最近一次打开任务的来源文件夹路径，与 lastTaskId 成对保存，回跳结果页时一起带上 */
const lastPath = ref('');
/** 监听路由上的 task_id：一旦有新任务被打开就缓存下来，immediate 保证首屏（挂载时已有 query）也生效 */
watch(taskId, (id) => {
  if (id) {
    lastTaskId.value = id;
    lastPath.value = path.value;
  }
}, { immediate: true });

// taskId 为空（从未打开过任务）时不提供跳转，顶部入口保持不可点
const resultLink = computed(() =>
    lastTaskId.value
        ? { name: 'scannResult', query: { task_id: lastTaskId.value, path: lastPath.value } }
        : null,
);
</script>

<template>
  <title>扫描文件</title>
  <nav class="nav">
    <RouterLink class="nav__link" to="/scannLogs">扫描日志</RouterLink>

    <!-- 扫描结果只有在打开过任务（task_id 非空）后才可作为导航入口点开 -->
    <RouterLink v-if="resultLink" class="nav__link" :to="resultLink">
      扫描结果
    </RouterLink>
    <span
        v-else
        class="nav__link nav__link--static"
        title="请先在扫描日志中打开一个任务"
    >
      扫描结果
    </span>
    <!-- AI 对话已迁到三栏布局的默认首页（/），这里保留一个快捷入口 -->
    <RouterLink class="nav__link" to="/">AI 对话</RouterLink>
    <RouterLink class="nav__link" to="/audit">操作记录</RouterLink>
  </nav>
  <main class="app-main">
    <RouterView v-slot="{ Component }">
      <KeepAlive>
        <component :is="Component" />
      </KeepAlive>
    </RouterView>
  </main>

</template>

<style scoped>
.nav {
  display: flex;
  gap: 8px;
}

.nav__link {
  color: var(--color-text-muted);
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 8px;
  transition: all 0.15s ease;
}

.nav__link:hover {
  color: var(--color-text);
  background: var(--color-surface-2);
}

.nav__link.router-link-active {
  color: var(--color-primary);
  background: var(--color-primary-weak);
}

.nav__link--static {
  cursor: default;
}
</style>
