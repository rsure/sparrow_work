// 引入 Vite 自带的客户端类型：让 import.meta.env、import.meta.hot 以及 *.vue 等资源导入有类型提示
/// <reference types="vite/client" />

// 注意（新手易踩的坑）：本文件末尾有 `export {}`，因此它是一个「模块」而不是全局脚本。
// 模块里直接写的 interface 只属于本文件，不会变成全局声明。
// 所以要扩展 Vite 的 import.meta.env，必须写进 declare global 里。
declare global {
  /** Vite 环境变量的类型声明：对应 frontend/.env* 里以 VITE_ 开头的变量 */
  interface ImportMetaEnv {
    /** 后端地址；留空则使用相对路径 /api（dev 走 vite 代理） */
    readonly VITE_API_BASE_URL?: string
    /** vite 代理目标，仅开发用 */
    readonly VITE_BACKEND_PROXY?: string
  }

  /** 扩展 import.meta，使 import.meta.env 具备上面声明的字段类型 */
  interface ImportMeta {
    readonly env: ImportMetaEnv
  }
}

declare global {
  /**
   * 自动更新所处的阶段（与 electron/src/shared/update.ts 的 UpdateStatus 一致）。
   * 「关于」页按它决定显示"检查中 / 有新版本 / 已是最新 / 失败"等文案。
   */
  type DesktopUpdateStatus =
    /** 还没检查过 */
    | 'idle'
    /** 当前环境不支持（开发态 / 未打包 / 设置里关了自动检查） */
    | 'disabled'
    /** 正在检查 */
    | 'checking'
    /** 有新版本，等待用户决定是否下载 */
    | 'available'
    /** 正在下载 */
    | 'downloading'
    /** 已下载完成，重启即可安装 */
    | 'downloaded'
    /** 已是最新版本 */
    | 'not-available'
    /** 检查或下载失败 */
    | 'error'

  /** 一次更新动作的状态快照（主进程经 IPC 传来，字段都可结构化克隆） */
  interface DesktopUpdateState {
    /** 当前阶段 */
    status: DesktopUpdateStatus
    /** 新版本号；没有新版本或还没检查时为 null */
    version: string | null
    /** 下载进度百分比（0~100，仅 downloading 阶段有意义） */
    percent: number
    /** 面向用户的一句说明（失败原因 / 已是最新 / 开发态提示），可为空串 */
    message: string
    /** 最近一次检查完成时间（ISO 8601），从未检查过时为 null */
    checked_at: string | null
  }

  /**
   * Electron preload 注入的桌面能力（electron/src/preload/index.ts）。
   *
   * 必须写在 `declare global` 里：本文件是模块（末尾有 `export {}`），
   * 模块顶层的 interface 只属于本文件——写在外面的后果是 `window.desktop` 能用、
   * 但别处想单独标注这个类型（如测试里造一个替身）会报 "Cannot find name"。
   */
  interface DesktopApi {
    /** 是否运行在 Electron 桌面壳内：浏览器直接打开页面时 window.desktop 整体不存在 */
    isDesktop: boolean
    /** 操作系统平台标识（darwin / win32 / linux），用于平台差异化展示 */
    platform: string
    /** Python 后端监听端口（默认 8000），前端据此拼 API 地址 */
    apiPort: number
    /** 运行时版本号集合，用于「关于」页面展示与问题排查 */
    versions: {
      /** Electron 版本号 */
      electron: string
      /** 内置 Chromium 版本号 */
      chrome: string
      /** Electron 内置的 Node.js 版本号 */
      node: string
    }
    /** 弹出系统原生文件夹选择框；返回选中路径，用户取消时为 null */
    selectFolder: () => Promise<string | null>
    /** 在系统文件管理器中定位文件（打开所在文件夹并选中） */
    showItemInFolder: (path: string) => Promise<void>
    /** 用系统默认方式打开路径（文件夹 → 文件管理器）；返回空串表示成功 */
    openPath: (path: string) => Promise<string>
    /** 应用版本号（主进程 app.getVersion()）；「关于」页显示"当前版本 vX.Y.Z" */
    getAppVersion: () => Promise<string>
    /** 自动更新能力（OPS-4）：只在打包后的安装版里真正可用，开发态返回 disabled 状态 */
    updates: {
      /** 读取当前更新状态（进页面先查一次，补上启动时自动检查的结果） */
      getState: () => Promise<DesktopUpdateState>
      /** 手动检查更新；失败也通过返回值报告，不抛异常 */
      check: () => Promise<DesktopUpdateState>
      /** 安装已下载完成的新版本（会退出应用）；未下载完成时主进程忽略该调用 */
      install: () => Promise<void>
      /** 订阅状态变化，返回取消订阅的函数（页面卸载时必须调用） */
      onState: (handler: (state: DesktopUpdateState) => void) => () => void
    }
  }

  interface Window {
    /** 浏览器环境下为 undefined */
    desktop?: DesktopApi
  }
}

// 声明 .vue 文件的模块类型：让 TS 认识 `import App from './App.vue'` 这类导入，
// 把它当成一个 Vue 组件而非「找不到模块」
declare module '*.vue' {
  // 只借用 Vue 的 DefineComponent 类型来描述组件，不引入运行时代码
  import type { DefineComponent } from 'vue'
  /** 单个 .vue 文件默认导出的组件类型：props/slots 均为宽松的 Record */
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

// 让本文件成为模块：只有模块里的 `declare global` 才会合并到全局 Window
export {}
