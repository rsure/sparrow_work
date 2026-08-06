# app/core/logging_setup.py
"""日志落盘：控制台 + 滚动文件（OPS-3）。

为什么必须落文件：
    打包后的桌面应用没有控制台可看。用户说"刚才崩了"，我们能拿到的只有日志文件。
    而且 MCP 子进程、长任务、SSE 异常这些信息只在日志里，不进数据库。

滚动策略：单文件 5MB × 保留 5 份（≈25MB 上限）。
    桌面应用不该在用户磁盘上无界增长；5MB 足够容纳几万行，够定位问题。

日志目录：`app/core/paths.logs_dir()`（用户数据目录），不是仓库目录——
    打包后程序目录可能只读，往那里写会直接失败。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：日志核心
import logging
# 标准库：按大小滚动的文件处理器
from logging.handlers import RotatingFileHandler

# 项目内：日志文件位置
from app.core.paths import log_file

# 滚动参数：单文件上限与保留份数
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

# 日志格式：时间 级别 [模块名] 消息。
# 不用行号：桌面端排查主要看"哪个模块做了什么"，行号反而让行变长、不好扫
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 处理器上打的标记：重复调用 setup_logging 时靠它识别"这个 handler 是我们加的"
_HANDLER_MARK = "_app_file_handler"

# 是否已经配置过（避免 create_app 被多次调用时叠加 handler）
_configured = False


def _level_from_setting() -> int:
    """从设置里读日志级别（`ops.log_level`），读不到用 INFO。

    :return: logging 的级别常量
    """
    try:
        # 项目内：延迟导入，避免导入期依赖数据库
        from app.services.settings_registry import get_setting

        name = str(get_setting("ops.log_level") or "info").strip().upper()
    except Exception:
        name = "INFO"
    return getattr(logging, name, logging.INFO)


def setup_logging(level: int | None = None) -> None:
    """配置根 logger：控制台 + 滚动文件（幂等）。

    为什么用根 logger：项目里各模块都是 `logging.getLogger("chat")` 这种写法，
    挂到根上就能一处生效，不需要每个模块自己配 handler。

    :param level: 显式指定级别；None 表示读设置
    """
    global _configured

    root = logging.getLogger()
    effective = level if level is not None else _level_from_setting()

    if _configured:
        # 已经配过：只更新级别（用户改了 ops.log_level 后不必重启）
        root.setLevel(effective)
        for handler in root.handlers:
            if getattr(handler, _HANDLER_MARK, False):
                handler.setLevel(effective)
        return

    root.setLevel(effective)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # ---- 文件 handler：真正要留存的那一份 ----
    try:
        file_handler = RotatingFileHandler(
            log_file(), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(effective)
        setattr(file_handler, _HANDLER_MARK, True)
        root.addHandler(file_handler)
    except OSError as exc:
        # 磁盘只读/权限不足时不能让后端起不来：只是没有文件日志而已
        root.warning("无法写入日志文件 %s：%s", log_file(), exc)

    # ---- 控制台 handler：开发时看终端 ----
    # 只在根 logger 还没有 StreamHandler 时添加，避免与 uvicorn 的 handler 重复打印
    if not any(
        isinstance(h, logging.StreamHandler) and not getattr(h, _HANDLER_MARK, False)
        for h in root.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(effective)
        root.addHandler(stream_handler)

    # 第三方库降噪：http 客户端与 MCP 的调试日志量极大，正常只留 WARNING
    for noisy in ("httpx", "httpcore", "urllib3", "mcp", "langchain_mcp_adapters"):
        logging.getLogger(noisy).setLevel(max(effective, logging.WARNING))

    _configured = True


def reset_for_test() -> None:
    """摘掉本模块加的 handler（用例隔离用）。"""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    _configured = False
