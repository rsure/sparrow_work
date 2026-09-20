/**
 * Vitest 配置 —— 前端单元测试 / 组件测试的入口。
 *
 * 为什么不写进 vite.config.ts：
 *   vite.config.ts 管的是「开发服务器 + 打包」；测试还要多出 jsdom 环境、setup 文件、
 *   测试文件范围、覆盖率报告这些东西。混在一份文件里，读的人分不清哪条配置是给谁用的。
 *
 * 必须与 vite.config.ts 保持一致的两处（否则「测试通过」并不代表「线上跑得通」）：
 *   1. plugins 里的 vue()：测试里的 .vue 走同一套编译；
 *   2. resolve.alias 的 `@`：源码里到处是 `@/xxx`，别名不一致会直接解析失败。
 */
// Node 内置的 path/url 工具：把本文件所在目录转成绝对路径，供下面 @ 别名使用
import { fileURLToPath, URL } from 'node:url'
// Vitest 的配置工厂：比 vite 的 defineConfig 多认识下面的 test 字段（有类型提示）
import { defineConfig } from 'vitest/config'
// Vue 单文件组件编译插件：与 vite.config.ts 用的是同一个版本、同一份配置
import vue from '@vitejs/plugin-vue'

/** 前端测试配置：上面三项与 vite 对齐，下面的 test 段落定义「怎么跑测试」 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // 与 vite.config.ts 完全一致的别名：@ → frontend/src
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    // 运行环境：jsdom（在 Node 里模拟一套浏览器 DOM）
    // 组件要 mount、DOMPurify 要真实 DOM 才能完成净化，这两件事都离不开它
    environment: 'jsdom',
    // 只有 tests 目录下的 *.spec.ts 算测试文件，避免误把 src 里的同名文件当测试跑
    include: ['tests/**/*.spec.ts'],
    // 每个测试文件运行前先执行的准备文件：补齐 jsdom 缺失的浏览器 API（见 tests/setup.ts）
    setupFiles: ['./tests/setup.ts'],
    // 不注入全局 describe/it/expect：每条 API 都显式 import，读测试的人一眼看出它从哪来
    globals: false,
    // 每个用例开始前清空 mock 的调用记录，避免上一个用例的调用次数被算进来
    clearMocks: true,
    // 每个用例结束后还原被 spy/mock 改过的原始实现，避免用例之间互相污染
    restoreMocks: true,
    coverage: {
      // 覆盖率采集器：v8 是 Node 自带的，不用改写源码插桩，速度最快
      provider: 'v8',
      // 只统计业务源码，不统计测试文件自身
      include: ['src/**/*.{ts,vue}'],
      // 排除项：main.ts 只是装配入口；big-mock.ts 是静态演示数据，都不是逻辑
      exclude: ['src/main.ts', 'src/data/big-mock.ts'],
      // 报告格式：text 在终端看总览，html 可以点进具体文件看哪一行没覆盖
      reporter: ['text', 'html'],
      // HTML 报告目录：frontend/coverage（已在根 .gitignore 里忽略）
      reportsDirectory: './coverage',
    },
  },
})
