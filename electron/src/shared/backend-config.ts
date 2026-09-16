/**
 * 后端配置加载器：决定 Electron 启动 Java 还是 Python 后端，以及用什么命令启动。
 *
 * 优先级（高 → 低）：
 *   1. 环境变量 APP_BACKEND_TARGET / APP_PORT；
 *   2. 项目根目录（打包后是 resources/）的 backend.config.json；
 *   3. 本文件里的 DEFAULT_BACKEND_CONFIG。
 *
 * 注意：scripts/dev.mjs 里有一份等价的 JS 配置读取逻辑（Node 脚本不能直接 import .ts）。
 * 修改默认值时请同时改两处，避免 `pnpm run dev` 与 Electron 直接启动行为不一致。
 */
// Node 文件系统（同步版）：启动阶段只读一次配置，同步读取最简单
import { existsSync, readFileSync } from 'node:fs'
// Node 路径工具：把项目根目录、后端目录、wrapper 文件名拼成绝对路径
import { join } from 'node:path'

// 共享常量：后端目标类型、默认目标、配置文件名、默认端口
import {
  BACKEND_CONFIG_FILE,
  BACKEND_PORT,
  DEFAULT_BACKEND_TARGET,
  type BackendTarget,
} from './config'

/** Java 后端的启动配置 */
export interface JavaBackendConfig {
  /** 开发态工作目录（相对项目根目录），默认 backend_java */
  devDir: string
  /**
   * 开发态启动命令模板。
   * 占位符：{mvnw}=Maven Wrapper 或全局 mvn；{port}=实际端口。
   */
  devCommand: string
  /** 打包后 jar 的文件名（位于 resources/backend/ 下），默认 backend-java.jar */
  jar: string
  /** 打包后可选的精简 JRE 目录名（位于 resources/backend/ 下），默认 jre */
  bundledJre: string
  /** 启动后等待健康检查的最长时间（毫秒）；首次 Maven 下载依赖可能较慢 */
  startupTimeoutMs: number
}

/** Python 后端的启动配置 */
export interface PythonBackendConfig {
  /** 开发态工作目录（相对项目根目录），默认 backend */
  devDir: string
  /** 开发态启动命令模板；{port}=实际端口 */
  devCommand: string
  /** 打包后的可执行文件名（位于 resources/backend/ 下），默认 app-backend.exe */
  exe: string
  /** 启动后等待健康检查的最长时间（毫秒） */
  startupTimeoutMs: number
}

/** 完整的后端配置 */
export interface BackendConfig {
  /** 当前目标后端：java / python */
  target: BackendTarget
  /** 后端监听端口；必须与前端 VITE_BACKEND_PROXY 一致 */
  port: number
  /** Java 后端配置 */
  java: JavaBackendConfig
  /** Python 后端配置 */
  python: PythonBackendConfig
}

/** 默认配置：即使 backend.config.json 丢失，应用也能按这些值启动 */
export const DEFAULT_BACKEND_CONFIG: BackendConfig = {
  target: DEFAULT_BACKEND_TARGET,
  port: BACKEND_PORT,
  java: {
    devDir: 'backend_java',
    // {mvnw} 会替换成 Maven Wrapper（优先）或全局 mvn；{port} 替换成实际端口
    devCommand: '{mvnw} -f backend_java/pom.xml spring-boot:run '
      + '-Dspring-boot.run.arguments=--server.port={port}',
    jar: 'backend-java.jar',
    bundledJre: 'jre',
    // Java + Maven 首次启动要下载依赖，给 3 分钟
    startupTimeoutMs: 180_000,
  },
  python: {
    devDir: 'backend',
    devCommand: 'uv run python run.py --port {port}',
    exe: 'app-backend.exe',
    startupTimeoutMs: 30_000,
  },
}

/**
 * 判断任意字符串是否是合法的后端目标。
 *
 * @param value 待判断值
 * @returns 是 java/python 时返回 true
 */
export function isBackendTarget(value: unknown): value is BackendTarget {
  return value === 'java' || value === 'python'
}

/**
 * 读取 backend.config.json，并与默认值、环境变量合并。
 *
 * @param options.projectRoot 项目根目录（开发态）
 * @param options.resourcesPath Electron 的 process.resourcesPath（打包态）
 * @param options.isPackaged 是否已打包；决定配置文件与 jar 的位置
 * @returns 最终生效的后端配置
 */
