<script setup lang="ts">
/** 404 页：路由兜底（见 router/index.ts 的 /:pathMatch(.*)*），给用户一个回首页的出口。 */
import { RouterLink } from 'vue-router' // 路由跳转组件：这里渲染成「返回首页」的按钮式链接
</script>

<template>
  <section class="not-found card">
    <h1>404</h1>
    <p class="muted">页面不存在。</p>
    <RouterLink class="btn" to="/">返回首页</RouterLink>
  </section>
</template>

<style scoped>
.not-found {
  text-align: center;
}

.not-found .btn {
  display: inline-block;
  margin-top: 12px;
  text-decoration: none;
}
</style>
