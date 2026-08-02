/**
 * 把 PyInstaller 产物（backend/dist/app-backend/）同步到 electron/resources/backend/，
 * 让 electron-builder 能通过 extraResources 把它打进安装包。
 *
 *   node scripts/sync-backend.mjs
 *   pnpm run build:backend        （先 PyInstaller 打包，再执行本脚本）
 */

// Node 文件系统（Promise 版）：cp 复制目录树、mkdir 建目录、readdir 列目录、
// rm 清空旧产物、stat 取文件大小用于统计
import { cp, mkdir, readdir, rm, stat } from 'node:fs/promises'
// Node 文件系统（同步版）：只需一个「源目录是否存在」的判断，同步写法更直观
import { existsSync } from 'node:fs'
// Node 路径工具：dirname 取目录、join 拼子路径、resolve 拼绝对路径
import { dirname, join, resolve } from 'node:path'
// 把 import.meta.url 转成本机路径，用来推导脚本自身所在目录
import { fileURLToPath } from 'node:url'

// 本脚本所在目录（scripts/）的绝对路径
const __dirname = dirname(fileURLToPath(import.meta.url))
// 项目根目录：scripts/ 的上一级
const rootDir = resolve(__dirname, '..')
// 同步源：PyInstaller 的产出目录（里面是 exe + 依赖文件）
const from = join(rootDir, 'backend', 'dist', 'app-backend')
// 同步目标：electron-builder 的 extraResources 目录，打包时会被整体拷进安装包
const to = join(rootDir, 'electron', 'resources', 'backend')

// 前置校验一：源目录不存在说明还没跑 PyInstaller，直接报错退出而不是产生一个空目录
if (!existsSync(from)) {
  console.error(`[sync-backend] 未找到 PyInstaller 产物：${from}`)
  console.error('[sync-backend] 请先执行：pnpm run build:backend:only')
  process.exit(1)
}

// 找出以 app-backend 开头的可执行文件（Windows 是 app-backend.exe，类 Unix 是 app-backend）
const exeNames = (await readdir(from)).filter((name) => name.startsWith('app-backend'))
// 前置校验二：没有可执行文件说明打包产物不完整，同样报错退出
if (exeNames.length === 0) {
  console.error(`[sync-backend] ${from} 里没有 app-backend 可执行文件`)
  process.exit(1)
}

// 先整体删除目标目录再重建：避免残留上一次的旧文件被打进安装包
await rm(to, { recursive: true, force: true })
await mkdir(to, { recursive: true })
// verbatimSymlinks：按原样复制符号链接本身，不追进目标（PyInstaller 产物里可能有链接）
await cp(from, to, { recursive: true, verbatimSymlinks: true })

// 回读目标目录用于统计与日志
const copied = await readdir(to)
// 顶层文件总字节数：目录条目按 0 计，只累加普通文件，用于给出一句体积概览
const totalBytes = (
  await Promise.all(
    copied.map(async (name) => {
      const info = await stat(join(to, name))
      return info.isDirectory() ? 0 : info.size
    }),
  )
).reduce((sum, size) => sum + size, 0)

// 同步结果日志：条目数 + 可执行文件名 + 顶层体积（KB，保留整数）
console.log(`[sync-backend] 已同步 ${copied.length} 项到 electron/resources/backend`)
console.log(`[sync-backend] 可执行文件：${exeNames.join(', ')}（顶层合计 ${(totalBytes / 1024).toFixed(0)} KB）`)
