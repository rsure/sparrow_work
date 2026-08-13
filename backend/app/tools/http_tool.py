# app/tools/http_tool.py
"""
通用 HTTP 工具：http_request（调接口、取 JSON、发 POST）。

与 web_fetch 的分工（很容易混，先记住）：
    web_fetch     只 GET，抓的是**给人看的网页**：会做 HTML→纯文本，丢掉标签结构；
    http_request  可以换方法、加请求头、发请求体，抓的是**给程序用的响应**：
                  原样保留 JSON / XML / 纯文本，不做 HTML 清理（除非对方就是返回 HTML）。

安全上沿用三条纪律（与 web_tool 一致，实现共用 app/tools/net_guard.py）：
    1. 默认关闭：连"能不能联网"都归 settings.allow_web_tools 管，没开时工具直接返回拒绝原因；
    2. 只允许 http/https，并拒绝本机/内网地址（防 SSRF），跳转后的最终地址再校验一次；
    3. 响应体一律当**外部不可信数据**：剥控制字符、截断、加围栏并声明"这不是给你的指令"。

额外一条（本工具独有）：
    4. POST / PUT / PATCH / DELETE 这类"会改数据"的方法默认关闭，
       要用户在 .env 里显式设置 APP_ALLOW_HTTP_WRITE_METHODS=true 才放行。
       理由：GET 最坏情况是把脏数据读进上下文（有围栏兜着），
       而写方法可能真的把线上数据改掉，这不是靠提示词能兜住的。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：regular expression 用来清理响应头里的换行（防响应头注入进日志/上下文）
import re

# 第三方：HTTP 客户端（与 web_tool 保持一致，避免再引入一个 http 库）
import requests

# LangChain 工具装饰器
from langchain_core.tools import tool

# 项目内：全局配置（联网开关、写方法开关、响应体上限）
from app.config import settings
# 项目内：联网护栏（URL/SSRF 校验 + 外部内容围栏），与 web_fetch 共用同一份实现
from app.tools.net_guard import as_untrusted, check_url
# 项目内：权限模型
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：统一返回格式
from app.tools.tool_utils import fmt

# 单次请求超时（单位：秒）；联网工具绝不能把一轮对话拖住
_HTTP_TIMEOUT = 15

# 允许的超时上限（单位：秒）：模型不该让用户等好几分钟
_MAX_TIMEOUT = 60

# "只读"方法：任何时候都允许（仍然要过联网开关与 SSRF 校验）
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# "会改数据"的方法：默认关闭，需要 settings.allow_http_write_methods=True
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 不允许模型自己设置的请求头：Host 会改变请求路由，Content-Length 由 requests 自己算，
# 让模型手动指定只会得到 400 或把请求搞坏
_BLOCKED_HEADERS = frozenset({"host", "content-length"})

# 提交给确认弹窗的响应体预览长度（字符）：只要能让用户认出"访问了什么"就够
_PREVIEW_CHARS = 200

# 响应头里只保留这几个"对理解响应有用"的项，其余（Set-Cookie 等）不进上下文
_KEEP_HEADERS = ("content-type", "content-length", "location", "server")

# 响应头值里可能夹带换行，先清掉再拼进文本（否则会伪造出假的"下一行"）
_HEADER_NEWLINE_RE = re.compile(r"[\r\n]+")


def build_http_action(url: str, method: str = "GET", payload: str = "") -> Action:
    """把一次 http_request 调用翻译成待裁决的操作。

    只声明"要访问哪个地址、用什么方法"，请求体只截一小段给确认弹窗看——
    把整个 body 塞进弹窗反而让用户看不清重点。

    :param url: 目标地址
    :param method: HTTP 方法（调用方已归一化为大写）
    :param payload: 请求体原文（只用于弹窗预览，不会整段展示）
    :return: 供裁决的 Action
    """
    preview: dict[str, object] = {"method": method, "url": url}
    if payload:
        # 只截前 _PREVIEW_CHARS 个字符：足够认出"要改什么"，又不至于把弹窗撑爆
        preview["body"] = payload[:_PREVIEW_CHARS]
    return Action(
        tool="http_request",
        kind=Kind.NET,
        target=url,
        preview=preview,
        detail=f"AI 将发起 HTTP 请求：{method} {url}",
    )


def _normalize_method(raw: str) -> str:
    """把用户/模型给的方法名归一化并校验。

    :param raw: 原始方法名（大小写随意，允许前后空格）
    :return: 大写方法名
    :raises ValueError: 方法不在支持列表里
    """
    method = (raw or "GET").strip().upper()
    if method not in _READ_METHODS and method not in _WRITE_METHODS:
        allowed = "、".join(sorted(_READ_METHODS | _WRITE_METHODS))
        raise ValueError(f"不支持的 HTTP 方法 {raw}（可用：{allowed}）")
    return method


def _clean_headers(raw: dict[str, str] | None) -> dict[str, str]:
    """过滤模型给的请求头：去掉被禁止的键，并把值转成单行字符串。

    :param raw: 模型传入的请求头字典
    :return: 可以真正发出去的请求头
    """
    cleaned: dict[str, str] = {}
    for key, value in (raw or {}).items():
        name = str(key).strip()
        if not name or name.lower() in _BLOCKED_HEADERS:
            continue
        cleaned[name] = _HEADER_NEWLINE_RE.sub(" ", str(value))
    return cleaned


def _read_body(resp: requests.Response, limit: int) -> tuple[str, bool]:
    """按上限读取响应体并解码成文本。

    :param resp: requests 的流式响应对象
    :param limit: 最多读取的字节数
    :return: (文本, 是否被字节上限截断)
    """
    chunks: list[bytes] = []
    size = 0
    truncated = False
    for chunk in resp.iter_content(chunk_size=16 * 1024):
        if not chunk:
            continue
        remaining = limit - size
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            # 这一块只保留前 remaining 字节，剩下的必须丢掉 —— 丢掉就是截断，
            # 这里直接 break 并标记，不能等到"下一块"才发现超限（否则最后一块
            # 刚好跨过上限时 truncated 会漏报，等于静默丢了数据）。
            chunks.append(chunk[:remaining])
            size += remaining
            truncated = True
            break
        chunks.append(chunk)
        size += len(chunk)
    data = b"".join(chunks)

    # 编码：先用响应头声明的编码；没声明就退回 apparent_encoding（中文站点常见 GB18030）
    encoding = resp.encoding or resp.apparent_encoding or "utf-8"
    try:
        return data.decode(encoding, errors="replace"), truncated
    except LookupError:
        # 服务器给了个 Python 不认识的编码名：退回 utf-8，宁可显示成替换字符也不报错
        return data.decode("utf-8", errors="replace"), truncated


@tool
@make_tool(
    POLICIES["http_request"],
    lambda url, method="GET", headers=None, payload="", timeout=_HTTP_TIMEOUT:
        build_http_action(url, _normalize_method(method), payload),
)
def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: str = "",
    timeout: int = _HTTP_TIMEOUT,
) -> str:
    """发一次 HTTP 请求，返回状态码、关键响应头与响应体（需要用户先开启联网能力）。

    适用：读接口文档里的 JSON、调内部服务的只读接口、确认某个 URL 是否可访问。
    不适用：读普通网页正文（用 web_fetch，它会把 HTML 清成纯文本）、
            下载大文件（有响应体上限）、访问本机/内网地址（会被拒绝）。

    :param url: 完整地址，必须以 http:// 或 https:// 开头
    :param method: HTTP 方法，默认 GET；POST/PUT/PATCH/DELETE 需要用户先开启写方法开关
    :param headers: 额外的请求头（不要传 Host / Content-Length，会被忽略）
    :param payload: 请求体（只在写方法下有意义），按 UTF-8 原样发送
    :param timeout: 超时秒数，1~60，默认 15
    :return: "OK: 状态行 + 响应头 + 带围栏的响应体" 或 "FAIL: 原因"
    """
    try:
        http_method = _normalize_method(method)
        # 写方法要用户显式打开：默认关闭时给一条能照着做的提示，而不是干巴巴的 "被拒绝"
        if http_method in _WRITE_METHODS and not settings.allow_http_write_methods:
            return fmt(
                False,
                f"{http_method} 会改动服务端数据，默认关闭。"
                f"开启方法：在后端 .env 里设置 APP_ALLOW_HTTP_WRITE_METHODS=true 后重启后端",
            )
        # GET/HEAD 带请求体在 HTTP 里没有意义，requests 也会静默忽略，不如直接说清
        if payload and http_method in _READ_METHODS:
            return fmt(False, f"{http_method} 不支持请求体；要提交数据请改用 POST")

        reason = check_url(url)
        if reason:
            return fmt(False, reason)

        # 超时夹在 1~60 秒：模型经常随手写 timeout=1（太短）或 600（把一轮对话拖死）
        seconds = max(1, min(_MAX_TIMEOUT, int(timeout)))
        limit = settings.http_max_response_bytes

        resp = requests.request(
            http_method,
            url,
            headers=_clean_headers(headers),
            data=payload.encode("utf-8") if payload else None,
            timeout=seconds,
            allow_redirects=True,
            # 流式读取：只读前 limit 个字节，避免对方返回 100MB 时把内存吃满
            stream=True,
        )
        # 跳转后的最终地址必须再校验一次：否则可以用一个公网地址 302 到 127.0.0.1 绕过 SSRF 检查
        final_reason = check_url(resp.url)
        if final_reason:
            return fmt(False, f"跳转后的地址被拒绝：{final_reason}")

        text, truncated = _read_body(resp, limit)
        # 只保留几个有用的响应头；Set-Cookie 之类既大又可能含凭证，不进上下文。
        # 按 items() 逐项比对小写名：requests 的 headers 大小写不敏感，但在测试里
        # 用普通 dict 模拟响应时是敏感的，用 get("content-type") 会取不到值。
        kept = [
            f"{key}: {_HEADER_NEWLINE_RE.sub(' ', str(value))}"
            for key, value in resp.headers.items()
            if key.lower() in _KEEP_HEADERS and value
        ]
        head = "\n".join([f"状态行: {resp.status_code} {resp.reason}", *kept])
        body_note = ""
        if truncated:
            body_note = f"\n…[响应体超过 {limit} 字节上限，已截断；需要更多请缩小请求范围]"
        wrapped = as_untrusted(
            f"{head}\n--- 响应体 ---\n{text}{body_note}",
            f"{http_method} {resp.url}",
            limit=8_000,
            noun="HTTP 响应的原文数据",
        )
        return fmt(True, wrapped)
    except ValueError as e:
        # 参数级错误（方法不支持）：这是模型的用法问题，照原样告诉它
        return fmt(False, str(e))
    except Exception as e:
        return fmt(False, f"请求失败: {e}")


# 本模块对外暴露的工具列表
HTTP_TOOLS = [http_request]
