/**
 * 路由表：集中登记「哪个 URL 对应哪个页面组件」（M2：三栏布局后的入口调整）。
 *
 * 关键变化：
 *   - `/` 从「介绍页」改成**对话页**（CC 式布局的默认落地页）；
 *   - `/settings` 依旧是设置页，入口从顶栏移到了左栏导航；
 *   - `/scannHistory` 保留为重定向（旧书签/旧链接不会 404），对话统一走 `/`；
 *   - 原来的首页（健康检查介绍）降级为 `/diagnostics`，不再占默认位置。
 */
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router' // 路由核心：createRouter 建实例、createWebHashHistory 用 hash 模式、RouteRecordRaw 约束路由数组类型

import ChatView from '@/views/chat/ChatView.vue' // 默认落地页：对话（首屏就要用，静态引入）

// 使用 hash 模式：Electron 打包后页面以 file:// 加载，history 模式会 404
const routes: RouteRecordRaw[] = [
  // 对话：三栏布局的中栏内容
  {
    path: '/',
    name: 'chat',
    component: ChatView,
    meta: { title: '对话' },
  },
  // 旧入口：改造前 AI 对话挂在 /scannHistory，保留重定向避免旧链接失效
  {
    path: '/scannHistory',
    redirect: '/',
  },
  // 关于页：分层架构说明，懒加载（不首屏用，拆成独立 chunk）
  {
    path: '/about',
    name: 'about',
    component: () => import('@/views/AboutView.vue'),
    meta: { title: '关于' },
  },
  // 诊断页：健康检查 + 运行环境（原首页内容，降级到这里）
  {
    path: '/diagnostics',
    name: 'diagnostics',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '诊断' },
  },
  // 设置页：后端「声明式注册表」驱动的全量设置面板；按 meta.category 自动分区渲染
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '设置' },
  },
  // 执行轨迹回放（ARCH-7）：只读页面，按「会话 → 轮次 → 事件」三级钻取，懒加载
  {
    path: '/trace',
    name: 'trace',
    component: () => import('@/views/TraceView.vue'),
    meta: { title: '执行轨迹' },
  },
  // 扫描模块的父级路由：只提供容器与 <RouterView>，本身不渲染内容
  {
    path: '/scanner',
    name: 'scanner',
    component: () => import('@/views/ScannIndex.vue'),
    meta: { title: '扫描' },
    redirect: '/scannLogs', // 直接进 /scanner 时默认落到扫描日志
    children: [
      // 扫描日志：选文件夹 + 发起扫描 + 任务列表（模块默认页）
      {
        path: '/scannLogs',
        name: 'scannLogs',
        component: () => import('@/views/scannLogs.vue'),
        meta: { title: '扫描日志' },
      },
      // 扫描结果：某次任务的实时文件列表，靠 query 的 task_id/path 定位数据
      {
        path: '/scannResult',
        name: 'scannResult',
        component: () => import('@/views/scannResult.vue'),
        meta: { title: '扫描结果' },
      },
      // 操作记录：展示工具调用审计（谁在什么时候做了什么、结果如何）
      {
        path: '/audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { title: '操作记录' },
      },
    ],
  },
  // 兜底路由：任何没匹配上的地址都显示 404 页
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '404' },
  },
]

// 全局唯一的路由实例，由 main.ts 通过 app.use(router) 挂载
const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/** 每次跳转完成后，用目标路由 meta.title 同步浏览器/窗口标题，方便一眼看出当前在哪一页 */
router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? ''
  document.title = title ? `${title} | Vue3-Electron-FastAPI` : 'Vue3-Electron-FastAPI'
})

export default router
