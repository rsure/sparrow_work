/**
 * Electron 主进程入口（electron-vite 中 main 的构建入口，见 electron/electron.vite.config.ts）。
 *
 * 启动顺序：抢单实例锁 → 启动或复用本地后端（默认 Java，可切 Python）→ 创建 BrowserWindow
 * → 注册 IPC 通道；退出时通过 will-quit 关掉「自己拉起的」后端进程。
 */
// Node 文件系统：用 existsSync 探测前端入口 index.html 是否存在（只判断存在性，不读内容）
import { existsSync } from 'node:fs'
// Node 路径工具：把 __dirname、process.resourcesPath 等片段拼成跨平台的绝对路径
import { join } from 'node:path'
// Electron 主进程 API：app 管应用生命周期，BrowserWindow 创建窗口，dialog 弹原生对话框，
// ipcMain 注册渲染进程可调用的通道，shell 调用系统文件管理器 / 系统默认程序
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'

// 同目录的后端生命周期管理：startBackend 负责拉起或复用 Java/Python 后端，stopBackend 负责退出时收尾
import { startBackend, stopBackend } from './backend'
// 同目录的自动更新（OPS-4）：initUpdater 注册更新事件与 IPC，maybeAutoCheck 按设置决定启动时是否检查
import { initUpdater, maybeAutoCheck } from './updater'
// 共享常量：开发态 vite dev server 的兜底地址（只有在 ELECTRON_RENDERER_URL 缺失时才会用到）
import { DEV_SERVER_URL } from '../shared/config'


app.commandLine.appendSwitch('no-sandbox')


// 关闭 GPU 硬件加速：在远程桌面 / 虚拟显示器（如向日葵 OrayIddDriver、RDP、无独显的虚拟机）环境下，
// Chromium 的 GPU 进程初始化 D3D/ANGLE 时会崩溃并以 STATUS_BREAKPOINT(0x80000003) 退出，
// 导致 Electron 一启动就闪退。必须在 ready 事件之前调用，否则不生效。
app.disableHardwareAcceleration()

/** 未打包运行（`pnpm run dev`）时加载 vite dev server，打包后加载前端构建产物 */
const isDev = !app.isPackaged || process.env.ELECTRON_RENDERER_URL !== undefined

/** 当前主窗口引用；窗口 closed 后置为 null，IPC 回调靠它判断窗口是否还存在 */
let mainWindow: BrowserWindow | null = null

/**
 * 找到前端入口文件：开发态取 frontend/dist，打包后取 resources/renderer。
 * @returns index.html 的绝对路径
 * @throws 所有候选路径都不存在时抛错，提示需要先执行 pnpm run build:web
 */
function resolveRendererEntry(): string {
  // 候选路径按优先级排列：打包态优先看 extraResources 拷进去的 renderer，再看仓库内的构建产物
  const candidates = app.isPackaged
    ? [
        join(process.resourcesPath, 'renderer', 'index.html'),
        join(app.getAppPath(), '../frontend/dist/index.html'),
      ]
    : [
        join(__dirname, '../../../frontend/dist/index.html'),
        join(app.getAppPath(), '../frontend/dist/index.html'),
      ]

  // 取第一个真实存在的候选路径作为最终入口
  const found = candidates.find((item) => existsSync(item))
  if (!found) {
    throw new Error(`未找到前端入口 index.html，请先执行 pnpm run build:web：\n${candidates.join('\n')}`)
  }
  return found
}

/**
 * 创建并显示主窗口。
 * 开发态 loadURL 指向 vite dev server 并自动打开 DevTools；生产态 loadFile 加载本地构建产物。
 * 窗口实例保存到模块级 mainWindow，供 IPC 回调判断窗口是否可用。
 */
