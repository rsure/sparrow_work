/**
 * 一键开发启动器：后端（默认 Java，可切 Python）+ Vite 前端 + Electron 桌面壳。
 *
 *   node scripts/dev.mjs                       # 按 backend.config.json 启动（默认 java）
 *   node scripts/dev.mjs --backend=python      # 本次改用 Python 后端
 *   node scripts/dev.mjs --port=9000           # 临时改端口
 *   node scripts/dev.mjs --backend-only        # 只启动后端，不启动前端/Electron
 *
 * 与 `concurrently` 的区别：这里会等前端 dev server 真正可访问后再拉起 Electron，
 * 并且退出时会把三个进程（含 Windows 进程树）一起收掉。
 *
 * JS/TS 侧统一使用 pnpm，所以下面拉起前端/Electron 时调用的也是 pnpm。
 */

// Node 子进程：负责拉起后端 / vite / electron 三个子进程并监听它们的退出
import { spawn } from 'node:child_process'
// 把 import.meta.url（file:// 形式的 URL）转成本机文件路径，用来推导项目根目录
import { fileURLToPath } from 'node:url'
// Node 路径工具：dirname 取目录，resolve 拼绝对路径（rootDir 由它算出）
import { dirname, resolve } from 'node:path'
// 在 ESM 里创建 require：本项目是纯 ESM 脚本，但 wait-on 只有 CJS 入口，需要它来加载
import { createRequire } from 'node:module'
// Node 文件系统：判断 backend.config.json / Maven Wrapper 是否存在
import { existsSync, readFileSync } from 'node:fs'

// 基于当前模块 URL 的 require，供下面加载 wait-on 使用
const require = createRequire(import.meta.url)
// wait-on：轮询等待某个 URL/端口可用，用于在拉起 Electron 前确认前端与后端已就绪
const waitOn = require('wait-on')

// 本脚本所在目录（scripts/）的绝对路径
const __dirname = dirname(fileURLToPath(import.meta.url))
// 项目根目录：scripts/ 的上一级，所有子进程都以它为工作目录
const rootDir = resolve(__dirname, '..')
// 是否 Windows：决定 spawn 时要不要加 shell（Windows 必须加才能解析 .cmd shim）
const isWindows = process.platform === 'win32'
// 注意：Windows 上必须配合 shell: true 使用（否则 pnpm 的 .cmd shim 无法直接 spawn），
// 但不要写 '.cmd' 后缀 —— 'pnpm.cmd' + shell:true 会抛 spawn EINVAL。
const pnpm = 'pnpm'

// 后端配置文件名：与 electron/src/shared/config.ts 的 BACKEND_CONFIG_FILE 保持一致
const BACKEND_CONFIG_FILE = 'backend.config.json'
// 默认外部端口：与 Java/Python 后端的 APP_PORT 默认值一致
const DEFAULT_PORT = 8000
// 默认后端目标：与 electron/src/shared/config.ts 的 DEFAULT_BACKEND_TARGET 保持一致
const DEFAULT_BACKEND_TARGET = 'java'
// Java 开发态启动命令模板：{mvnw} 会替换成 wrapper 或 mvn，{port} 替换成实际端口
const DEFAULT_JAVA_DEV_COMMAND =
  '{mvnw} -f backend_java/pom.xml spring-boot:run -Dspring-boot.run.arguments=--server.port={port}'
// Python 开发态启动命令模板
const DEFAULT_PYTHON_DEV_COMMAND = 'uv run python run.py --port {port}'

// Vite 打印形如 "Local:   http://127.0.0.1:5173/"（中间夹着 ANSI 颜色码），
// 5173 被占用时会自动换成下一个空闲端口
// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b\[[0-9;]*m/g
// 从 Vite 输出里抠出实际监听地址的正则（只匹配 "Local:" 那一行，忽略 Network 行）
const VITE_LOCAL_URL_RE = /Local:\s+(https?:\/\/[^\s]+)/

/**
 * 解析命令行参数。
 *
 * @param argv process.argv.slice(2)
 * @returns {{ backend: 'java'|'python'|null, port: number|null, backendOnly: boolean }}
 */
