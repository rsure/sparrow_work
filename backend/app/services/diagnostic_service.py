# app/services/diagnostic_service.py
"""诊断包导出（OPS-3）：把"复现问题需要的信息"打成一个 zip。

包里有什么、为什么：
    meta.json        版本 / Python 版本 / 平台 / 打包标志 / 数据库迁移版本
                     —— 90% 的"在我机器上不行"都先看这几个
    settings.json    **脱敏后**的全部设置 —— 能看出模型、权限模式、MCP、主题配了什么
    schema.json      表名与列定义 —— 判断"是不是库没迁移"
    logs/app.log     日志尾部（最多 2MB）—— 真正的现场
    trace/recent.jsonl  最近的执行轨迹 —— 看第几步开始不对劲

安全红线（这是本模块最要紧的部分）：
    - 任何密钥都不得出现在包里。做法是两层：
        1. 按**键名**脱敏（api_key / token / secret / password / authorization…）；
        2. `env` / `headers` 这类"容器键"下的值一律替换（因为里面的键名是用户自定义的，
           叫 `X-Foo` 也可能是个 token，没法靠名字判断）。
    - 最后再对整个 JSON 文本做一次 `sk-xxx` 形态的兜底擦除。
    - `secrets.*` 本来就进不了 get_all_settings()，所以不存在"忘了过滤"的路径。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：把 zip 写在内存里，避免在用户磁盘上留临时文件
import io
# 标准库：JSON 序列化
import json
# 标准库：日志
import logging
# 标准库：平台与版本信息
import platform
import sys
# 标准库：时间戳（包名与 meta 里的导出时间）
from datetime import datetime
# 标准库：正则（脱敏兜底）
import re
# 标准库：zip 打包
import zipfile
# 标准库：路径
from pathlib import Path
# 标准库：Any 标注
from typing import Any

# SQLAlchemy：读表结构
from sqlalchemy import inspect

# 项目内：数据库引擎与当前迁移版本
from app.db.db_config import _current_revision, engine
# 项目内：日志文件位置
from app.core.paths import log_file
# 项目内：配置（版本号等）
from app.config import settings as app_settings
# 项目内：设置读取
from app.services import settings_registry

# 本模块专用 logger
log = logging.getLogger("diagnostic")

# 键名里出现这些词就按密钥处理（大小写不敏感）
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?key|token|secret|password|passwd|credential|authorization|bearer)",
    re.I,
)

# 这些键下面的**值**一律脱敏：容器里的键名是用户自定义的，靠名字判断不可靠
_SECRET_CONTAINER_KEYS = frozenset({"env", "headers"})

# 兜底擦除：形如 sk-abcdefghijklmnop 的长串（OpenAI / DeepSeek 等常见形态）
_SECRET_VALUE_RE = re.compile(r"\b(sk|pk|ghp|xoxb)-[A-Za-z0-9_\-]{12,}")

# 日志最多打包多少字节（2MB：够看最近的现场，又不至于让包太大）
_LOG_TAIL_BYTES = 2 * 1024 * 1024

# 打包多少条轨迹
_TRACE_LIMIT = 2000

# 脱敏后的占位符：写清楚"这里被处理过"，避免用户以为配置丢了
_REDACTED = "***REDACTED***"


def redact(value: Any, key: str = "") -> Any:
    """递归脱敏一个设置值。

    :param value: 原始值（任意 JSON 结构）
    :param key: 当前所在的键名（用于判断"这个值是不是密钥"）
    :return: 脱敏后的副本
    """
    if key in _SECRET_CONTAINER_KEYS and isinstance(value, dict):
        # 容器键：保留键名（用户要能看出"我配了哪些 env"），值全部抹掉
        return {str(k): _REDACTED for k in value}
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, key) for item in value]
    if isinstance(value, str) and _SECRET_KEY_RE.search(key):
        return _REDACTED
    return value


def _settings_snapshot() -> dict[str, Any]:
    """取全部非密钥设置并脱敏。

    :return: 脱敏后的设置字典
    """
    values = settings_registry.get_all_settings()
    return {key: redact(value, key) for key, value in values.items()}


def _schema_snapshot() -> dict[str, list[dict[str, Any]]]:
    """读出库里的表与列定义。

    :return: {表名: [{name, type, nullable}]}
    """
    inspector = inspect(engine)
    result: dict[str, list[dict[str, Any]]] = {}
    for table in inspector.get_table_names():
        result[table] = [
            {
                "name": column.get("name"),
                "type": str(column.get("type")),
                "nullable": bool(column.get("nullable", True)),
            }
            for column in inspector.get_columns(table)
        ]
    return result


def _meta() -> dict[str, Any]:
    """版本与环境信息。

    :return: 字典
    """
    # 项目内：延迟导入，避免与 constants 的初始化顺序纠缠
    from app.constants import IS_PACKAGED

    return {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": app_settings.app_name,
        "app_version": app_settings.version,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packaged": bool(IS_PACKAGED),
        "db_revision": _current_revision(),
        "log_file": str(log_file()),
    }


def _log_tail() -> bytes:
    """读日志文件的尾部（没有日志文件时返回空字节）。

    :return: 日志尾部内容
    """
    path = Path(log_file())
    if not path.exists():
        return b""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > _LOG_TAIL_BYTES:
                handle.seek(size - _LOG_TAIL_BYTES)
            return handle.read()
    except OSError as exc:
        return f"（读取日志失败：{exc}）".encode("utf-8")


def _trace_lines() -> str:
    """把最近的轨迹转成 JSONL（一行一条，便于 grep）。

    :return: JSONL 文本；没有轨迹时返回空串
    """
    # 项目内：延迟导入，避免诊断模块在导入期就依赖轨迹服务
    from app.services import trace_service

    try:
        events = trace_service.recent(limit=_TRACE_LIMIT)
    except Exception as exc:
        return json.dumps({"error": f"读取轨迹失败：{exc}"}, ensure_ascii=False) + "\n"
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _scrub(text: str) -> str:
    """对最终文本做密钥形态的兜底擦除（第二道防线）。

    为什么在"已经按键名脱敏"之后还要做一次：
        `llm.custom_providers` 之类是用户自由填写的 JSON，键名可能叫 `k`；
        而 `mcp.servers[].args` 里也可能直接写 `--token=sk-xxx`。
        按键名判断漏掉的，这一层能兜住。

    :param text: 原始文本
    :return: 擦除后的文本
    """
    return _SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}-{_REDACTED}", text)


def build_package() -> tuple[str, bytes]:
    """生成诊断包。

    :return: (建议文件名, zip 字节内容)
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"diagnostic-{stamp}.zip"

    meta_text = _scrub(json.dumps(_meta(), ensure_ascii=False, indent=2))
    settings_text = _scrub(json.dumps(_settings_snapshot(), ensure_ascii=False, indent=2))
    schema_text = _scrub(json.dumps(_schema_snapshot(), ensure_ascii=False, indent=2))
    trace_text = _scrub(_trace_lines())

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meta.json", meta_text)
        archive.writestr("settings.json", settings_text)
        archive.writestr("schema.json", schema_text)
        archive.writestr("trace/recent.jsonl", trace_text)
        archive.writestr("logs/app.log", _log_tail())
        archive.writestr(
            "README.txt",
            "本诊断包用于排查问题，已按键名脱敏并做过密钥形态擦除，但仍建议仅在内部流转。\n"
            "meta.json=版本与环境 · settings.json=脱敏配置 · schema.json=库结构 · "
            "trace/recent.jsonl=最近的执行轨迹 · logs/app.log=日志尾部\n",
        )

    payload = buffer.getvalue()
    log.info("诊断包已生成：%s（%.1f KB）", filename, len(payload) / 1024)
    return filename, payload


def summary() -> dict[str, Any]:
    """诊断概要（前端「诊断」页展示用，不含任何敏感内容）。

    :return: {version, python, platform, db_revision, log_file, log_bytes, trace_events, tables}
    """
    path = Path(log_file())
    try:
        log_bytes = path.stat().st_size if path.exists() else 0
    except OSError:
        log_bytes = 0

    # 项目内：延迟导入，避免循环依赖
    from app.services import trace_service

    try:
        trace_events = len(trace_service.recent(limit=_TRACE_LIMIT))
    except Exception:
        trace_events = 0

    meta = _meta()
    return {
        "version": meta["app_version"],
        "python": meta["python"],
        "platform": meta["platform"],
        "packaged": meta["packaged"],
        "db_revision": meta["db_revision"],
        "log_file": meta["log_file"],
        "log_bytes": log_bytes,
        "trace_events": trace_events,
        "tables": len(_schema_snapshot()),
    }
