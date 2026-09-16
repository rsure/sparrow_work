/**
 * 后端生命周期管理：支持 Java（Spring Boot）与 Python（FastAPI）两种目标。
 *
 * 判定顺序：
 *   1. 先探测 127.0.0.1:port/api/health，已有健康后端就直接复用；
 *   2. 读取 backend.config.json / 环境变量，确定目标（默认 java）；
 *   3. 打包态优先启动 resources/backend 下的 jar/exe，开发态用 Maven/uv 拉起源码；
 *   4. 轮询健康检查，超时只警告、不阻断窗口创建。
 *
 * 被 electron/src/main/index.ts 的 bootstrap() 调用。
 */
// Node 子进程模块：spawn 负责拉起后端进程，ChildProcess 是它的返回类型
import { spawn, type ChildProcess } from 'node:child_process'
// Node 文件系统：判断 jar / exe / 精简 JRE 是否存在
import { existsSync } from 'node:fs'
// Node 路径工具：把 resourcesPath、项目根目录拼成候选绝对路径
import { join } from 'node:path'

// 共享常量：健康检查路径、端口兜底值、后端目标类型
import { BACKEND_HEALTH_PATH, BACKEND_PORT, type BackendTarget } from '../shared/config'
// 后端配置：读取 backend.config.json + 环境变量，并拼出开发态启动命令
import {
  buildJavaDevCommand,
  buildPythonDevCommand,
  loadBackendConfig,
  type BackendConfig,
} from '../shared/backend-config'

/** startBackend 的返回体：告诉调用方后端是否由本进程掌管、用的哪个端口与目标 */
export interface BackendHandle {
  /** 后端进程是我们自己拉起的（需要负责关掉）；false 表示复用了外部已启动的服务 */
  owned: boolean
  /** 后端实际监听的端口 */
  port: number
  /** 本次使用的后端类型：java / python */
  target: BackendTarget
}

/** 当前后端子进程句柄；进程退出或 stopBackend 后置为 null */
let child: ChildProcess | null = null
/** 心跳定时器句柄；用于随后端进程退出而清理，避免定时器泄漏 */
let heartbeat: NodeJS.Timeout | null = null
/** 后端是否由本进程拉起：决定退出时要不要杀掉它（复用外部服务时不能杀） */
let ownedBackend = false
/** 最近一次实际使用的后端端口：APP_PORT 覆盖后可能与默认值不同 */
let resolvedPort = BACKEND_PORT
/** 最近一次实际使用的后端类型：日志与调试展示用 */
let resolvedTarget: BackendTarget = 'java'

/**
 * 取后端端口：支持 APP_PORT 环境变量覆盖。
 *
 * @param fallback 配置文件给出的端口；环境变量优先
 * @returns 最终使用的端口
 */
export function getBackendPort(fallback: number = BACKEND_PORT): number {
  const raw = process.env.APP_PORT
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN
  // 只有解析出正整数才采用，否则回退到配置文件/默认端口
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

/**
 * 轮询健康检查接口，直到后端就绪或超时。
 *
 * @param port 后端监听端口
 * @param timeoutMs 最长等待时间（毫秒）
 * @returns 后端返回 code===0 表示就绪；超时或始终不通返回 false
 */
async function waitForHealth(port: number, timeoutMs: number): Promise<boolean> {
  const url = `http://127.0.0.1:${port}${BACKEND_HEALTH_PATH}`
  // 用绝对时间点做截止线，避免每次循环都重置等待时长
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    try {
      // 必须用 GET：Spring MVC / uvicorn 对 HEAD 的处理不同，显式 GET 最稳
      const response = await fetch(url, { method: 'GET', signal: AbortSignal.timeout(1500) })
      if (response.ok) {
        const body = (await response.json()) as { code?: number }
        // 只有业务码为 0 才算真正就绪：能连上但返回非 0 说明后端还在初始化
        if (body.code === 0) return true
      }
    } catch {
      // 后端还没起来，继续重试
    }
    await sleep(500)
  }
  return false
}

