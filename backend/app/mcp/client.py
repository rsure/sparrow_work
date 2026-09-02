# app/mcp/client.py
"""MCP 连接管理：发现工具、缓存、状态上报（EXT-2）。

生命周期（只在三个时刻做"连接"这件事）：
    1. 应用启动后**首次**需要工具时（`get_tools` 第一次被调）；
    2. `POST /api/mcp/reload`（用户改了配置或想手动重试）；
    3. 设置里改了 `mcp.*` —— 下一次读工具时按指纹惰性刷新。

设计取舍：
    - **只做工具发现，不保持长连接**：langchain-mcp-adapters 的工具每次调用会自行
      新建 session，官方就是这个模型。好处是某个 server 挂掉不会污染后续调用；
      代价是单次调用多一次握手（stdio 要起子进程，约几百毫秒）。
    - **发现放在独立线程里跑**：发现要 `await`，而调用方 `get_agent()` 在事件循环里。
      直接 `asyncio.run` 会抛 "already running"；放到新线程里各跑各的循环最稳。
    - **单 server 失败隔离**：一个 server 连不上只影响它自己的工具，
      其余 server 与全部内置工具照常工作（这条有测试钉住）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：异步发现（每个 server 一次 list_tools）
import asyncio
# 标准库：配置指纹（判断要不要重连）
import hashlib
import json
# 标准库：日志
import logging
# 标准库：线程锁 + 独立线程跑发现
import threading
# 标准库：计时（发现耗时、调用耗时）
import time
# 标准库：数据类描述状态
from dataclasses import dataclass, field
# 标准库：Any 标注设置值与工具对象
from typing import Any

# LangChain：工具基类（只用于类型标注）
from langchain_core.tools import BaseTool

# 项目内：配置解析
from app.mcp.config import (
    MCPServerConfig,
    parse_auto_approve,
    parse_servers,
    server_tool_name,
)
# 项目内：工具包装
from app.mcp.tools import wrap_server_tools
# 项目内：策略表清理（server 被删掉后不留残影）
from app.tools.policy import unregister_prefix

# 本模块专用 logger
log = logging.getLogger("mcp")

# MCP 工具的统一前缀：策略层据此识别"这是外部工具"
MCP_TOOL_PREFIX = "mcp__"


@dataclass
class ServerStatus:
    """一个 server 的发现结果（下发给设置页）。"""

    # server 名
    name: str
    # 传输方式的简短描述（不含 env/headers，避免密钥进日志与响应）
    description: str
    # 是否成功拿到工具列表
    ok: bool
    # 工具数
    tool_count: int = 0
    # 工具清单（名字 + 描述），供设置页展示"这个 server 能干什么"
    tools: list[dict[str, str]] = field(default_factory=list)
    # 失败原因（ok=False 时非空）
    error: str = ""
    # 发现耗时（毫秒）
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转成可下发的字典。"""
        return {
            "name": self.name,
            "description": self.description,
            "ok": self.ok,
            "tool_count": self.tool_count,
            "tools": self.tools,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# --------------------------------------------------------------------------- #
# 模块状态
# --------------------------------------------------------------------------- #
# 保护下面所有状态；发现过程本身在锁外进行（可能要几秒，不能阻塞读者）
_lock = threading.RLock()
# server 名 → 已包装好的工具
_tools_by_server: dict[str, list[BaseTool]] = {}
# server 名 → 状态
_status_by_server: dict[str, ServerStatus] = {}
# 配置级错误（JSON 写错、字段缺失），与 server 级错误分开
_config_errors: list[str] = []
# 上次加载时的配置指纹；变了就重连
_signature: tuple | None = None
# 是否已经尝试过加载（即使 0 个 server 也要记住，避免每次都重扫）
_loaded = False


def _read_settings() -> tuple[bool, Any, Any]:
    """读取三个 MCP 设置项；读不到时用最保守的默认值。

    :return: (总开关, servers 原始值, 免确认名单原始值)
    """
    # 项目内：延迟导入，避免模块导入期就依赖数据库
    from app.services.settings_registry import get_setting

    try:
        enabled = bool(get_setting("mcp.enabled"))
    except Exception:
        enabled = False
    if not enabled:
        return False, [], []
    try:
        servers = get_setting("mcp.servers")
    except Exception:
        servers = []
    try:
        patterns = get_setting("mcp.auto_approve_tools")
    except Exception:
        patterns = []
    return True, servers, patterns


def _signature_of(servers: list[MCPServerConfig], patterns: set[str]) -> tuple:
    """算出"影响工具集合"的配置指纹。

    为什么把 env/headers 也算进去（用哈希而不是明文）：
        换了 token 之后必须重连，否则一直用旧凭据；但指纹会进日志/缓存键，
        不能出现明文密钥，所以只放 sha1。

    :param servers: 解析后的配置
    :param patterns: 免确认名单
    :return: 可比较的元组
    """
    items: list[tuple] = []
    for server in servers:
        secret = hashlib.sha1(
            json.dumps(
                {"env": server.env, "headers": server.headers},
                sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:12]
        items.append((
            server.name, server.transport, server.enabled, server.command,
            server.args, server.url, server.auto_approve, server.timeout, secret,
        ))
    return (tuple(items), tuple(sorted(patterns)))


def _run_in_thread(factory, timeout: float) -> Any:
    """在一个新线程里跑协程工厂并等结果。

    为什么不用 `asyncio.run` 直接调：调用方（`get_agent`）本身就在事件循环里，
    直接调会抛 "asyncio.run() cannot be called from a running event loop"。

    线程设为 daemon：万一外部 server 卡死，进程退出时不会被它拖住。

    :param factory: 返回协程的零参函数
    :param timeout: 等待上限（秒）
    :return: 协程的返回值
    :raises TimeoutError: 超时
    :raises Exception: 协程内部抛出的异常
    """
    box: dict[str, Any] = {}

    def target() -> None:
        """线程体：新建事件循环跑完协程，结果/异常放回 box。"""
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001  线程里必须全接住，否则异常会静默丢失
            box["error"] = exc

    thread = threading.Thread(target=target, name="mcp-discover", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"MCP 连接超时（{timeout:.0f}s）")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _discover(server: MCPServerConfig) -> list[BaseTool]:
    """连上 server 并取回它声明的工具（不注册策略、不包装）。

    :param server: server 配置
    :return: 原始 LangChain 工具列表
    :raises Exception: 连接失败/协议错误/超时
    """
    # 项目内：延迟导入——这两个包体积不小，且只在真正用 MCP 时才需要
    from langchain_mcp_adapters.client import MultiServerMCPClient

    async def _run() -> list[BaseTool]:
        """真正的异步发现。"""
        client = MultiServerMCPClient({server.name: server.to_connection()})
        # 每个 server 单独一个 client：一个连不上不会把整批拖垮（get_tools 内部是 gather）
        return await asyncio.wait_for(
            client.get_tools(server_name=server.name),
            timeout=server.timeout,
        )

    # 外层多给 10 秒：内层 wait_for 负责取消协程，外层负责兜住"协程被取消后线程还没退"的情况
    return _run_in_thread(_run, timeout=server.timeout + 10)


def refresh(force: bool = True) -> dict:
    """重新发现全部 server 的工具，刷新缓存与策略表。

    :param force: True=无条件重连；False=配置没变就跳过
    :return: 快照（见 snapshot）
    """
    global _signature, _loaded, _config_errors

    enabled, raw_servers, raw_patterns = _read_settings()
    servers, config_errors = parse_servers(raw_servers)
    patterns = parse_auto_approve(raw_patterns)
    signature = _signature_of(servers, patterns) if enabled else ("disabled",)

    with _lock:
        if not force and _loaded and signature == _signature:
            return snapshot()

    # 配置变了：先清掉旧的 MCP 策略，避免"server 删了但工具还在策略表里"
    unregister_prefix(MCP_TOOL_PREFIX)

    tools_by_server: dict[str, list[BaseTool]] = {}
    status_by_server: dict[str, ServerStatus] = {}

    if not enabled:
        with _lock:
            _tools_by_server.clear()
            _status_by_server.clear()
            _config_errors = []
            _signature = signature
            _loaded = True
        return snapshot()

    for server in servers:
        if not server.enabled:
            status_by_server[server.name] = ServerStatus(
                name=server.name, description=server.describe(), ok=False,
                error="已在配置里停用",
            )
            continue

        started = time.time()
        try:
            raw_tools = _discover(server)
        except Exception as exc:  # noqa: BLE001
            # 单 server 失败只影响它自己：其余 server 与内置工具照常
            message = f"{type(exc).__name__}: {exc}"
            log.warning("MCP server %s 连接失败：%s", server.name, message)
            status_by_server[server.name] = ServerStatus(
                name=server.name, description=server.describe(), ok=False,
                error=message, duration_ms=int((time.time() - started) * 1000),
            )
            continue

        wrapped = wrap_server_tools(server, raw_tools, patterns=patterns)
        tools_by_server[server.name] = wrapped
        status_by_server[server.name] = ServerStatus(
            name=server.name,
            description=server.describe(),
            ok=True,
            tool_count=len(wrapped),
            tools=[
                {
                    "name": tool.name,
                    # 与 wrap_server_tools 里一致：工具名带 server 前缀，用户能对上号
                    "raw_name": tool.name.rsplit("__", 1)[-1],
                    "description": (tool.description or "").split("] ", 1)[-1][:160],
                }
                for tool in wrapped
            ],
            duration_ms=int((time.time() - started) * 1000),
        )
        log.info("MCP server %s 就绪，发现 %d 个工具", server.name, len(wrapped))

    with _lock:
        _tools_by_server.clear()
        _tools_by_server.update(tools_by_server)
        _status_by_server.clear()
        _status_by_server.update(status_by_server)
        _config_errors = config_errors
        _signature = signature
        _loaded = True

    return snapshot()


def ensure_loaded() -> None:
    """确保已加载；配置变了（或从未加载）时重连。"""
    enabled, raw_servers, raw_patterns = _read_settings()
    servers, _ = parse_servers(raw_servers)
    patterns = parse_auto_approve(raw_patterns)
    signature = _signature_of(servers, patterns) if enabled else ("disabled",)

    with _lock:
        if _loaded and signature == _signature:
            return
    refresh(force=True)


def get_tools() -> list[BaseTool]:
    """取全部已就绪的 MCP 工具（惰性加载）。

    :return: 包装后的 LangChain 工具列表；没有配置时返回空列表
    """
    try:
        ensure_loaded()
    except Exception:
        # 发现层出问题不该让整轮对话起不来：退回"没有 MCP 工具"
        log.warning("加载 MCP 工具失败，本轮不使用外部工具", exc_info=True)
        return []
    with _lock:
        return [tool for tools in _tools_by_server.values() for tool in tools]


def tool_names() -> list[str]:
    """当前可用的 MCP 工具名（进 Agent 缓存指纹用）。

    :return: 排序后的工具名列表
    """
    return sorted(tool.name for tool in get_tools())


def snapshot() -> dict:
    """MCP 的可下发状态（设置页用）。

    :return: {enabled, servers, errors, tool_count}
    """
    enabled, _, _ = _read_settings()
    with _lock:
        servers = [status.to_dict() for status in _status_by_server.values()]
        errors = list(_config_errors)
        tool_count = sum(len(tools) for tools in _tools_by_server.values())
    return {
        "enabled": enabled,
        "servers": sorted(servers, key=lambda item: item["name"]),
        "errors": errors,
        "tool_count": tool_count,
    }


def test_server(raw: dict) -> dict:
    """试连一个 server 配置（不写缓存、不注册策略），供设置页"测试连接"按钮用。

    :param raw: 单条 server 配置（与 mcp.servers 里的元素同构）
    :return: {ok, tools, error, duration_ms}
    """
    servers, errors = parse_servers([raw])
    if errors or not servers:
        return {"ok": False, "tools": [], "error": "；".join(errors) or "配置不合法", "duration_ms": 0}

    server = servers[0]
    started = time.time()
    try:
        tools = _discover(server)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "tools": [],
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": int((time.time() - started) * 1000),
        }
    return {
        "ok": True,
        "tools": [
            {"name": server_tool_name(server.name, tool.name), "description": (tool.description or "")[:160]}
            for tool in tools
        ],
        "error": "",
        "duration_ms": int((time.time() - started) * 1000),
    }


def reset_for_test() -> None:
    """清空缓存状态（不删策略表，调用方按需自行 unregister）。"""
    global _signature, _loaded
    with _lock:
        _tools_by_server.clear()
        _status_by_server.clear()
        _config_errors.clear()
        _signature = None
        _loaded = False
