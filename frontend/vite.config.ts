/**
 * Vite 构建 / 开发服务器配置（frontend 独立构建用，例如浏览器里单页调试或 pnpm run build:web）。
 * 注意：Electron 打包时的渲染进程由 electron/electron.vite.config.ts 单独配置，不读本文件。
 */
// Node URL 工具：fileURLToPath 把模块 URL 转成路径，URL 用于拼出 src 目录的绝对路径
import { fileURLToPath, URL } from 'node:url'
// Vite 配置 API：defineConfig 提供类型提示，loadEnv 读取 .env 文件里的变量
import { defineConfig, loadEnv } from 'vite'
// 官方 Vue 插件：让 Vite 能编译 .vue 单文件组件
import vue from '@vitejs/plugin-vue'

// 前端开发端口默认 5173，若被占用则 Vite 自动换下一个可用端口
// （Electron 主进程通过 electron-vite 注入的 ELECTRON_RENDERER_URL 自动跟随实际端口，
//  后端 CORS 对 localhost/127.0.0.1 任意端口放行，见 backend/app/config.py 的 cors_origin_regex）
/**
 * 以函数形式导出配置，便于按命令模式（mode）动态读取环境变量。
 * @param context.mode 当前模式字符串：'development' | 'production' 等，决定 sourcemap 等开关
 * @returns Vite 的完整配置对象
 */
export default defineConfig(({ mode }) => {
  // 第三个参数传 '' 表示不过滤前缀，这样连 VITE_ 之外的变量也能读到
  const env = loadEnv(mode, process.cwd(), '')
  // 代理转发目标：优先读 .env 里的 VITE_BACKEND_PROXY，否则用本地后端默认地址
  const target = env.VITE_BACKEND_PROXY || 'http://127.0.0.1:8000'

  return {
    // Electron 生产环境以 file:// 相对路径加载页面，必须用相对 base
    base: './',
    plugins: [vue()], // 注册 Vue 插件，用于编译 .vue 文件
    resolve: {
      alias: {
        // 路径别名：'@' 指向 frontend/src，让 import 不用写一长串 ../../
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1', // 只监听本机回环地址，不对外暴露开发服务器
      port: 5173, // 期望端口；下面 strictPort 为 false，占用时会自动改用下一个
      strictPort: false, // 端口被占用时不报错，自动尝试下一个可用端口
      // 浏览器单页调试时，/api 直接代理到 Python 后端，避免跨域
      proxy: {
        '/api': {
          target, // 代理目标地址，即后端 8000 端口
          changeOrigin: true, // 转发时把 Host 头改成目标地址，避免后端按 Host 做校验时报错
        },
      },
    },
    build: {
      outDir: 'dist', // 构建产物目录：frontend/dist，Electron 主进程从这里加载
      emptyOutDir: true, // 构建前清空 outDir，防止旧文件残留
      sourcemap: mode !== 'production', // 非生产模式生成 sourcemap 便于调试；正式打包不产出
    },
  }
})