/**
 * 让当前异步流程暂停指定毫秒数。
 *
 * @param ms 暂停时长（毫秒）
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 定位打包后的 Java jar。
 *
 * @param resourcesPath Electron 的 process.resourcesPath
 * @param config 后端配置
 * @returns 存在的 jar 绝对路径；都不存在时返回 null
 */
function resolveJavaJar(
  resourcesPath: string,
  config: BackendConfig,
  isPackaged: boolean,
): string | null {
  const candidates = [
    // 环境变量显式指定，优先级最高
    process.env.JAVA_BACKEND_JAR,
    // electron-builder 的 extraResources 目录
    join(resourcesPath, 'backend', config.java.jar),
  ]

  // 只有开发态才接受 cwd / target 下的本地产物；打包态必须用安装包里的 jar，
  // 否则可能误跑一份过期的开发产物
  if (!isPackaged) {
    candidates.push(
      join(process.cwd(), 'resources', 'backend', config.java.jar),
      join(process.cwd(), config.java.devDir, 'target', config.java.jar),
    )
  }

  return candidates.filter((item): item is string => Boolean(item))
    .find((item) => existsSync(item)) ?? null
}

/**
 * 定位 Java 可执行文件。
 *
 * @param resourcesPath Electron 的 process.resourcesPath
 * @param config 后端配置
 * @returns 优先使用随包携带的精简 JRE；否则退回系统 PATH 里的 java
 */
function resolveJavaExecutable(resourcesPath: string, config: BackendConfig): string {
  const javaName = process.platform === 'win32' ? 'java.exe' : 'java'
  const explicit = process.env.JAVA_BACKEND_JAVA
  if (explicit && existsSync(explicit)) {
    return explicit
  }

  const bundled = join(resourcesPath, 'backend', config.java.bundledJre, 'bin', javaName)
  if (existsSync(bundled)) {
    return bundled
  }

  // 系统 PATH：要求 JAVA_HOME 指向 JDK 17+，否则会出现 UnsupportedClassVersionError
  return 'java'
}

/**
 * 打包态直接运行 Java jar。
 *
 * @param jarPath jar 绝对路径
 * @param javaExecutable java 可执行文件
 * @param port 监听端口
 * @returns 已 spawn 的子进程
 */
function spawnJavaPackaged(
  jarPath: string,
  javaExecutable: string,
  port: number,
  userDataPath: string,
): ChildProcess {
  // 打包后安装目录可能不可写（如 Program Files）；数据库放到 Electron 的 userData 目录。
  // 用户显式设置 APP_DB_PATH / APP_CHECKPOINT_DB_PATH 时，尊重用户配置。
  const dbPath = process.env.APP_DB_PATH ?? join(userDataPath, 'app.db')
  const checkpointPath = process.env.APP_CHECKPOINT_DB_PATH ?? join(userDataPath, 'app.db')

  return spawn(
    javaExecutable,
    [
      // Windows 控制台默认 GBK，强制 UTF-8 避免中文日志乱码
      '-Dfile.encoding=UTF-8',
      '-jar',
      jarPath,
      // Spring Boot 会把 --server.port 当作配置覆盖项
      `--server.port=${port}`,
    ],
    {
      env: {
        ...guardEnv(port),
        APP_PACKAGED: '1',
        APP_DB_PATH: dbPath,
        APP_CHECKPOINT_DB_PATH: checkpointPath,
      },
      stdio: ['pipe', 'inherit', 'inherit'],
      windowsHide: true,
    },
  )
}

/**
 * 开发态用 Maven Wrapper / Maven 启动 Java 后端。
 *
 * @param projectRoot 项目根目录（作为子进程工作目录）
 * @param config 后端配置
 * @param port 监听端口
 * @returns 已 spawn 的子进程
 */
