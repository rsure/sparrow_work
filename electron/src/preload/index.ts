/**
 * Electron preload 脚本（electron-vite 中 preload 的构建入口）。
 *
 * 运行在渲染进程加载之前，是页面与主进程之间唯一的受控通道：
 * 只把下面 desktopApi 里的字段挂到 window.desktop，页面拿不到任何原始 Node / Electron 能力。
 * 前端类型声明见 frontend/env.d.ts 的 DesktopApi。
 */
// Electron preload API：contextBridge 负责把白名单对象安全地挂到 window，
// ipcRenderer 负责 invoke 主进程用 ipcMain.handle 注册的通道
import { contextBridge, ipcRenderer } from 'electron'
// 事件参数类型：订阅「更新状态变化」时，回调收到的第一个参数就是它（用不到，但必须声明）
import type { IpcRendererEvent } from 'electron'

// 共享常量：后端端口，前端据此拼请求地址，避免在多处硬编码 8000
import { BACKEND_PORT } from '../shared/config'
// 共享类型：更新状态快照的形状，页面消费时必须与主进程一致
import type { UpdateState } from '../shared/update'

/**
 * 通过 contextBridge 暴露给渲染进程的最小桌面能力。
 * 前端只能看到这个白名单对象，拿不到 Node / Electron 的原始能力。
 */
const desktopApi = {
  /** 是否运行在 Electron 桌面壳里：浏览器直接打开页面时为 undefined，前端用它做能力降级判断 */
  isDesktop: true,
  /** 当前操作系统平台标识（darwin / win32 / linux），用于平台差异化展示逻辑 */
  platform: process.platform,
  /** Python 后端监听端口（默认 8000），前端拼 API 地址时使用 */
  apiPort: BACKEND_PORT,
  /** 运行时版本号集合，用于「关于」页面展示与排查问题 */
  versions: {
    /** Electron 版本号 */
    electron: process.versions.electron,
    /** 内置 Chromium 版本号 */
    chrome: process.versions.chrome,
    /** Electron 内置的 Node.js 版本号 */
    node: process.versions.node,
  },
  /** 弹出系统原生文件夹选择框，返回选中路径；用户取消时为 null */
  selectFolder: (): Promise<string | null> => ipcRenderer.invoke('dialog:selectFolder'),
  /**
   * 在系统文件管理器中定位文件（打开所在文件夹并选中它）。
   * @param path 目标文件的绝对路径
   */
  showItemInFolder: (path: string): Promise<void> => ipcRenderer.invoke('shell:showItemInFolder', path),
  /**
   * 用系统默认方式打开路径（文件夹 → 文件管理器，文件 → 系统默认程序）。
   * @param path 目标路径（文件或文件夹）
   * @returns 空串表示成功；非空串是系统返回的错误描述
   */
  openPath: (path: string): Promise<string> => ipcRenderer.invoke('shell:openPath', path),
  /** 应用版本号（取自主进程的 app.getVersion()），「关于」页展示"当前版本 vX.Y.Z" */
  getAppVersion: (): Promise<string> => ipcRenderer.invoke('app:version'),
  /**
   * 自动更新能力（OPS-4）。只有在打包后的安装版里才真正可用；
   * 开发态调用 check() 会立刻得到 status='disabled' 的状态，不会报错。
   */
  updates: {
    /** 读取当前更新状态（进入「关于」页时先查一次，避免错过启动时的自动检查结果） */
    getState: (): Promise<UpdateState> => ipcRenderer.invoke('update:state'),
    /** 手动检查更新，返回检查结束后的状态（失败也走返回值，不抛异常） */
    check: (): Promise<UpdateState> => ipcRenderer.invoke('update:check'),
    /** 安装已下载完成的新版本：会退出应用并启动安装程序；未下载完成时主进程直接忽略 */
    install: (): Promise<void> => ipcRenderer.invoke('update:install'),
    /**
     * 订阅更新状态变化（主进程每次 setState 都会广播）。
     * @param handler 收到新状态时调用
     * @returns 取消订阅的函数；页面卸载时必须调用，否则重复进入页面会叠加监听
     */
    onState: (handler: (state: UpdateState) => void): (() => void) => {
      const listener = (_event: IpcRendererEvent, state: UpdateState): void => handler(state)
      ipcRenderer.on('update:state-changed', listener)
      return () => {
        ipcRenderer.removeListener('update:state-changed', listener)
      }
    },
  },
}

// 等 preload 执行完，渲染进程就能通过 window.desktop 访问上述能力（仅此一项，别无其他）
contextBridge.exposeInMainWorld('desktop', desktopApi)

/** desktopApi 的类型别名：前端可据此获得 window.desktop 的完整补全与类型检查 */
export type DesktopApi = typeof desktopApi
