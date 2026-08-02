/**
 * Maven 启动器：优先使用 backend_java/mvnw(.cmd)，找不到再退回全局 mvn。
 *
 * 用法：
 *   node scripts/run-maven.mjs test
 *   node scripts/run-maven.mjs -DskipTests package
 *   node scripts/run-maven.mjs spring-boot:run
 *
 * 这样写的原因：Windows 与 Unix 的 wrapper 文件名不同，且路径可能包含空格；
 * 把解析逻辑集中在一个脚本里，package.json 就能保持跨平台。
 */

// Node 子进程：spawn 拉起 Maven，inherit 让日志直接进当前终端
import { spawn } from 'node:child_process'
// Node 文件系统：判断 wrapper 是否存在
import { existsSync } from 'node:fs'
// Node 路径工具：拼出 backend_java 与 wrapper 的绝对路径
import { dirname, join, resolve } from 'node:path'
// 把 import.meta.url 转成本机路径，用来推导脚本所在目录
import { fileURLToPath } from 'node:url'

// 本脚本所在目录（scripts/）
const __dirname = dirname(fileURLToPath(import.meta.url))
// 项目根目录
const rootDir = resolve(__dirname, '..')
// Java 后端模块目录
const backendDir = join(rootDir, 'backend_java')
// 是否 Windows：决定 wrapper 文件名与 shell 参数
const isWindows = process.platform === 'win32'

// 优先使用仓库自带的 Maven Wrapper；没有时退回全局 mvn
const wrapper = join(backendDir, isWindows ? 'mvnw.cmd' : 'mvnw')
// 路径可能包含空格，Windows 下必须加引号
const command = existsSync(wrapper) ? `"${wrapper}"` : 'mvn'

// 透传命令行参数；例如 `node scripts/run-maven.mjs -DskipTests package`
const args = process.argv.slice(2)

// shell: Windows 需要它解析 mvnw.cmd；Unix 下保持 false，避免多余的 shell 层
const child = spawn(command, args, {
  // 以 backend_java 为工作目录，pom.xml 就不用每次写 -f
  cwd: backendDir,
  stdio: 'inherit',
  shell: isWindows,
  windowsHide: true,
})

// 子进程启动失败（例如 wrapper 文件损坏）：打印原因并以 1 退出
child.on('error', (error) => {
  console.error('[run-maven] 启动失败：', error)
  process.exit(1)
})

// 把 Maven 的退出码透传给 pnpm，CI 才能正确判断成功/失败
child.on('exit', (code, signal) => {
  if (signal) {
    console.error(`[run-maven] 被信号终止：${signal}`)
    process.exit(1)
  }
  process.exit(code ?? 1)
})