function spawnJavaDev(projectRoot: string, config: BackendConfig, port: number): ChildProcess {
  const command = buildJavaDevCommand(config, projectRoot, port)
  // shell:true：Windows 需要它解析 mvnw.cmd / mvn.cmd
  return spawn(command, {
    cwd: projectRoot,
    shell: true,
    env: guardEnv(port),
    stdio: ['pipe', 'inherit', 'inherit'],
    windowsHide: true,
  })
}

/**
 * 开发态用 uv 启动 Python 后端。
 *
 * @param projectRoot 项目根目录
 * @param config 后端配置
 * @param port 监听端口
 * @returns 已 spawn 的子进程
 */
function spawnPythonDev(projectRoot: string, config: BackendConfig, port: number): ChildProcess {
  const command = buildPythonDevCommand(config, port)
  return spawn(command, {
    cwd: join(projectRoot, config.python.devDir),
    shell: true,
    env: { ...guardEnv(port), PYTHONUNBUFFERED: '1' },
    stdio: ['pipe', 'inherit', 'inherit'],
    windowsHide: true,
  })
}

/**
 * 定位打包后的 Python 可执行文件。
 *
 * @param resourcesPath Electron 的 process.resourcesPath
 * @param config 后端配置
 * @returns 存在的 exe 绝对路径；都不存在时返回 null
 */
function resolvePythonExe(resourcesPath: string, config: BackendConfig): string | null {
  const names = [config.python.exe, config.python.exe.replace(/\.exe$/i, '')]
  const candidates = [
    process.env.PYTHON_BACKEND_EXE,
    ...names.map((name) => join(resourcesPath, 'backend', name)),
    ...names.map((name) => join(process.cwd(), 'resources', 'backend', name)),
  ].filter((item): item is string => Boolean(item))

  return candidates.find((item) => existsSync(item)) ?? null
}

/**
 * 打包态直接运行 Python 可执行文件。
 *
 * @param exePath 可执行文件绝对路径
 * @param port 监听端口
 * @returns 已 spawn 的子进程
 */
function spawnPythonPackaged(exePath: string, port: number): ChildProcess {
  return spawn(exePath, ['--port', String(port)], {
    env: { ...guardEnv(port), APP_PACKAGED: '1', PYTHONUNBUFFERED: '1' },
    stdio: ['pipe', 'inherit', 'inherit'],
    windowsHide: true,
  })
}

/** 传给子进程的环境：APP_PARENT_GUARD 让后端通过 stdin 感知父进程退出 */
function guardEnv(port: number): NodeJS.ProcessEnv {
  return { ...process.env, APP_PORT: String(port), APP_PARENT_GUARD: '1' }
}

/**
 * 心跳：定期往子进程 stdin 写一个字节。
 *
 * @param proc 后端子进程
 * @returns 定时器句柄，供退出时 clearInterval
 */
function startHeartbeat(proc: ChildProcess): NodeJS.Timeout {
  const timer = setInterval(() => {
    // 管道可能已被对端关闭，先判空再写，避免 EPIPE 抛错
    if (!proc.stdin || proc.stdin.destroyed) return
    proc.stdin.write('.')
  }, 5000)
  timer.unref()
  return timer
}

/**
 * 启动本地后端。
 *
 * @param options.projectRoot 项目根目录（开发态启动命令的 cwd）
 * @param options.resourcesPath Electron 的 process.resourcesPath
 * @param options.isPackaged 是否已打包；决定用 jar/exe 还是开发命令
 * @param options.userDataPath Electron 的用户数据目录；打包态 Java 数据库放这里
 * @returns owned 表示进程是否由本进程掌管，port/target 为实际使用的值
 */
