"""FastAPI 应用工厂：装配路由、中间件、文档。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库：日志（启动清理也要留痕）
import logging
# 标准库：把"退出清理"写成异步上下文管理器，交给 FastAPI 的 lifespan 参数
from contextlib import asynccontextmanager

# Web 框架：FastAPI 用于创建应用实例；Request 供全局异常处理器读取请求上下文
from fastapi import FastAPI, Request
# 开发态跨域中间件：让 Vite 起的 5173 页面能直接请求 8000 端口的后端
from fastapi.middleware.cors import CORSMiddleware
# 直接返回 JSON 的响应类：异常处理器用它拼出统一的错误结构
from fastapi.responses import JSONResponse

# 项目内：聚合后的总路由，一次性挂到应用上（各 controller 的 router 已在其中注册）
from app.api.router import api_router
# 项目内：全局配置，提供应用名/版本/CORS 白名单/接口前缀
from app.config import settings
# 项目内：是否运行在 Electron 打包环境，决定 CORS 用「全放开」还是「白名单」
from app.constants import IS_PACKAGED
# 项目内：建表入口与迁移入口，应用启动时确保 SQLite 表结构已存在且为最新
from app.db.db_config import init_db, run_migrations
# 项目内：业务异常类型，注册成全局处理器后会被自动转成 JSON 错误响应
from app.schemas.scan_exception import ScanException
# 项目内：设置声明式注册表与其内置声明；启动时把内置声明注册进去，
# 之后各模块再通过 register_defs() 追加自己的声明（见 doc/27-设置体系规范.md）
from app.services.settings_registry import (
    BUILTIN_DEFS,
    get_setting,
    register_defs,
    subscribe,
)
# 项目内：工作区这一层的设置声明（workspaces.list / workspaces.active_id）与其白名单联动订阅；
# 导入并调用 register_workspace_defs() 即完成注册（ARCH-3）
from app.services.workspace_settings_defs import register_workspace_defs
# 项目内：界面层设置声明（theme.* 主题定制 / input.* 输入快捷键，M2）；
# 前端设置页由 meta 驱动，注册后「外观」「输入」分区自动出现，无需改前端代码
from app.services.ui_settings_defs import register_ui_defs
# 项目内：权限三档与预算熔断的设置声明（UX-7 / UX-9）；与 policy.py 同批落地
from app.services.policy_settings_defs import register_policy_defs
# 项目内：技能系统（EXT-1）的设置声明与注册表
from app.services.skill_settings_defs import register_skill_defs
# 项目内：MCP 客户端（EXT-2）的设置声明
from app.services.mcp_settings_defs import register_mcp_defs
# 项目内：运维设置声明（OPS-3 / OPS-6）：日志级别与轨迹保留天数
from app.services.ops_settings_defs import register_ops_defs
# 项目内：复杂任务拆分（TASK）的设置声明
from app.services.task_settings_defs import register_task_defs
# 项目内：工作空间记忆（MEM）的设置声明
from app.services.memory_settings_defs import register_memory_defs
# 项目内：本地 Office 引擎解析（EXT-4）的设置声明：office.enabled / port / timeout_ms 等
from app.services.office_settings_defs import register_office_defs
# 项目内：日志落盘配置（OPS-3）——打包后没有控制台，日志文件是唯一现场
from app.core.logging_setup import setup_logging


# 本模块专用 logger
log = logging.getLogger("app")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期钩子：退出时关闭异步检查点的数据库连接。

    为什么必须关：aiosqlite 的连接由一个**非守护线程**驱动，不关闭的话
    uvicorn 收到 Ctrl+C 后进程会一直挂着退不掉。

    :param _app: FastAPI 应用实例（本函数用不到）
    """
    # 延迟导入：避免 main 在导入期就把 agent / 工具链全部拉起来
    from app.agents import rag_agent

    # 启动即建立检查点连接并建表：adelete_thread 不会自动 setup，
    # 先初始化才能保证"还没聊过就清空会话"这类操作不会报 no active connection
    await rag_agent.init_checkpointer()
    yield
    # 关闭 aiosqlite 连接，避免它的非守护线程拖住 uvicorn 退出
    await rag_agent.close_checkpointer()


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用：建表、注册异常处理器与 CORS 中间件、挂载全部路由。

    在 main.py 末尾调用一次；测试里也可以重复调用它来拿到互不干扰的应用实例。
    """
    # 启动即建表（已存在的表会跳过），避免首次运行因缺表而报错
    init_db()

    # 再跑一遍 Alembic 迁移：init_db 只保证"表在"，迁移才保证"字段与实体声明一致"。
    # 存量库会被自动 stamp 到基线，不会重复建表；失败只记日志、不阻断启动。
    run_migrations()

    # 注册内置设置声明：必须在建表之后（部分模块声明的默认值会读库），
    # 且必须在挂载路由之前（GET /api/settings/meta 要能立刻读到完整 schema）。
    # 各模块可在自己的包被导入时再调register_defs() 追加声明，覆盖同名键亦不会报错。
    register_defs(BUILTIN_DEFS)
    # 注册工作区（ARCH-3）的设置声明，并按当前 active 工作区同步一次工具层白名单
    register_workspace_defs()
    # 注册界面层（M2）的设置声明：theme.* 与 input.*，设置页由 meta 驱动自动出现
    register_ui_defs()
    # 注册权限与预算（UX-7 / UX-9）的设置声明：permission.mode 与 cost.*
    register_policy_defs()
    # 注册技能（EXT-1）的设置声明，并扫描一次技能目录（失败不影响启动）
    register_skill_defs()
    # 注册 MCP（EXT-2）的设置声明。这里**不**连接 server：
    # 连接要起子进程/发 HTTP，会让启动变慢，改为"首次装配 Agent 时惰性连接"
    register_mcp_defs()
    # 注册运维（OPS-3 / OPS-6）的设置声明
    register_ops_defs()
    # 注册复杂任务拆分（TASK）的设置声明
    register_task_defs()
    # 注册工作空间记忆（MEM）的设置声明
    register_memory_defs()
    # 注册本地 Office 引擎（EXT-4）的设置声明：office.* 五个键
    register_office_defs()

    # 日志落盘：必须在设置注册之后（要读 ops.log_level），
    # 且尽可能早——启动过程中的问题也应该被记下来
    setup_logging()

    # ---- OPS-6：按 trace.keep_days 清理过期轨迹 ----
    # 放在启动时而不是每次写入后：清理是低频动作，没必要给每轮对话加一次 DELETE
    try:
        # 项目内：延迟导入，避免轨迹表尚未建好时就被 import 连带拖慢启动
        from app.services import trace_service

        removed = trace_service.purge_older_than(int(get_setting("trace.keep_days")))
        if removed:
            log.info("启动清理：删除 %d 条过期轨迹", removed)
    except Exception:
        # 清理失败不影响启动：大不了表大一点
        log.warning("清理过期轨迹失败", exc_info=True)

    # 用户改了日志级别后立即生效，不用重启后端
    subscribe("ops.", lambda _event: setup_logging())
    try:
        from app.skills import registry as skill_registry

        skill_registry.reload(force=True)
    except Exception:
        # 技能扫不到只是"没有可用技能"，不该让整个后端起不来
        pass

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Vue3 + Electron 桌面应用的本地后端服务",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        # 退出时关闭异步检查点连接，避免 aiosqlite 的非守护线程拖住进程
        lifespan=_lifespan,
    )

    @app.exception_handler(ScanException)
    async def scan_exception_handler(request: Request, exc: ScanException) -> JSONResponse:
        """把业务异常 ScanException 统一转成 JSON 响应。

        场景：controller 里 `raise ScanException(404, "任务不存在")` 时，
        由这里接住并以异常自带的 code 作为 HTTP 状态码返回，前端只需认一种错误结构。
        """
        return JSONResponse(
            status_code=exc.code,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    # 打包运行时前端是 file:// 页面（Origin: null），直接放开；
    # 开发时按 settings.cors_origins 白名单 + localhost 任意端口的正则兜底放开
    # （Vite 遇端口占用会自动换下一个，白名单列不全）。
    if IS_PACKAGED:
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_origin_regex=settings.cors_origin_regex,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 统一挂载：所有接口最终路径都是 settings.api_prefix + 各 controller 自己的前缀
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


# 模块级应用实例：`uvicorn app.main:app` 与 Electron 主进程都从这里取应用
app = create_app()