export function loadBackendConfig(options: {
  projectRoot: string
  resourcesPath: string
  isPackaged: boolean
}): BackendConfig {
  // 打包后配置文件在 resources/ 下；开发态在项目根目录
  const configPath = options.isPackaged
    ? join(options.resourcesPath, BACKEND_CONFIG_FILE)
    : join(options.projectRoot, BACKEND_CONFIG_FILE)

  // 以默认值起步，逐层覆盖
  let config: BackendConfig = {
    ...DEFAULT_BACKEND_CONFIG,
    java: { ...DEFAULT_BACKEND_CONFIG.java },
    python: { ...DEFAULT_BACKEND_CONFIG.python },
  }

  // 配置文件是可选的：不存在或解析失败时只打印警告，继续用默认值，不能让应用起不来
  try {
    if (existsSync(configPath)) {
      const raw = JSON.parse(readFileSync(configPath, 'utf8')) as Partial<BackendConfig>
      config = {
        target: isBackendTarget(raw.target) ? raw.target : config.target,
        port: Number.isFinite(raw.port) && (raw.port ?? 0) > 0 ? Number(raw.port) : config.port,
        java: { ...config.java, ...(raw.java ?? {}) },
        python: { ...config.python, ...(raw.python ?? {}) },
      }
    }
  } catch (error) {
    console.warn(`[backend-config] 读取 ${configPath} 失败，使用默认配置：`, error)
  }

  // 环境变量优先级最高：方便临时切换，不用改文件
  const envTarget = process.env.APP_BACKEND_TARGET ?? process.env.BACKEND_TARGET
  if (isBackendTarget(envTarget)) {
    config.target = envTarget
  }
  const envPort = Number.parseInt(process.env.APP_PORT ?? '', 10)
  if (Number.isFinite(envPort) && envPort > 0) {
    config.port = envPort
  }

  return config
}

/**
 * 解析 Maven 命令：优先使用仓库自带的 Maven Wrapper。
 *
 * @param projectRoot 项目根目录
 * @returns 可直接拼进 shell 命令的 Maven 可执行命令；找不到 wrapper 时退回全局 mvn
 */
export function resolveMavenCommand(projectRoot: string): string {
  const isWindows = process.platform === 'win32'
  const wrapper = join(projectRoot, 'backend_java', isWindows ? 'mvnw.cmd' : 'mvnw')
  if (existsSync(wrapper)) {
    // 路径可能包含空格，必须加引号；Windows 下 shell:true 会正确解析
    return `"${wrapper}"`
  }
  return 'mvn'
}

/**
 * 展开命令模板里的占位符。
 *
 * @param template 命令模板，如 "{mvnw} -f backend_java/pom.xml ... --server.port={port}"
 * @param port 实际端口
 * @param mavenCommand resolveMavenCommand 的返回值
 * @returns 可直接交给 shell 的命令字符串
 */
export function expandBackendCommand(template: string, port: number, mavenCommand: string): string {
  return template
    .replaceAll('{port}', String(port))
    .replaceAll('{mvnw}', mavenCommand)
}

/**
 * 取 Java 开发态启动命令（环境变量可整体覆盖）。
 *
 * @param config 后端配置
 * @param projectRoot 项目根目录
 * @param port 实际端口
 * @returns shell 命令字符串
 */
export function buildJavaDevCommand(
  config: BackendConfig,
  projectRoot: string,
  port: number,
): string {
  // JAVA_BACKEND_CMD 用于用户完全自定义命令（例如指定另一个 JDK 的 mvn）
  const template = process.env.JAVA_BACKEND_CMD?.trim() || config.java.devCommand
  return expandBackendCommand(template, port, resolveMavenCommand(projectRoot))
}

/**
 * 取 Python 开发态启动命令（环境变量可整体覆盖）。
 *
 * @param config 后端配置
 * @param port 实际端口
 * @returns shell 命令字符串
 */
export function buildPythonDevCommand(config: BackendConfig, port: number): string {
  const template = process.env.PYTHON_BACKEND_CMD?.trim() || config.python.devCommand
  // Python 不用 Maven，第三个参数传空串即可
  return expandBackendCommand(template, port, '')
}
