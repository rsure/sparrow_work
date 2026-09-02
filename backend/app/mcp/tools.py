# app/mcp/tools.py
"""把 MCP server 的工具包装成"过权限关卡"的 LangChain 工具（EXT-2）。

为什么不让 MCP 工具直接进 Agent：
    MCP server 是**外部进程**，它提供的工具在本地看来就是黑盒（可能删文件、可能读隐私）。
    如果直接把 `client.get_tools()` 的结果塞给模型，这些工具完全绕过 `tools/policy.py`
    的裁决——这与"所有工具调用都必须过 policy"的结构性约束冲突。

包装后每个 MCP 工具都具备与内置工具完全一致的行为：
    - DENY / 预算熔断 / 用户确认（含"记住本工作区授权"）；
    - 审计落库；
    - EXT-5 输出截断与续读标记。

命名：`mcp__<server>__<tool>`（见 config.server_tool_name），策略层按 `mcp__` 前缀识别。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：计时（写审计与日志时想知道这次外部调用花了多久）
import time
# 标准库：Any 标注工具的返回值
from typing import Any

# LangChain：StructuredTool 是"带参数 schema 的函数工具"，MCP 适配器产出的也是它
from langchain_core.tools import BaseTool, StructuredTool
# LangChain：工具消息类型（MCP 报错时适配器会返回 ToolMessage）
from langchain_core.messages import ToolMessage

# 项目内：MCP 配置（名字映射、免确认判断）
from app.mcp.config import MCPServerConfig, is_auto_approved, server_tool_name
# 项目内：权限模型（Action / Policy / Kind / Level）、裁决与收尾
from app.tools.policy import (
    Action,
    GuardResult,
    Kind,
    Level,
    Policy,
    finalize,
    guard,
    register_dynamic,
)


# 单个参数值在确认弹窗里最多显示多少字符（长文本参数会撑爆弹窗）
_PREVIEW_CHARS = 300


def _preview(args: dict[str, Any]) -> dict[str, Any]:
    """把工具入参整理成确认弹窗能显示的形状（超长值截断）。

    :param args: 原始入参
    :return: 键 → 截断后的字符串/原值
    """
    preview: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > _PREVIEW_CHARS:
            preview[key] = value[:_PREVIEW_CHARS] + "…"
        else:
            preview[key] = value
    return preview


def _flatten_content(value: Any) -> str:
    """把 MCP 工具的返回值压成纯文本。

    适配器的返回形态有四种（见 langchain_mcp_adapters/tools.py）：
        - `(content, artifact)` 元组（response_format="content_and_artifact"）；
        - 纯字符串；
        - LangChain 内容块数组（`[{"type":"text","text":"..."}]`）；
        - ToolMessage（MCP 侧报错时）。

    :param value: 原始返回值
    :return: 纯文本
    """
    if isinstance(value, tuple):
        # 只看 content，artifact 是结构化附加物，模型与前端目前都用不到
        return _flatten_content(value[0]) if value else ""
    if isinstance(value, ToolMessage):
        return _flatten_content(value.content)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # 文本块取 text；其它类型（图片/资源）给出可读占位，别静默丢
                text = item.get("text")
                parts.append(str(text) if text is not None else f"[{item.get('type', 'content')}]")
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return "" if value is None else str(value)


def _normalize_output(value: Any) -> str:
    """把 MCP 返回值规整成 `OK: ...` / `FAIL: ...` 的既有约定。

    为什么要统一前缀：审计层靠 `result.startswith("OK:")` 判定成败（见 policy.finalize）。
    MCP 工具不会主动带这个前缀，这里补上，否则所有 MCP 调用都会被记成失败。

    :param value: MCP 工具返回值
    :return: 带前缀的文本
    """
    is_error = False
    if isinstance(value, tuple) and value:
        # 元组第二个元素是 artifact；MCP 的 isError 在适配器里已经转成异常或 ToolMessage
        pass
    if isinstance(value, ToolMessage):
        is_error = getattr(value, "status", "") == "error"

    text = _flatten_content(value).strip()
    if not text:
        # 空返回也是有效结果（比如"写入成功"类工具），不能当成失败
        return "OK: （该工具没有返回内容）"
    if text.startswith(("OK:", "FAIL:")):
        return text
    return f"{'FAIL' if is_error else 'OK'}: {text}"


def wrap_server_tools(
    server: MCPServerConfig,
    raw_tools: list[BaseTool],
    *,
    patterns: set[str],
) -> list[BaseTool]:
    """把一个 server 的工具全部包装成"过 policy"的版本。

    :param server: server 配置（提供名字与免确认默认值）
    :param raw_tools: 适配器返回的原始工具
    :param patterns: 全局免确认名单（`mcp.auto_approve_tools`）
    :return: 包装后的工具列表
    """
    wrapped: list[BaseTool] = []

    for raw in raw_tools:
        tool_name = server_tool_name(server.name, raw.name)
        approved = is_auto_approved(
            patterns, server.name, raw.name, server_default=server.auto_approve,
        )

        # 免确认 = ALLOW；否则 ASK。两种都用 default_level 显式表达，
        # 避免落到 Kind.MCP 的默认 DENY（那会把 MCP 工具整体禁掉）。
        level = Level.ALLOW if approved else Level.ASK
        policy = Policy(
            tool=tool_name,
            kind=Kind.MCP,
            default_level=level,
            confirm_note=(
                "" if approved
                else f"由外部 MCP server「{server.name}」提供，本程序无法审查它内部做了什么"
            ),
        )
        # 运行时才发现 → 走 register_dynamic（允许覆盖，重连/改配置后以最新为准）
        register_dynamic(policy)

        wrapped.append(_wrap_one(server, raw, tool_name, policy))

    return wrapped


def _wrap_one(
    server: MCPServerConfig,
    raw: BaseTool,
    tool_name: str,
    policy: Policy,
) -> BaseTool:
    """把单个 MCP 工具包装成带裁决的 LangChain 工具。

    :param server: 所属 server
    :param raw: 原始工具（只有 coroutine 实现）
    :param tool_name: 包装后的工具名
    :param policy: 已登记的策略（裁决时按名字查表，这里只为可读性传入）
    :return: 新的 StructuredTool
    """
    # 描述里带上 server 名：模型在多个 server 都有同名工具时能区分来源，
    # 用户在确认弹窗里也能一眼看出这是谁提供的
    description = f"[MCP:{server.name}] {raw.description or raw.name}"
    if not policy.default_level == Level.ALLOW:
        description += "（调用前需要用户确认）"

    async def _call(**kwargs: Any) -> str:
        """实际调用：裁决 → 远程执行 → 收尾（截断 + 审计）。"""
        action = Action(
            tool=tool_name,
            kind=Kind.MCP,
            target=f"{server.name}/{raw.name}",
            preview=_preview(kwargs),
            detail=f"MCP server「{server.name}」准备调用工具 {raw.name}",
        )

        result: GuardResult = guard(tool_name, action)
        if result.blocked is not None:
            return result.blocked

        started = time.time()
        try:
            # 每次调用由适配器新建一个 session（它内部就是这么设计的），
            # 好处是长连接失效不会影响下一次调用，代价是单次调用多一次握手
            value = await raw.ainvoke(kwargs)
        except Exception as exc:  # noqa: BLE001
            # 外部服务什么错都可能抛：协议错、超时、子进程崩溃。
            # 一律转成 FAIL 交给模型（它会换策略或告诉用户），不让整轮对话崩掉
            text = f"FAIL: MCP 工具 {raw.name} 调用失败：{exc}"
        else:
            text = _normalize_output(value)

        elapsed_ms = int((time.time() - started) * 1000)
        if elapsed_ms > 5000:
            # 慢调用单独记一笔：外部 server 卡顿是排查"对话突然变慢"的第一嫌疑
            import logging

            logging.getLogger("mcp").info(
                "MCP 调用较慢：%s/%s 耗时 %dms", server.name, raw.name, elapsed_ms,
            )
        return finalize(tool_name, action, result, text)

    return StructuredTool(
        name=tool_name,
        description=description,
        # 直接复用 MCP 的 inputSchema（JSON Schema 字典，LangChain 会自行转换）
        args_schema=raw.args_schema,
        coroutine=_call,
        # 与内置工具一致：返回值是纯文本，不要 content_and_artifact
        response_format="content",
    )
