# app/mcp/config.py
"""MCP server 配置：解析设置里的 JSON 数组，产出可用的连接配置。

为什么把"解析"和"连接"分开：
    解析是纯函数（可单测、不联网），连接要起子进程/发 HTTP（慢且可能失败）。
    混在一起的话，一条写错的配置会让整批 server 都连不上，也说不清是配置问题还是网络问题。

配置形状（设置键 `mcp.servers`，JSON 数组）：

    [
      {
        "name": "filesystem",                 // 必填，唯一；会出现在工具名里
        "transport": "stdio",                 // stdio | sse | streamable_http | websocket
        "command": "npx",                     // stdio 必填
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/work"],
        "env": {"TOKEN": "..."},              // 可选：追加给子进程的环境变量
        "enabled": true,
        "auto_approve": false                 // 可选：该 server 的工具是否免确认
      },
      {
        "name": "remote",
        "transport": "streamable_http",
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer ..."},
        "enabled": true
      }
    ]

安全提醒：`env` / `headers` 里可能有密钥。它们只存在 `app_settings` 与内存里，
**不会**出现在诊断导出包中（见 services/diagnostic_service.py 的脱敏规则）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：数据类与字段默认值
from dataclasses import dataclass, field
# 标准库：正则清洗工具名（LangChain 工具名有字符集限制）
import re
# 标准库：Any 标注原始 JSON 值
from typing import Any

# 受支持的传输方式。与 langchain-mcp-adapters 的 connection 类型一一对应
SUPPORTED_TRANSPORTS: tuple[str, ...] = ("stdio", "sse", "streamable_http", "websocket")

# server 名的允许字符：它会被拼进工具名，太野的字符（空格、点、斜杠）会破坏工具名规则
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# LangChain 工具名上限（langchain_core 的校验规则是 1~64 字符）
_MAX_TOOL_NAME = 64

# 单次调用的默认超时（秒）。MCP server 可能很慢（要起子进程），给得比普通工具宽
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class MCPServerConfig:
    """一个 MCP server 的连接配置（解析后的规范化形态）。"""

    # server 名：唯一标识，也是工具名的第一段
    name: str
    # 传输方式
    transport: str
    # stdio：要执行的命令
    command: str = ""
    # stdio：命令参数
    args: tuple[str, ...] = ()
    # stdio：追加的环境变量（会与当前进程环境合并）
    env: dict[str, str] = field(default_factory=dict)
    # 远程传输：服务地址
    url: str = ""
    # 远程传输：请求头（常放 token）
    headers: dict[str, str] = field(default_factory=dict)
    # 是否启用
    enabled: bool = True
    # 该 server 的工具是否默认免确认（等价于把所有工具加进 mcp.auto_approve_tools）
    auto_approve: bool = False
    # 连接/调用超时（秒）
    timeout: float = DEFAULT_TIMEOUT

    def to_connection(self) -> dict[str, Any]:
        """转成 langchain-mcp-adapters 需要的 connection 字典。

        :return: 可直接放进 `MultiServerMCPClient(connections=...)` 的字典
        """
        if self.transport == "stdio":
            connection: dict[str, Any] = {
                "transport": "stdio",
                "command": self.command,
                "args": list(self.args),
            }
            # env 为空时不要传：传空字典会覆盖掉子进程的完整环境（PATH 就没了）
            if self.env:
                connection["env"] = dict(self.env)
            return connection
        if self.transport == "sse":
            return {
                "transport": "sse",
                "url": self.url,
                "headers": dict(self.headers) or None,
                "timeout": self.timeout,
            }
        if self.transport == "websocket":
            return {"transport": "websocket", "url": self.url}
        # streamable_http 是当前推荐的远程传输（sse 为兼容旧服务保留）
        return {
            "transport": "streamable_http",
            "url": self.url,
            "headers": dict(self.headers) or None,
            "timeout": self.timeout,
        }

    def describe(self) -> str:
        """给界面/日志用的一句话描述（**不含 env/headers**，避免密钥进日志）。

        :return: 如 "stdio: npx -y server-filesystem D:/work"
        """
        if self.transport == "stdio":
            return "stdio: " + " ".join([self.command, *self.args]).strip()
        return f"{self.transport}: {self.url}"

    def to_dict(self) -> dict[str, Any]:
        """转成可下发给前端的形态（同样**不含** env/headers 的值）。

        :return: 脱敏后的字典
        """
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "url": self.url,
            "enabled": self.enabled,
            "auto_approve": self.auto_approve,
            "timeout": self.timeout,
            # 只回显"有没有配"，不回显内容
            "env_keys": sorted(self.env.keys()),
            "header_keys": sorted(self.headers.keys()),
        }


def server_tool_name(server: str, tool: str) -> str:
    """算出 MCP 工具在 LangChain 里的名字：`mcp__<server>__<tool>`。

    为什么统一加 `mcp__` 前缀：
        1. 策略层可以按前缀识别"这是外来的工具"，与内置工具分开放行规则；
        2. 用户一眼能看出这个工具来自哪个 server（确认弹窗里尤其重要）；
        3. 避免与内置工具重名（内置工具都是短名字，不会有 `mcp__` 前缀）。

    :param server: server 名
    :param tool: MCP 侧的原始工具名
    :return: 符合 LangChain 命名规则的工具名
    """
    raw = f"mcp__{server}__{tool}"
    # 非法字符统一换成下划线（MCP 规范没限制工具名字符，但 LangChain 限制）
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    return clean[:_MAX_TOOL_NAME]


def _as_str_dict(raw: Any) -> dict[str, str]:
    """把 JSON 里的对象安全转成 `dict[str, str]`（值统一成字符串）。

    :param raw: 原始值，可能不是字典
    :return: 规范化后的字典；非法输入返回空字典
    """
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k is not None and v is not None}


def parse_servers(raw: Any) -> tuple[list[MCPServerConfig], list[str]]:
    """解析设置里的 server 列表，**逐条容错**：一条写错不影响其它条。

    为什么不整体失败：用户手写 JSON 出错是常态（少个引号、把 args 写成字符串）。
    一条坏配置就让 MCP 整体不可用，排查成本远高于"跳过它并回显原因"。

    :param raw: 设置值（期望是对象数组）
    :return: (可用配置列表, 错误说明列表)
    """
    if raw is None or raw == "":
        return [], []
    if not isinstance(raw, list):
        return [], [f"mcp.servers 必须是数组，收到 {type(raw).__name__}"]

    servers: list[MCPServerConfig] = []
    errors: list[str] = []
    seen: set[str] = set()

    for index, item in enumerate(raw):
        where = f"第 {index + 1} 条"
        if not isinstance(item, dict):
            errors.append(f"{where}：必须是对象，收到 {type(item).__name__}")
            continue

        name = str(item.get("name") or "").strip()
        if not _NAME_RE.match(name):
            errors.append(f"{where}：name 只能包含字母、数字、下划线、连字符（1~32 位），收到 {name!r}")
            continue
        if name in seen:
            # 重名会让工具名冲突、策略互相覆盖，必须拦
            errors.append(f"{where}：name `{name}` 与前面的配置重复")
            continue

        transport = str(item.get("transport") or "stdio").strip().lower()
        # 常见别名归一：http 是 streamable_http 的通俗写法
        if transport == "http":
            transport = "streamable_http"
        if transport not in SUPPORTED_TRANSPORTS:
            errors.append(
                f"{where}：transport 只支持 {'/'.join(SUPPORTED_TRANSPORTS)}，收到 {transport!r}"
            )
            continue

        command = str(item.get("command") or "").strip()
        url = str(item.get("url") or "").strip()
        if transport == "stdio" and not command:
            errors.append(f"{where}：stdio 传输必须提供 command")
            continue
        if transport != "stdio" and not url:
            errors.append(f"{where}：{transport} 传输必须提供 url")
            continue

        raw_args = item.get("args")
        if raw_args is None:
            args: tuple[str, ...] = ()
        elif isinstance(raw_args, list):
            args = tuple(str(a) for a in raw_args)
        else:
            errors.append(f"{where}：args 必须是数组，收到 {type(raw_args).__name__}")
            continue

        try:
            timeout = float(item.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            errors.append(f"{where}：timeout 必须是数字")
            continue
        # 下限 5 秒：再小基本连不上，属于配置错误而不是"我想快速失败"
        timeout = max(5.0, min(timeout, 600.0))

        seen.add(name)
        servers.append(MCPServerConfig(
            name=name,
            transport=transport,
            command=command,
            args=args,
            env=_as_str_dict(item.get("env")),
            url=url,
            headers=_as_str_dict(item.get("headers")),
            enabled=bool(item.get("enabled", True)),
            auto_approve=bool(item.get("auto_approve", False)),
            timeout=timeout,
        ))

    return servers, errors


def parse_auto_approve(raw: Any) -> set[str]:
    """解析「免确认名单」（设置键 `mcp.auto_approve_tools`）。

    支持三种写法（大小写不敏感）：
        `server`        该 server 的全部工具
        `server:*`      同上（显式写法，读起来更清楚）
        `server:tool`   只免这一个工具

    :param raw: 设置值（字符串数组）
    :return: 规范化后的模式集合（小写）
    """
    if not isinstance(raw, list):
        return set()
    result: set[str] = set()
    for item in raw:
        text = str(item or "").strip().lower()
        if not text:
            continue
        result.add(text)
    return result


def is_auto_approved(
    patterns: set[str],
    server: str,
    tool: str,
    *,
    server_default: bool = False,
) -> bool:
    """判断某个 MCP 工具是否命中免确认名单。

    :param patterns: `parse_auto_approve` 的结果
    :param server: server 名
    :param tool: 工具名（MCP 侧的原始名字）
    :param server_default: 该 server 配置里的 `auto_approve` 是否为 true
    :return: 命中返回 True
    """
    if server_default:
        return True
    s = server.strip().lower()
    t = tool.strip().lower()
    # 注意比较的是**原始工具名**，不是 mcp__server__tool——用户在设置里写的是后者更自然
    return s in patterns or f"{s}:*" in patterns or f"{s}:{t}" in patterns
