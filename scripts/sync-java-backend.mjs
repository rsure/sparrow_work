/**
 * 把 Java 后端的可执行 jar 同步到 electron/resources/backend/，
 * 让 electron-builder 能通过 extraResources 把它打进安装包。
 *
 *   node scripts/sync-java-backend.mjs
 *   pnpm run build:backend:java    （先 mvn package，再执行本脚本）
 */

// Node 文件系统（Promise 版）：mkdir 建目录、copyFile 复制 jar、stat 取大小
import { copyFile, mkdir, stat } from 'node:fs/promises'
// Node 文件系统（同步版）：只需判断源 jar 是否存在
import { existsSync } from 'node:fs'
// Node 路径工具：dirname 取目录、join 拼子路径、resolve 拼绝对路径
import { dirname, join, resolve } from 'node:path'
// 把 import.meta.url 转成本机路径，用来推导脚本自身所在目录
import { fileURLToPath } from 'node:url'

// 本脚本所在目录（scripts/）
const __dirname = dirname(fileURLToPath(import.meta.url))
// 项目根目录
const rootDir = resolve(__dirname, '..')
// Maven 打包产物：pom.xml 的 finalName 固定为 backend-java
const from = join(rootDir, 'backend_java', 'target', 'backend-java.jar')
// 同步目标：electron-builder 的 extraResources 目录
const to = join(rootDir, 'electron', 'resources', 'backend', 'backend-java.jar')

// 前置校验：jar 不存在说明还没打包，直接报错并给出修复命令
if (!existsSync(from)) {
  console.error(`[sync-java-backend] 未找到 jar：${from}`)
  console.error('[sync-java-backend] 请先执行：pnpm run build:backend:java:only')
  process.exit(1)
}

// 目标目录可能不存在（首次构建），先创建
await mkdir(dirname(to), { recursive: true })
// 覆盖复制：保证安装包里永远是最新 jar
await copyFile(from, to)

// 读取大小用于日志（MB，保留 1 位小数）
const info = await stat(to)
console.log(
  `[sync-java-backend] 已同步 ${to}（${(info.size / 1024 / 1024).toFixed(1)} MB）`,
)
