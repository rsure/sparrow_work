"""应用配置：全部支持环境变量覆盖，前缀 APP_。

例如：
    APP_PORT=9000
    APP_CORS_ORIGINS=["http://localhost:5173"]
"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 第三方：pydantic-settings 提供配置基类 BaseSettings（自动从环境变量/.env 读值），
# 以及它的行为配置类 SettingsConfigDict（用来声明变量前缀、.env 文件名等）
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端全部可配置项：取值优先级为「环境变量 APP_xxx」>「.env 文件」>「本文件默认值」。"""

    # 配置读取规则：环境变量统一加 APP_ 前缀、读工作目录下的 .env（UTF-8）、忽略多余变量
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础信息（会被 /api/health 返回）
    # 应用名，展示在 FastAPI 文档标题与前端关于页
    app_name: str = "vue3-electron-fastapi"
    # 服务版本号，随发布递增，前端用于展示与排查问题时对版本
    version: str = "0.1.0"
    # 运行环境标识：development=开发 / production=生产，前端据此决定是否显示调试入口
    env: str = "development"

    # 服务监听地址：Electron 主进程会以 127.0.0.1 拉起后端
    # 监听网卡地址，默认只绑回环地址，保证后端的端口不对局域网暴露
    host: str = "127.0.0.1"
    # 监听端口（1~65535），前端与 Electron 主进程用它拼接口地址
    port: int = 8000

    # API 统一前缀：所有业务路由都挂到它下面（见 main.py 的 include_router 调用）
    api_prefix: str = "/api"

    # 跨域白名单（浏览器 dev 模式下前端跑在 5173，端口被占用时 Vite 会自动换下一个）
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    # 兜底：localhost/127.0.0.1 任意端口都放行，避免 Vite 自动换端口后 CORS 被拒
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1):\d+$"

    # 向量模型（embedding）配置：api_key 等敏感信息必须放在 .env 里，不入库
    # 向量化服务地址（OpenAI 兼容的 /v1 接口），默认指向硅基流动
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    # 调用向量化服务的密钥；留空表示未配置，此时文嵌入会失败、检索不可用
    embedding_api_key: str = ""
    # 使用的向量模型名，默认 BAAI/bge-m3（中英文检索效果较均衡）
    embedding_model: str = "BAAI/bge-m3"
    # 向量维度，必须与所选模型的输出维度一致（bge-m3 为 1024），建 FAISS 索引时使用
    embedding_dim: int = 1024
    # 单次请求最多送多少条文本去向量化，控制请求体大小，避免被服务端拒收
    embedding_batch_size: int = 32
    # 同时对几批文本发起向量化请求，越大越快但越容易触发服务端限流
    embedding_concurrency: int = 4
    # 查询侧指令前缀（部分模型要求给 query 加一段引导文字），留空表示不添加
    embedding_query_prefix: str = ""

    # ---- DeepSeek 对话模型（chat）：Agent 对话用的密钥，与向量化(embedding)分开配置 ----
    # DeepSeek API 密钥；留空表示未配置，此时 Agent 无法启动（rag_agent 导入即报错）
    deepseek_api_key: str = ""

    # ---- 联网工具（第 05 篇）：默认关闭，用户在设置里显式打开后才可用 ----
    # 是否允许 Agent 使用联网工具（搜索 / 抓取网页）；关掉时工具会返回明确的拒绝原因
    allow_web_tools: bool = False
    # 联网抓取的域名白名单；为空表示"除私网/本机地址外都可访问"
    web_allowed_domains: list[str] = []

    # ---- EXT-3 通用 HTTP 工具（http_request）----
    # 是否允许 http_request 使用"会改数据"的方法（POST / PUT / PATCH / DELETE）。
    # 默认关闭：GET/HEAD/OPTIONS 已能覆盖"读接口文档、取 JSON"这类需求，
    # 而写方法可能真的改掉线上数据，必须由用户显式同意后才打开
    allow_http_write_methods: bool = False
    # 单次响应最多读取的字节数（默认 512KB）：防止一次请求把几十 MB 文件读进内存
    http_max_response_bytes: int = 512 * 1024

    # ---- EXT-4 本地 Office 引擎（editor_sdk）----
    # 引擎的鉴权 token；留空表示引擎没开鉴权（桌面壳拉起引擎时写进同一个环境变量）。
    # 端口不在这里配：端口属于"用户可调"的运行时设置，见 office.port（app_settings 表）
    editor_sdk_token: str = ""

# 全局唯一的配置实例：其它模块以 `from app.config import settings` 复用这一份，
# 保证运行时改环境变量只需在一处生效
settings = Settings()
