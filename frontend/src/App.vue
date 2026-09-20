<script setup lang="ts">
/**
 * 根组件 App.vue —— 只做一件事：把三栏外壳挂出来。
 *
 * 改造前这里承载「顶部导航 + 运行载体提示 + 后端地址提示 + 路由出口」，
 * 页面被限制在 1080px 居中容器里；现在布局交给 `components/layout/AppShell.vue`，
 * 本文件保持极薄，便于以后换外壳（全屏预览、无边框窗口）而不动其它代码。
 */
// 三栏外壳：左栏导航 + 顶栏 + 中栏路由出口 + 右栏上下文
import AppShell from '@/components/layout/AppShell.vue'
</script>

<template>
  <AppShell />
</template>
