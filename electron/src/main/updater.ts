/**
 * 自动更新（OPS-4）：把 electron-updater 接进主进程。
 *
 * 工作方式（对应 doc/24 的 OPS-4 要求）：
 *   1. 打包后的应用启动时自动检查一次（可在设置页关掉 `ops.auto_update_check`）；
 *   2. 用户在「关于」页点「检查更新」可手动检查；
 *   3. 发现新版本 → 弹原生对话框问「要不要下载」→ 下完再问「现在重启安装吗」；
 *   4. 状态变化会广播给渲染进程，页面据此显示「检查中 / 有新版本 / 已是最新 / 失败」。
 *
 * 两个关键事实：
 *   - 开发态（未打包）没有 app-update.yml，electron-updater 会直接抛错，所以这里主动跳过；
 *   - 更新源来自 electron-builder.yml 的 publish 配置（打包时生成 resources/app-update.yml），
 *     改发布地址只改 electron-builder.yml，不改代码。
 */
// Electron 主进程 API：app 判断是否打包、取版本号；dialog 弹原生对话框；ipcMain 注册通道
// BrowserWindow 类型用于窗口引用（广播状态时用）
import { app, BrowserWindow, dialog, ipcMain } from 'electron'
// 自动更新器：electron-updater 的单例，内部处理差分下载与签名校验
import { autoUpdater } from 'electron-updater'

// 共享类型：状态快照的形状在三个进程间必须一致
import type { UpdateState, UpdateStatus } from '../shared/update'


/** 状态广播通道：主进程 → 渲染进程（页面订阅它来刷新「关于」页） */
const EVENT_CHANNEL = 'update:state-changed'

/** 模块级状态：整个应用只维护一份，任何一次 check/download 都更新它 */
let state: UpdateState = {
  status: 'idle',
  version: null,
  percent: 0,
  message: '',
  checked_at: null,
}

/** 取窗口的回调：窗口可能被关掉再打开，所以每次广播时现取，不缓存实例 */
let windowGetter: (() => BrowserWindow | null) | null = null

/** 是否已经初始化过（IPC 通道只需注册一次；重复注册会抛 "second handler" 错误） */
let initialized = false

/** 是否正在检查（防止启动自动检查与用户手点同时进行，弹两次对话框） */
let checking = false


/**
 * 取当前状态快照的副本。
 * @returns 状态对象（拷贝，调用方改了也不影响模块内的那份）
 */
export function getUpdateState(): UpdateState {
  return { ...state }
}

/**
 * 更新状态并广播给渲染进程。
 * @param patch 要合并进状态的字段
 */
function setState(patch: Partial<UpdateState>): void {
  state = { ...state, ...patch }
  const win = windowGetter?.() ?? null
  // 窗口可能已经关闭（更新检查是异步的，用户可能中途退出了页面）：此时静默丢弃
  if (win && !win.isDestroyed()) {
    win.webContents.send(EVENT_CHANNEL, getUpdateState())
  }
}

/**
 * 把 status 单独设成一个值（同时保留其它字段）。
 * @param status 新的阶段
 * @param message 附带的一句说明；不传表示沿用旧值
 */
function setStatus(status: UpdateStatus, message?: string): void {
  setState(message === undefined ? { status } : { status, message })
}

/**
 * 读后端的 `ops.auto_update_check` 设置，决定要不要在启动时自动检查。
 *
 * 为什么要绕到后端去读：
 *   设置页的所有开关都存在后端（app_settings 表），Electron 自己另存一份就会出现
 *   「设置页关了它、下次启动还是检查」的分裂状态。这里在启动时读一次即可——
 *   用户改了开关，下一次启动生效（导入导出也会覆盖这个键）。
 *
 * @param port Python 后端正在监听的端口
 * @returns 是否自动检查；读不到时按 true 处理（宁可多查一次，也不要静默失效）
 */