function parseCliArgs(argv) {
  // backend：--backend=java / --backend=python；非法值忽略，交给配置文件兜底
  let backend = null
  // port：--port=9000
  let port = null
  // backendOnly：只起后端，方便单独调试
  let backendOnly = false

  for (const arg of argv) {
    if (arg === '--backend-only') {
      backendOnly = true
      continue
    }
    if (arg.startsWith('--backend=')) {
      const value = arg.slice('--backend='.length).trim()
      // 只接受两个合法值，避免拼错后静默启动错误的语言
      if (value === 'java' || value === 'python') backend = value
      continue
    }
    if (arg.startsWith('--port=')) {
      const parsed = Number.parseInt(arg.slice('--port='.length), 10)
      // 只有正整数端口才采用
      if (Number.isFinite(parsed) && parsed > 0) port = parsed
    }
  }

  return { backend, port, backendOnly }
}

/**
 * 读取项目根目录的 backend.config.json。
 *
 * @returns 解析后的配置对象；文件不存在或解析失败时返回空对象
 */
function readBackendConfigFile() {
  const configPath = resolve(rootDir, BACKEND_CONFIG_FILE)
  try {
    if (!existsSync(configPath)) return {}
    return JSON.parse(readFileSync(configPath, 'utf8'))
  } catch (error) {
    log('dev', `读取 ${configPath} 失败，使用默认配置：${String(error)}`)
    return {}
  }
}

/**
 * 解析 Maven 命令：优先仓库自带的 Maven Wrapper。
 *
 * @returns 可拼进 shell 命令的 Maven 命令（含引号）
 */
function resolveMavenCommand() {
  const wrapper = resolve(rootDir, 'backend_java', isWindows ? 'mvnw.cmd' : 'mvnw')
  // 路径可能包含空格，加引号；找不到 wrapper 时退回全局 mvn
  return existsSync(wrapper) ? `"${wrapper}"` : 'mvn'
}

/**
 * 展开命令模板里的 {port} / {mvnw} 占位符。
 *
 * @param template 命令模板
 * @param port 实际端口
 * @returns 可交给 shell 执行的命令字符串
 */
function expandCommand(template, port) {
  return template
    .replaceAll('{port}', String(port))
    .replaceAll('{mvnw}', resolveMavenCommand())
}

/**
 * 合并 CLI、环境变量、配置文件，得到本次启动设置。
 *
 * 优先级：CLI > 环境变量 > backend.config.json > 默认值。
 *
 * @param {{backend: string|null, port: number|null}} cli 命令行参数
 * @returns {{ target: 'java'|'python', port: number, config: object }}
 */
function resolveBackendSettings(cli) {
  const config = readBackendConfigFile()

  // 目标：CLI > APP_BACKEND_TARGET/BACKEND_TARGET > 配置文件 > 默认 java
  const envTarget = process.env.APP_BACKEND_TARGET ?? process.env.BACKEND_TARGET
  const configTarget = config.target
  const target = cli.backend
    ?? (envTarget === 'java' || envTarget === 'python' ? envTarget : null)
    ?? (configTarget === 'java' || configTarget === 'python' ? configTarget : null)
    ?? DEFAULT_BACKEND_TARGET

  // 端口：CLI > APP_PORT > 配置文件 > 默认 8000
  const envPort = Number.parseInt(process.env.APP_PORT ?? '', 10)
  const configPort = Number.isFinite(config.port) && config.port > 0 ? Number(config.port) : null
  const port = cli.port
    ?? (Number.isFinite(envPort) && envPort > 0 ? envPort : null)
    ?? configPort
    ?? DEFAULT_PORT

  return { target, port, config }
}

/**
 * 构造后端启动命令与工作目录。
 *
 * @param {{target: 'java'|'python', port: number, config: object}} settings 后端设置
 * @returns {{ command: string, cwd: string }} 可交给 spawn 的命令与工作目录
 */
function buildBackendCommand(settings) {
  if (settings.target === 'java') {
    // 环境变量 JAVA_BACKEND_CMD 可以整体覆盖命令（例如指定另一套 JDK/Maven）
    const template = process.env.JAVA_BACKEND_CMD?.trim()
      || settings.config.java?.devCommand
      || DEFAULT_JAVA_DEV_COMMAND
    return {
      command: expandCommand(template, settings.port),
      // Java 的开发命令里已经写了 -f backend_java/pom.xml，所以 cwd 用项目根目录
      cwd: rootDir,
    }
  }

  const template = process.env.PYTHON_BACKEND_CMD?.trim()
    || settings.config.python?.devCommand
    || DEFAULT_PYTHON_DEV_COMMAND
  return {
    command: expandCommand(template, settings.port),
    // Python 的 run.py 在 backend/ 下，cwd 指到后端目录
    cwd: resolve(rootDir, settings.config.python?.devDir ?? 'backend'),
  }
}

