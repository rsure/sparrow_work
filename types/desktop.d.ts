/**
 * 桌面能力类型声明（preload 注入）——**文档参考用，不参与类型检查**。
 *
 * 说明（新手视角，重要）：
 *   - 真正生效的声明在 frontend/env.d.ts，那里有 `interface DesktopApi` 与
 *     `declare global { interface Window { desktop?: DesktopApi } }`；
 *     frontend/tsconfig.json 的 include 只包含 env.d.ts 与 src/**，**不包含本文件**。
 *   - 本文件因此是一份「给人看的对照表」：字段必须与
 *     electron/src/preload/index.ts 里的 desktopApi 一字不差。
 *   - 类型刻意与 env.d.ts 保持完全一致（例如 platform 写成 string 而不是
 *     NodeJS.Platform）。因为两个全局同名声明的 interface 会被 TS 合并，
 *     一旦字段类型不同就会报 TS2717「Subsequent property declarations must
 *     have the same type」——所以不要单方面在这里改类型。
 */

/** 由 preload 通过 contextBridge 注入到渲染进程的桌面能力集合 */
interface DesktopApi {
  /** 是否运行在 Electron 桌面环境：false 表示纯浏览器调试，桌面能力不可用 */
  isDesktop: boolean
  /** 操作系统平台标识，取值来自 Node 的 process.platform，如 'win32' / 'darwin' / 'linux' */
  platform: string
  /** 后端实际监听的端口号（主进程可用 APP_PORT 覆盖），前端拼接口地址时要用它 */
  apiPort: number
  /** 运行版本号集合，用于「关于」页面展示与问题排查 */
  versions: {
    /** Electron 运行时版本，如 '33.4.11' */
    electron: string
    /** 内置 Chromium 版本 */
    chrome: string
    /** 内置 Node.js 版本 */
    node: string
  }
  /** 弹出系统原生文件夹选择框，返回选中的绝对路径；用户取消时返回 null */
  selectFolder: () => Promise<string | null>
  /** 在系统文件管理器中定位并高亮某个文件（如「打开所在文件夹」） */
  showItemInFolder: (path: string) => Promise<void>
  /** 用系统默认程序打开文件或文件夹；返回空串表示成功，非空串是系统返回的错误描述 */
  openPath: (path: string) => Promise<string>
}

/** 扩展全局 Window：浏览器环境下 window.desktop 为 undefined */
interface Window {
  /** 由 electron/src/preload/index.ts 注入；浏览器环境下为 undefined */
  desktop?: DesktopApi
}
