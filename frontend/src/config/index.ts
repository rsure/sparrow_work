/** 前端全局常量：与后端 backend/app/config.py 保持一致 */

/** 本地后端端口（Java 默认，Python 同端口；Electron 生产环境据此直连，浏览器开发态由 vite 代理转发） */
export const API_PORT = 8000

/** 应用显示名称：渲染在 App.vue 顶栏品牌位上；改了它前后端无需同步 */
export const APP_TITLE = 'Vue3 + Electron + FastAPI'