/**
 * 从 Vite dev server 的输出中解析出它实际监听的地址（端口可能因占用而漂移）。
 *
 * @param child 已启动的 vite 子进程
 * @returns 解析出的 dev server 地址，如 http://127.0.0.1:5173/
 * @rejects 进程提前退出，或 30 秒内始终没打印监听地址
 */
function waitForViteUrl(child) {
  return new Promise((resolvePromise, rejectPromise) => {
    // 标记 Promise 是否已结算：data 事件可能多次触发，防止重复 resolve
    let settled = false
    /** stdout 数据回调：每收到一段输出就尝试解析 Local 地址，命中即 resolve 并解绑 */
    const onData = (chunk) => {
      // 先剥掉 ANSI 颜色码，否则正则会匹配到 \x1b[32m 之类的干扰字符
      const clean = chunk.toString('utf8').replace(ANSI_RE, '')
      const match = VITE_LOCAL_URL_RE.exec(clean)
      if (!match || settled) return
      settled = true
      child.stdout.off('data', onData)
      resolvePromise(match[1])
    }
    child.stdout.on('data', onData)
    // 进程在打印地址前就挂掉：直接失败，不必等满 30 秒
    child.once('exit', () => {
      if (!settled) rejectPromise(new Error('vite 进程退出前未输出监听地址'))
    })
    // 兜底超时：防止 vite 一直不输出 Local 行导致脚本永久挂起
    setTimeout(() => {
      if (!settled) {
        settled = true
        child.stdout.off('data', onData)
        rejectPromise(new Error('等待 vite 输出监听地址超时'))
      }
    }, 30_000)
  })
}

/** 各子进程日志的前缀配色（ANSI 转义码），让三个进程的输出在同一个终端里能一眼区分 */
const COLORS = {
  backend: '\u001b[36m', // cyan 青色：后端日志
  web: '\u001b[35m', // magenta 洋红：Vite 前端日志
  electron: '\u001b[32m', // green 绿色：Electron 主进程日志
  dev: '\u001b[33m', // yellow 黄色：启动器自身（dev.mjs）的提示信息
  reset: '\u001b[0m', // 重置颜色：每行结尾恢复默认，避免后续输出被染色
}

/** 已启动的子进程集合（元素形如 { name, child }）：shutdown 时遍历它逐个结束 */
const boxes = new Set()
/** 是否正在退出：防止多个退出信号重复执行 shutdown 逻辑 */
let shuttingDown = false

/**
 * 按 scope 选择颜色，打印一行带 `[scope]` 前缀的启动器日志。
 *
 * @param scope 日志分类（backend / web / electron / dev），同时决定颜色
 * @param message 要打印的正文
 */
function log(scope, message) {
  const color = COLORS[scope] ?? COLORS.dev
  console.log(`${color}[${scope}]${COLORS.reset} ${message}`)
}

/**
 * 启动前先确认 pnpm 可用，避免后面抛一句难懂的 ENOENT。
 *
 * @returns pnpm 可用时 resolve；不可用时直接结束进程
 */
function assertPnpmAvailable() {
  return new Promise((resolvePromise) => {
    let settled = false
    /** 失败收口：打印安装指引并无条件退出进程（幂等） */
    const fail = (reason) => {
      if (settled) return
      settled = true
      log('dev', `pnpm 不可用（${reason}）。请先安装：npm i -g pnpm 或 corepack enable pnpm`)
      process.exit(1)
    }

    let probe
    try {
      probe = spawn(pnpm, ['--version'], { stdio: 'ignore', shell: isWindows, windowsHide: true })
    } catch (error) {
      fail(String(error))
      return
    }

    probe.on('error', (error) => fail(String(error)))
    probe.on('exit', (code) => {
      if (settled) return
      settled = true
      if (code === 0) resolvePromise()
      else fail(`exit code ${code ?? 'null'}`)
    })
  })
}

/**
 * 给某个子进程的 stdout/stderr 逐行加 `[scope]` 前缀后转发到控制台。
 *
 * @param stream 子进程的输出流（stdout 或 stderr）
 * @param scope 日志前缀分类
 */
function prefixOutput(stream, scope) {
  let buffer = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk) => {
    buffer += chunk
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const color = COLORS[scope] ?? COLORS.dev
      process.stdout.write(`${color}[${scope}]${COLORS.reset} ${line}\n`)
    }
  })
}

