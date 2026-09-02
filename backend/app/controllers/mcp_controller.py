# app/controllers/mcp_controller.py
"""MCP 管理接口（EXT-2）。

三个端点：
    GET  /api/mcp/servers   列出 server 状态与已发现的工具
    POST /api/mcp/reload    重新连接（改完配置后点「重连」，或连接失败想重试）
    POST /api/mcp/test      试连单条配置（保存前先验证，避免"存了才发现起不来"）

为什么重连要顺带清 LLM 缓存：
    Agent 是编译好的图，工具列表在编译时就固定了。不失效缓存的话，
    重连后新工具要等下次重启后端才会出现在模型眼前。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter 建路由，Body 让单条配置作为请求体直接传入
from fastapi import APIRouter, Body

# 项目内：MCP 连接管理
from app.mcp import client as mcp_client


# 本模块的路由，由 app/api/router.py 挂载（统一前缀 /api）
router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/servers", summary="列出 MCP server 状态与工具清单")
async def list_servers() -> dict:
    """返回各 server 的连接状态、工具数与错误原因。

    :return: {"enabled", "servers", "errors", "tool_count"}
    """
    return mcp_client.snapshot()


@router.post("/reload", summary="重新连接全部 MCP server")
async def reload_servers() -> dict:
    """强制重新发现（不等配置指纹变化）。

    :return: 重载后的快照
    """
    state = mcp_client.refresh(force=True)
    # 项目内：延迟导入，避免控制器导入期就把模型层拉起来
    from app.llm import state as llm_state

    llm_state.invalidate()
    return state


@router.post("/test", summary="试连一个 MCP server 配置（不保存）")
async def test_server(config: dict = Body(..., description="单条 server 配置，结构同 mcp.servers 的元素")) -> dict:
    """验证一条配置能不能连上，返回它会提供哪些工具。

    这个接口**只读**：不写设置、不注册策略、不影响当前正在用的工具集。

    :param config: 单条 server 配置
    :return: {"ok", "tools", "error", "duration_ms"}
    """
    return mcp_client.test_server(config)
