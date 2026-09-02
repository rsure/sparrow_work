# app/mcp/__init__.py
"""MCP（Model Context Protocol）客户端（EXT-2）。

对外的三个入口：
    get_tools()    取当前可用的 MCP 工具（已过权限包装，可直接并进 Agent）
    refresh()      重新发现（改了配置后调它）
    snapshot()     状态快照（设置页展示"连没连上、有哪些工具"）

配置在设置键 `mcp.*` 里（见 services/mcp_settings_defs.py），不另建配置文件——
与 EXT-1 的技能、UX-7 的权限一样，走"声明即生效"的统一路径。
"""