/**
 * 统一启动一个子进程。
 *
 * @param name 进程名称，同时作为日志前缀与退出判断依据
 * @param command 要执行的命令
 * @param args 命令参数数组
 * @param options 额外 spawn 选项；可覆盖 cwd / shell
 * @returns 记录该进程的 box 对象（name + child）
 */
function start(name, command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: rootDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    // Windows 上需要 shell 才能解析 pnpm / uv / mvnw.cmd 这类 shim
    shell: isWindows,
    windowsHide: true,
    ...options,
  })

  const box = { name, child }
  boxes.add(box)

  prefixOutput(child.stdout, name)
  prefixOutput(child.stderr, name)

  child.on('error', (error) => log('dev', `${name} 启动失败：${String(error)}`))
  child.on('exit', (code, signal) => {
    log('dev', `${name} 已退出 (code=${code ?? 'null'}, signal=${signal ?? 'null'})`)
    boxes.delete(box)
    // 前端或 Electron 挂了就没必要继续跑；只起后端时不受此规则影响
    if (!shuttingDown && name !== 'backend') {
      void shutdown(0)
    }
  })

  return box
}

/**
 * 结束一个子进程及其子进程树。
 *
 * @param child 目标子进程
 */
function killTree(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return
  if (isWindows && child.pid !== undefined) {
    spawn('taskkill', ['/pid', String(child.pid), '/f', '/t'], { windowsHide: true, shell: true })
    return
  }
  child.kill('SIGTERM')
}

/**
 * 退出收尾：杀掉所有子进程，等待 600ms 让 taskkill 生效，再按指定退出码结束本进程。
 *
 * @param exitCode 本脚本的退出码，0 表示正常退出
 */
async function shutdown(exitCode = 0) {
  if (shuttingDown) return
  shuttingDown = true
  log('dev', '正在停止所有子进程…')
  for (const box of boxes) killTree(box.child)
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 600))
  process.exit(exitCode)
}

/**
 * 主流程。
 */
async function main() {
  log('dev', `项目根目录：${rootDir}`)

  // 1) 解析本次要启动的后端
  const cli = parseCliArgs(process.argv.slice(2))
  const settings = resolveBackendSettings(cli)
  const backend = buildBackendCommand(settings)
  const healthUrl = `http-get://127.0.0.1:${settings.port}/api/health`

  // 只起后端时不需要 pnpm 与前端
  if (!cli.backendOnly) {
    await assertPnpmAvailable()
  }

  // 2) 后端（默认 Java；shell:true 是为了解析 mvnw.cmd / uv）
  log('backend', `target=${settings.target} port=${settings.port}`)
  log('backend', backend.command)
  start('backend', backend.command, [], { cwd: backend.cwd, shell: true })

  // 只启动后端：保持进程存活，Ctrl+C 时由 shutdown 收尾
  if (cli.backendOnly) {
    log('dev', '仅启动后端模式；按 Ctrl+C 退出')
    await new Promise(() => {})
    return
  }

  // 3) Vue3 前端 dev server
  log('web', 'vite dev server')
  const webBox = start('web', pnpm, ['--filter', 'app-frontend', 'run', 'dev'])

  // 4) 等前端可访问后再启动 Electron（Electron 会复用已就绪的后端）
  log('dev', '等待 vite dev server 输出监听地址…')
  const frontendUrl = await waitForViteUrl(webBox.child)
  log('dev', `前端已就绪：${frontendUrl}`)
  await waitOn({ resources: [frontendUrl], timeout: 60_000, interval: 300, log: false })

  log('dev', `等待 ${healthUrl} 就绪…`)
  try {
    await waitOn({ resources: [healthUrl], timeout: 30_000, interval: 500, log: false })
  } catch {
    // 后端慢启动不阻塞 Electron：主进程启动时还会再探活一次
    log('dev', '后端健康检查未就绪（继续启动 Electron，页面会提示连接失败）')
  }

  log('electron', 'electron-vite dev')
  start('electron', pnpm, ['--filter', 'app-electron', 'run', 'dev'])
}

// Ctrl+C / 被终止时走统一收尾，保证所有子进程一起退出
process.on('SIGINT', () => void shutdown(0))
process.on('SIGTERM', () => void shutdown(0))

// 启动失败：记录原因并以非 0 退出码收尾
main().catch(async (error) => {
  log('dev', `启动失败：${String(error)}`)
  await shutdown(1)
})
