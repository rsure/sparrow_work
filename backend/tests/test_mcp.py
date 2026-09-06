# tests/test_mcp.py
"""EXT-2 MCP 客户端测试。

分两类：
    1. **纯函数**（配置解析、命名、免确认匹配）—— 不联网、不起进程，跑得飞快；
    2. **端到端**（真的起一个 stdio MCP server 子进程）—— 验证"发现 → 包装 → 调用"
       整条链路。这一条最要紧：MCP 的问题几乎都出在连接与序列化上，mock 掉就白测了。

端到端用例会写真实的 app_settings，所以每条都在 finally 里还原，
避免污染开发者本机的配置（与 conftest 清理对话记录同一个思路）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：在同步用例里跑协程（本项目没装 pytest-asyncio）
import asyncio
# 标准库：定位当前解释器，用同一个 Python 起 MCP 子进程
import sys
# 标准库：写临时 server 脚本
from pathlib import Path

# 测试框架
import pytest

# 项目内：被测模块
from app.mcp import client as mcp_client
from app.mcp.config import (
    MCPServerConfig,
    is_auto_approved,
    parse_auto_approve,
    parse_servers,
    server_tool_name,
)
# 项目内：设置读写（用例要临时改 mcp.* 并还原）
from app.services import settings_registry
# 项目内：策略表（验证"外部工具也登记了策略"）
from app.tools.policy import POLICIES, Action, Kind, Level, decide

# 一个最小可用的 MCP server：只暴露一个加法工具。
# 用它而不是 mock，是因为 stdio 握手、JSON Schema 转换、返回值序列化这些
# 恰恰是最容易出错的环节——mock 掉就等于什么都没验证。
_SERVER_SRC = '''
from mcp.server.fastmcp import FastMCP

server = FastMCP("demo")


@server.tool()
def add(a: int, b: int) -> int:
    """把两个整数相加"""
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
'''


@pytest.fixture(autouse=True)
def _ensure_mcp_defs():
    """确保 mcp.* 的设置声明已注册。

    为什么不能只靠模块级 import：其它用例（如 test_settings_registry）会调
    `settings_registry.reset_for_test()` 清空注册表，而用例执行顺序一旦变化，
    "模块导入时注册过"就不再成立。这里每条用例前补一次，与 app 启动顺序一致。
    """
    from app.services.mcp_settings_defs import register_mcp_defs

    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    register_mcp_defs()
    yield


@pytest.fixture()
def restore_mcp_settings(  # noqa: PT004  依赖 _ensure_mcp_defs 的 autouse 顺序
):
    """用例结束后把 mcp.* 还原成用例开始前的样子。

    为什么不用事务回滚：设置是通过 setting_service 直接写库的，
    与测试自己的 Session 不在一个事务里，只能"存旧值 → 写回"。
    """
    keys = ("mcp.enabled", "mcp.servers", "mcp.auto_approve_tools")
    before = {key: settings_registry.get_setting(key) for key in keys}
    yield
    settings_registry.put_settings(before)
    mcp_client.refresh(force=True)
    mcp_client.reset_for_test()


# --------------------------------------------------------------------------- #
# 1. 配置解析（纯函数）
# --------------------------------------------------------------------------- #
def test_parse_stdio_server() -> None:
    """stdio 配置应被完整解析，args 归一成元组，env/headers 不丢。"""
    servers, errors = parse_servers([
        {
            "name": "fs",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "server-filesystem"],
            "env": {"TOKEN": "abc"},
            "timeout": 30,
        }
    ])

    assert errors == []
    assert len(servers) == 1
    server = servers[0]
    assert server.name == "fs"
    assert server.args == ("-y", "server-filesystem")
    assert server.env == {"TOKEN": "abc"}
    assert server.timeout == 30
    # env 必须进 connection，否则"要 token 的 server"永远连不上
    assert server.to_connection()["env"] == {"TOKEN": "abc"}


def test_parse_rejects_bad_entries_but_keeps_good_ones() -> None:
    """一条坏配置只跳过它自己：手写 JSON 出错是常态，不该让整个 MCP 失效。"""
    servers, errors = parse_servers([
        {"name": "ok", "transport": "stdio", "command": "node"},
        {"name": "bad name!", "transport": "stdio", "command": "node"},
        {"name": "no-cmd", "transport": "stdio"},
        {"name": "ok", "transport": "stdio", "command": "node"},   # 重名
        "not-an-object",
    ])

    assert [s.name for s in servers] == ["ok"]
    assert len(errors) == 4
    assert any("name" in e for e in errors)


def test_parse_accepts_http_alias() -> None:
    """`http` 是 `streamable_http` 的通俗写法，必须能直接写。"""
    servers, errors = parse_servers([
        {"name": "remote", "transport": "http", "url": "https://example.com/mcp"}
    ])
    assert errors == []
    assert servers[0].transport == "streamable_http"
    assert servers[0].to_connection()["url"] == "https://example.com/mcp"


def test_server_tool_name_is_langchain_safe() -> None:
    """工具名要同时满足：带 mcp__ 前缀、只含合法字符、不超过 64 字符。"""
    assert server_tool_name("fs", "read_file") == "mcp__fs__read_file"
    # MCP 规范不限制工具名字符，但 LangChain 限制，非法字符必须被替换
    assert server_tool_name("fs", "do.something/now") == "mcp__fs__do_something_now"
    long_name = server_tool_name("s" * 32, "t" * 40)
    assert len(long_name) <= 64


def test_auto_approve_patterns() -> None:
    """三种写法都要能命中，且大小写不敏感。"""
    patterns = parse_auto_approve(["demo", "fs:*", "db:query"])
    assert is_auto_approved(patterns, "demo", "anything")
    assert is_auto_approved(patterns, "FS", "anything")
    assert is_auto_approved(patterns, "db", "query")
    assert not is_auto_approved(patterns, "db", "delete")
    # server 配置里的 auto_approve 等价于"该 server 全部免确认"
    assert is_auto_approved(set(), "x", "y", server_default=True)


def test_empty_config_means_no_tools(restore_mcp_settings) -> None:
    """没配 server 时不应报错，只是没有工具。"""
    settings_registry.put_settings({"mcp.enabled": True, "mcp.servers": []})
    state = mcp_client.refresh(force=True)

    assert state["servers"] == []
    assert state["tool_count"] == 0
    assert mcp_client.get_tools() == []


# --------------------------------------------------------------------------- #
# 2. 端到端（真起 stdio 子进程）
# --------------------------------------------------------------------------- #
def _write_server(tmp_path: Path) -> Path:
    """把最小 server 源码写成脚本文件。

    :param tmp_path: pytest 提供的临时目录
    :return: 脚本路径
    """
    script = tmp_path / "demo_server.py"
    script.write_text(_SERVER_SRC, encoding="utf-8")
    return script


def _configure(tmp_path: Path, *, auto_approve: list[str] | None = None) -> None:
    """把临时 server 配进 mcp.servers 并刷新。

    :param tmp_path: 临时目录（放脚本）
    :param auto_approve: 免确认名单；None 表示全部需要确认
    """
    script = _write_server(tmp_path)
    settings_registry.put_settings({
        "mcp.enabled": True,
        "mcp.servers": [{
            "name": "demo",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(script)],
            "timeout": 40,
        }],
        "mcp.auto_approve_tools": auto_approve or [],
    })
    mcp_client.refresh(force=True)


def test_stdio_server_discovery(tmp_path: Path, restore_mcp_settings) -> None:
    """真的连上一个 stdio server，工具应被发现并登记策略（默认需确认）。"""
    _configure(tmp_path)

    state = mcp_client.refresh(force=True)
    assert state["servers"][0]["ok"] is True, state["servers"][0]["error"]
    assert state["servers"][0]["tool_count"] == 1

    tools = mcp_client.get_tools()
    names = [tool.name for tool in tools]
    assert "mcp__demo__add" in names

    # 外部工具默认 ASK：本程序无法审查它内部做了什么
    decision = decide("mcp__demo__add", Action(tool="mcp__demo__add", kind=Kind.MCP, target="demo/add"))
    assert decision.level is Level.ASK
    assert "MCP" in decision.reason or "demo" in decision.reason


def test_auto_approved_tool_is_allowed_and_callable(
    tmp_path: Path, restore_mcp_settings
) -> None:
    """免确认名单命中后：裁决直接 ALLOW，且真能调到远端工具拿到结果。

    这一条把整条链路串起来了：配置 → 连接 → 包装 → 裁决 → 真实调用 → 输出规整。
    """
    _configure(tmp_path, auto_approve=["demo:add"])

    decision = decide("mcp__demo__add", Action(tool="mcp__demo__add", kind=Kind.MCP, target="demo/add"))
    assert decision.level is Level.ALLOW

    tool = next(t for t in mcp_client.get_tools() if t.name == "mcp__demo__add")
    output = asyncio.run(tool.ainvoke({"a": 2, "b": 3}))

    # 统一前缀让审计能判定成败；3+2 的结果必须原样带回来
    assert output.startswith("OK:"), output
    assert "5" in output


def test_failed_server_does_not_break_others(tmp_path: Path, restore_mcp_settings) -> None:
    """一个 server 起不来只影响它自己：另一个仍可用，且错误原因能回显。"""
    script = _write_server(tmp_path)
    settings_registry.put_settings({
        "mcp.enabled": True,
        "mcp.servers": [
            {
                "name": "demo", "transport": "stdio",
                "command": sys.executable, "args": [str(script)], "timeout": 40,
            },
            {
                # 这个命令不存在，连接必然失败；bounded timeout 保证用例不会挂很久
                "name": "broken", "transport": "stdio",
                "command": "definitely-not-a-real-command-xyz", "timeout": 15,
            },
        ],
        "mcp.auto_approve_tools": [],
    })
    state = mcp_client.refresh(force=True)
    by_name = {item["name"]: item for item in state["servers"]}

    assert by_name["demo"]["ok"] is True
    assert by_name["broken"]["ok"] is False
    assert by_name["broken"]["error"]  # 具体原因（FileNotFoundError 等）要能看见

    # 内置工具 + demo 的工具仍然在，说明失败被隔离住了
    assert [t.name for t in mcp_client.get_tools()] == ["mcp__demo__add"]


def test_disabling_mcp_clears_tools_and_policies(
    tmp_path: Path, restore_mcp_settings
) -> None:
    """关掉总开关后：工具清空、策略也清空（不留"已消失工具"的残影）。"""
    _configure(tmp_path)
    assert "mcp__demo__add" in [t.name for t in mcp_client.get_tools()]

    settings_registry.put_settings({"mcp.enabled": False})
    mcp_client.refresh(force=True)

    assert mcp_client.get_tools() == []
    assert "mcp__demo__add" not in POLICIES


def test_policy_is_replaced_on_reload(tmp_path: Path, restore_mcp_settings) -> None:
    """重连后策略以最新配置为准：ASK → ALLOW（否则用户改了免确认名单却不生效）。"""
    _configure(tmp_path, auto_approve=[])
    assert POLICIES["mcp__demo__add"].default_level is Level.ASK

    settings_registry.put_settings({"mcp.auto_approve_tools": ["demo"]})
    mcp_client.refresh(force=True)
    assert POLICIES["mcp__demo__add"].default_level is Level.ALLOW


def test_describe_never_leaks_secrets() -> None:
    """给界面/日志用的描述里不能出现 env/headers 的值（那里面常放 token）。"""
    server = MCPServerConfig(
        name="fs", transport="stdio", command="npx", args=("-y", "srv"),
        env={"SECRET_TOKEN": "abcdef"},
    )
    assert "abcdef" not in server.describe()
    assert "abcdef" not in str(server.to_dict())
    # 但"配了哪些 key"要回显，否则用户不知道自己到底配没配
    assert server.to_dict()["env_keys"] == ["SECRET_TOKEN"]
