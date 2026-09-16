/**
 * electron-vite 构建配置：分别描述主进程（main）、预加载（preload）、渲染进程（renderer）三份产物。
 * 主进程入口是 electron/src/main/index.ts，预加载入口是 electron/src/preload/index.ts，
 * 渲染进程则复用 frontend/ 这个前端工程。
 */
// electron-vite 配置 API：defineConfig 提供类型提示，
// externalizeDepsPlugin 把 dependencies 里的第三方包标记为外部依赖，不打进主进程 bundle
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
// 官方 Vue 插件：renderer 部分需要它来编译 .vue 单文件组件
import vue from '@vitejs/plugin-vue'
// Node 路径工具：用 resolve(__dirname, ...) 把目录/入口写成基于配置文件的绝对路径
import { resolve } from 'node:path'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()], // 依赖外部化：electron 等原生模块交给运行时 require，不打包
    build: {
      outDir: 'out/main', // 主进程产物输出目录：electron/out/main
      lib: {
        entry: resolve(__dirname, 'src/main/index.ts'), // 主进程唯一入口文件
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()], // 同样外部化依赖，preload 产物保持精简
    build: {
      outDir: 'out/preload', // 预加载产物输出目录：electron/out/preload
      lib: {
        entry: resolve(__dirname, 'src/preload/index.ts'), // preload 唯一入口文件
      },
    },
  },
  // 渲染进程直接复用 frontend/ 这一个前端工程（单一事实来源）。
  // 注意：electron-vite 的 renderer 不会读取 frontend/vite.config.ts，
  // 所以这里要重新声明 vue 插件与入口。
  renderer: {
    root: resolve(__dirname, '../frontend'), // 渲染进程根目录 = 前端工程目录
    base: './', // 打包后用 file:// 相对路径加载页面，必须是相对 base
    plugins: [vue()], // 注册 Vue 插件，用于编译 .vue 文件
    resolve: {
      alias: {
        // 路径别名：'@' 指向 frontend/src，与 frontend/vite.config.ts 保持一致
        '@': resolve(__dirname, '../frontend/src'),
      },
    },
    build: {
      outDir: resolve(__dirname, '../frontend/dist'), // 产物直接落到 frontend/dist，供主进程加载
      emptyOutDir: true, // 构建前清空该目录，避免混入上一次的旧文件
      // electron-vite 默认找 <root>/src/renderer/index.html，这里显式指向前端工程入口
      rollupOptions: {
        input: resolve(__dirname, '../frontend/index.html'), // HTML 入口，Rollup 由它推导依赖图
      },
    },
  },
})