export async function startBackend(options: {
  projectRoot: string
  resourcesPath: string
  isPackaged: boolean
  userDataPath: string
}): Promise<BackendHandle> {
  const config = loadBackendConfig(options)
  const port = getBackendPort(config.port)
  const target = config.target
  resolvedPort = port
  resolvedTarget = target

  // 第一步：先探活，能复用就绝不再起一个（开发态 dev.mjs 已经起过后端）
  if (await waitForHealth(port, 800)) {
    console.log(`[backend:${target}] 复用已在 ${port} 端口运行的后端服务`)
    return { owned: false, port, target }
  }

  // 第二步：按目标选择启动方式
  if (target === 'java') {
    const jarPath = resolveJavaJar(options.resourcesPath, config, options.isPackaged)
    if (options.isPackaged) {
      if (jarPath) {
        const javaExecutable = resolveJavaExecutable(options.resourcesPath, config)
        child = spawnJavaPackaged(jarPath, javaExecutable, port, options.userDataPath)
      } else {
        console.error(
          `[backend:java] 未找到 ${config.java.jar}；请先执行 pnpm run build:backend:java`,
        )
      }
    } else {
      // 开发态即使有 jar 也优先用 Maven，保证改代码后立即生效
      child = spawnJavaDev(options.projectRoot, config, port)
    }
  } else {
    const exePath = resolvePythonExe(options.resourcesPath, config)
    if (exePath) {
      child = spawnPythonPackaged(exePath, port)
    } else if (options.isPackaged) {
      console.error(
        `[backend:python] 未找到 ${config.python.exe}；请先执行 pnpm run build:backend`,
      )
    } else {
      child = spawnPythonDev(options.projectRoot, config, port)
    }
  }

  // 没成功创建进程：不再等待，让前端页面自行提示连接失败
  if (!child) {
    return { owned: false, port, target }
  }

  ownedBackend = true
  heartbeat = startHeartbeat(child)

  // 启动失败（如命令不存在）：只记录日志，后续健康检查会超时并降级
  child.on('error', (error) => {
    console.error(`[backend:${target}] 启动失败：`, error)
  })
  // 进程退出：清理心跳与句柄，防止后续 stopBackend 操作到已死进程
  child.on('exit', (code, signal) => {
    console.log(
      `[backend:${target}] 进程退出 code=${code ?? 'null'} signal=${signal ?? 'null'}`,
    )
    if (heartbeat) {
      clearInterval(heartbeat)
      heartbeat = null
    }
    child = null
  })

  // 第三步：等待真正就绪；超时不算致命错误
  const timeoutMs = target === 'java'
    ? config.java.startupTimeoutMs
    : config.python.startupTimeoutMs
  if (await waitForHealth(port, timeoutMs)) {
    console.log(`[backend:${target}] 就绪：http://127.0.0.1:${port}`)
  } else {
    console.warn(
      `[backend:${target}] 等待健康检查超时（${timeoutMs}ms），前端页面会提示连接失败`,
    )
  }

  return { owned: true, port, target }
}

/**
 * 关闭后端进程（仅当它是我们自己拉起的，避免误杀开发中的服务）。
 */
export function stopBackend(): void {
  if (heartbeat) {
    clearInterval(heartbeat)
    heartbeat = null
  }
  // owned=false（复用外部服务）或进程已消失时直接返回，不误杀别人的进程
  if (!ownedBackend || !child || child.pid === undefined) return

  const pid = child.pid
  console.log(`[backend:${resolvedTarget}] 关闭进程 ${pid}`)

  if (process.platform === 'win32') {
    // Windows 下需要连同子进程树一起结束（Maven → Java 是父子进程）
    spawn('taskkill', ['/pid', String(pid), '/f', '/t'], { windowsHide: true, shell: true })
  } else {
    child.kill('SIGTERM')
  }

  child = null
  ownedBackend = false
}

/** 读取最近一次 startBackend 实际使用的端口（供日志或调试展示） */
export function getResolvedPort(): number {
  return resolvedPort
}

/** 读取最近一次 startBackend 实际使用的后端类型（供日志或调试展示） */
export function getResolvedTarget(): BackendTarget {
  return resolvedTarget
}
