# app/services/mcp_settings_defs.py
"""MCP 客户端的设置声明（EXT-2）。

三个键的分工：
    mcp.enabled            总开关。关掉后不连任何 server，MCP 工具整体消失（内置工具不受影响）
    mcp.servers            server 列表（JSON 数组，结构见 app/mcp/config.py 的模块注释）
    mcp.auto_approve_tools 免确认名单（`server` / `server:*` / `server:tool`）

不设"重连开关"这样的键：重连由 `POST /api/mcp/reload` 显式触发。
把它做成设置键的话，写设置的那一刻就要起子进程连接，会让"保存设置"这个动作
卡好几秒，用户会以为界面卡死；而"下次装配 Agent 时惰性重连"既即时又不阻塞保存。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


# MCP 的全部设置声明
MCP_DEFS: list[SettingDef] = [
    SettingDef(
        key="mcp.enabled", label="启用 MCP", kind=SettingKind.BOOL, default=True,
        category="mcp", since="M4",
        description="MCP 总开关：关闭后不再连接任何外部 server，内置工具不受影响",
    ),
    SettingDef(
        key="mcp.servers", label="MCP 服务列表", kind=SettingKind.JSON, default=[],
        category="mcp", since="M4",
        description='MCP server 列表（JSON 数组）。每项形如 '
                    '{"name":"filesystem","transport":"stdio","command":"npx",'
                    '"args":["-y","@modelcontextprotocol/server-filesystem","D:/work"]}；'
                    '远程用 {"transport":"streamable_http","url":"https://...","headers":{...}}',
    ),
    SettingDef(
        key="mcp.auto_approve_tools", label="免确认的 MCP 工具", kind=SettingKind.JSON, default=[],
        category="mcp", since="M4",
        description='免确认名单（JSON 数组）：写 server 名表示该 server 的全部工具免确认，'
                    '写 server:tool 只免单个工具。默认全部需要确认',
    ),
]


def register_mcp_defs() -> None:
    """把 MCP 设置声明注册进全局注册表（幂等）。"""
    register_defs(MCP_DEFS)