async function readAutoCheck(port: number): Promise<boolean> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/settings`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!response.ok) return true
    const body = (await response.json()) as { data?: { values?: Record<string, unknown> } }
    const value = body.data?.values?.['ops.auto_update_check']
    return value === undefined ? true : value === true
  } catch {
    // 后端还没起来或端口不对：不因为读不到设置就不检查（这属于异常路径）
    return true
  }
}

/**
 * 检查是否有新版本。
 *
 * @param manual 是否是用户手点的（手点时要给出"已是最新/检查失败"的明确反馈，静默不了）
 * @returns 检查结束时的状态快照
 */
export async function checkForUpdates(manual = false): Promise<UpdateState> {
  // 开发态没有 app-update.yml，electron-updater 会抛 "ENOENT"，不如直接说明白
  if (!app.isPackaged) {
    setState({
      status: 'disabled',
      message: '开发态不检查更新（打包后的应用才具备更新能力）',
      checked_at: new Date().toISOString(),
    })
    if (manual) {
      void dialog.showMessageBox({
        type: 'info',
        title: '自动更新',
        message: '当前是开发态，不检查更新',
        detail: '用 `pnpm run dist` 打包出的安装版才会启用自动更新。',
      })
    }
    return getUpdateState()
  }

  if (checking) return getUpdateState()
  checking = true
  setState({ status: 'checking', percent: 0, message: '正在检查更新…' })
  try {
    // checkForUpdates 会读 app-update.yml 里的发布源；网络失败会抛错（下面统一处理）
    await autoUpdater.checkForUpdates()
    setState({ checked_at: new Date().toISOString() })
  } catch (error) {
    setState({
      status: 'error',
      message: `检查更新失败：${describeError(error)}`,
      checked_at: new Date().toISOString(),
    })
    if (manual) {
      void dialog.showMessageBox({
        type: 'warning',
        title: '检查更新失败',
        message: describeError(error),
        detail: '可能是网络不通，或 electron-builder.yml 里的发布地址还没配置。',
      })
    }
  } finally {
    checking = false
  }
  return getUpdateState()
}

/**
 * 把异常压成一句人能看懂的说明（IPC 不能传 Error，对话框也不该出现堆栈）。
 * @param error 任意异常
 * @returns 一行文字
 */
function describeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

/**
 * 有新版本时问用户要不要下载；下载完成后问要不要立刻重启安装。
 * 这两步都用原生对话框而不是页面弹层：更新时页面可能正处在任何状态（甚至是白屏）。
 */
function promptDownload(version: string): void {
  void dialog
    .showMessageBox({
      type: 'info',
      title: '发现新版本',
      message: `发现新版本 ${version}`,
      detail: '现在下载吗？下载在后台进行，不影响你继续使用。',
      buttons: ['下载', '以后再说'],
      defaultId: 0,
      cancelId: 1,
    })
    .then(({ response }) => {
      if (response === 0) {
        setState({ status: 'downloading', percent: 0, message: `正在下载 ${version}…` })
        void autoUpdater.downloadUpdate().catch((error: unknown) => {
          setState({ status: 'error', message: `下载失败：${describeError(error)}` })
        })
      } else {
        setState({ status: 'available', message: `新版本 ${version} 已可用，稍后可在「关于」页下载` })
      }
    })
}

/**
 * 下载完成后询问是否重启安装。
 * @param version 刚下载完的版本号
 */
function promptInstall(version: string): void {
  void dialog
    .showMessageBox({
      type: 'info',
      title: '更新已就绪',
      message: `新版本 ${version} 已下载完成`,
      detail: '现在重启应用完成安装吗？（选「稍后」则下次退出时自动安装）',
      buttons: ['立即重启安装', '稍后'],
      defaultId: 0,
      cancelId: 1,
    })
    .then(({ response }) => {
      if (response === 0) {
        // isSilent=false 让安装程序显示进度；isForceRunAfter=true 装完自动把应用拉起来
        autoUpdater.quitAndInstall(false, true)
      }
    })
}

/**
 * 初始化自动更新：注册事件监听与 IPC 通道（幂等，重复调用只生效一次）。
 *
 * @param getWindow 取当前主窗口的回调；状态广播时用它
 */
export function initUpdater(getWindow: () => BrowserWindow | null): void {
  windowGetter = getWindow
  if (initialized) return
  initialized = true

  // 手动控制下载时机：发现新版本先问用户，而不是默默吃掉带宽
  autoUpdater.autoDownload = false
  // 用户选了「稍后」时，退出应用自动完成安装，避免更新被无限拖延
  autoUpdater.autoInstallOnAppQuit = true
  // 把 electron-updater 自己的日志接进主进程控制台，方便排查更新失败
  autoUpdater.logger = {
    info: (...args: unknown[]) => console.log('[update]', ...args),
    warn: (...args: unknown[]) => console.warn('[update]', ...args),
    error: (...args: unknown[]) => console.error('[update]', ...args),
    debug: (...args: unknown[]) => console.debug('[update]', ...args),
  }

  autoUpdater.on('checking-for-update', () => setStatus('checking', '正在检查更新…'))
  autoUpdater.on('update-available', (info) => {
    setState({
      status: 'available',
      version: info.version,
      message: `发现新版本 ${info.version}`,
      checked_at: new Date().toISOString(),
    })
    promptDownload(info.version)
  })
  autoUpdater.on('update-not-available', () => {
    setState({
      status: 'not-available',
      version: null,
      message: '已是最新版本',
      checked_at: new Date().toISOString(),
    })
  })
  autoUpdater.on('download-progress', (progress) => {
    setState({
      status: 'downloading',
      percent: Math.round(progress.percent),
      message: `正在下载 ${Math.round(progress.percent)}%`,
    })
  })
  autoUpdater.on('update-downloaded', (info) => {
    setState({
      status: 'downloaded',
      version: info.version,
      percent: 100,
      message: `新版本 ${info.version} 已下载完成，重启即可安装`,
    })
    promptInstall(info.version)
  })
  autoUpdater.on('error', (error) => {
    setState({
      status: 'error',
      message: `更新失败：${describeError(error)}`,
      checked_at: new Date().toISOString(),
    })
  })

  // IPC：页面主动查状态、手点检查、立即安装
  ipcMain.handle('update:state', () => getUpdateState())
  ipcMain.handle('update:check', () => checkForUpdates(true))
  ipcMain.handle('update:install', () => {
    // 只有下载完成才允许安装；否则 electron-updater 会抛错
    if (state.status === 'downloaded') {
      autoUpdater.quitAndInstall(false, true)
    }
  })
  // 应用版本号：页面要显示"当前版本 v0.1.0"，主进程的 app.getVersion() 才是权威值
  ipcMain.handle('app:version', () => app.getVersion())
}

/**
 * 启动时按设置决定是否自动检查一次更新（在窗口创建之后调用）。
 *
 * @param port Python 后端端口（用来读 ops.auto_update_check）
 */
export async function maybeAutoCheck(port: number): Promise<void> {
  if (!app.isPackaged) {
    setState({ status: 'disabled', message: '开发态不检查更新' })
    return
  }
  const enabled = await readAutoCheck(port)
  if (!enabled) {
    setState({ status: 'disabled', message: '自动检查更新已在设置里关闭' })
    return
  }
  // 延迟几秒再查：让窗口先画出来，别和启动时的后端拉起抢资源
  setTimeout(() => {
    void checkForUpdates(false)
  }, 3000)
}
