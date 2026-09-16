/**
 * 主进程与渲染进程共享的常量。
 * 渲染层通过 preload 暴露的 desktop.apiPort 读取，不要在前端硬编码同一份值。
 */

/**
 * 后端目标类型：
 *   java   = Spring Boot + LangChain4j + LangGraph4j（默认）
 *   python = FastAPI + LangChain/LangGraph（原实现）
 */
export type BackendTarget = 'java' | 'python'

/** 默认后端目标：没有配置文件、没有环境变量时使用 Java */
export const DEFAULT_BACKEND_TARGET: BackendTarget = 'java'

/** 后端配置文件名：开发态放项目根目录，打包后放 resources/ 下 */
export const BACKEND_CONFIG_FILE = 'backend.config.json'

/** 本地后端端口兜底值：Java/Python 两套实现的默认端口都是 8000 */
export const BACKEND_PORT = 8000

/** 后端健康检查路径：用 /api/health 判断后端是否真的就绪 */
export const BACKEND_HEALTH_PATH = '/api/health'

/**
 * 开发模式下 vite dev server 地址的兜底值。
 * 实际地址以 electron-vite 注入的 process.env.ELECTRON_RENDERER_URL 为准
 * （5173 被占用时 vite 会自动换端口，这个常量只在该环境变量缺失时才用到）。
 */
export const DEV_SERVER_URL = 'http://127.0.0.1:5173'