function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200, // 初始窗口宽度（像素）
    height: 800, // 初始窗口高度（像素）
    minWidth: 900, // 允许用户拖拽到的最小宽度（像素），再窄布局会挤坏
    minHeight: 640, // 允许用户拖拽到的最小高度（像素）
    show: false, // 先隐藏窗口，等 ready-to-show 再显示，避免加载期间出现白屏闪烁
    title: 'Sparrow Work', // 窗口初始标题（页面里的 <title> 会覆盖它）
    backgroundColor: '#0b1120', // 窗口底色：与前端深色主题一致，减少首屏白闪
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'), // 预加载脚本路径：用它向渲染进程暴露白名单 API
      contextIsolation: true, // 开启上下文隔离：preload 与页面脚本分处不同上下文，防止原型污染
      nodeIntegration: false, // 关闭 Node 集成：页面里拿不到 require / process，降低安全风险
      sandbox: false, // 关闭渲染进程沙箱：否则 preload 无法正常使用 Node 能力
    },
  })

  // 页面首帧准备好后再显示窗口，配合上面的 show:false 彻底消除白屏
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  // 窗口被关闭时清空引用，避免后续 IPC 回调操作到已销毁的窗口
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // 开发态优先用 electron-vite 注入的实际地址（vite 端口漂移时会变），否则退回共享常量
  const devServerUrl = process.env.ELECTRON_RENDERER_URL ?? DEV_SERVER_URL
  if (isDev) {
    void mainWindow.loadURL(devServerUrl)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    // 渲染产物：开发态在 frontend/dist，打包后在 resources/renderer（extraResources）
    void mainWindow.loadFile(resolveRendererEntry())
  }
}

/**
 * 应用启动流程：拉起（或复用）后端，成功后再创建窗口。
 *
 * 后端目标由 backend.config.json / APP_BACKEND_TARGET 决定，默认 Java；
 * 后端不可用时不阻断启动——startBackend 内部会等待健康检查超时并降级，由前端页面提示连接失败。
 */
async function bootstrap(): Promise<void> {
  // 项目根目录：electron/out/main → 上三级就是仓库根目录
  const projectRoot = join(__dirname, '../../..')

  const handle = await startBackend({
    projectRoot,
    resourcesPath: process.resourcesPath,
    isPackaged: app.isPackaged,
    // 打包态 Java 数据库写到用户数据目录，避免安装目录不可写
    userDataPath: app.getPath('userData'),
  })
  // owned=true 说明后端是本进程拉起的，退出时需要负责关掉；false 表示复用了外部已启动的服务
  if (handle.owned) {
    console.log(`[electron] 已拉起 ${handle.target} 后端，端口 ${handle.port}`)
  }

  createWindow()

  // 窗口建好之后再接自动更新：更新对话框需要有一个窗口做父对象，
  // 状态广播也需要窗口已经存在（见 updater.ts 的 windowGetter）
  initUpdater(() => mainWindow)
  // 不 await：检查更新要联网，不能拖慢启动；后台跑完把结果广播给「关于」页即可。
  // 传端口是因为 updater 要读后端的 ops.auto_update_check（设置页关掉后就不再自动检查）
  void maybeAutoCheck(handle.port)
}

/**
 * IPC 通道 `dialog:selectFolder`：弹出系统原生文件夹选择框。
 * 供渲染进程的 desktop.selectFolder() 调用；用户取消或窗口已关闭时返回 null。
 */
ipcMain.handle('dialog:selectFolder', async () => {
  if (!mainWindow) return null
  const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'], // openDirectory：只能选文件夹，不能选文件
    title: '请选择一个文件夹',
  })
  return canceled ? null : filePaths[0]
})

// 在系统文件管理器中定位文件：打开其所在文件夹并选中该文件
ipcMain.handle('shell:showItemInFolder', (_event, targetPath: string) => {
  shell.showItemInFolder(targetPath)
})

// 用系统默认方式打开路径：文件夹 → 文件管理器，文件 → 系统默认程序；返回空串表示成功
ipcMain.handle('shell:openPath', async (_event, targetPath: string) => {
  return shell.openPath(targetPath)
})

// 单实例锁：避免重复启动导致端口冲突
const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  // 已经有实例在跑：本进程直接退出，把焦点交给那个实例
  app.quit()
} else {
  // 可选：调试端口（配合 ELECTRON_DEBUG_PORT=9222 使用 CDP 观察渲染进程）
  const debugPort = process.env.ELECTRON_DEBUG_PORT
  if (debugPort) {
    app.commandLine.appendSwitch('remote-debugging-port', debugPort)
  }

  // 用户第二次启动时触发：把已有窗口从最小化恢复并置前，而不是新开一个
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  // Electron 初始化完成后才开始跑启动流程；失败就弹错误框并退出，避免留下无窗口的僵尸进程
  app.whenReady().then(async () => {
    try {
      await bootstrap()
    } catch (error) {
      dialog.showErrorBox('启动失败', String(error))
      app.quit()
    }

    // macOS 习惯：点击 Dock 图标且没有窗口时重新创建一个
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })
}

// 所有窗口关闭后退出应用；macOS 上保留进程驻留（符合平台习惯）
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

// 应用即将退出：关掉本次由主进程拉起的后端（Java 或 Python），避免残留进程占用端口
app.on('will-quit', () => {
  stopBackend()
})
