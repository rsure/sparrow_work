# app/services/office_cli.py
"""本地 Office 引擎适配层（EXT-4）—— 解析链路访问 Office 文档的唯一出口。

## 它是什么

桌面壳（Electron）会拉起一个本地 **editor_sdk** 进程，它把 Word / Excel / PPT 的读写能力
暴露成 **MCP over HTTP**（JSON-RPC 的 `tools/call`）。本模块就是后端这一侧的薄客户端：
探测端口 → 调用只读工具 → 把返回的结构拼成纯文本给 `document_parser`。

## 为什么直接打 HTTP，而不是 `subprocess` 调 `edsdk.py`

`edsdk.py` 本身只是一个"MCP 客户端封装"（list / schema / call 三条命令）。由后端再起一个
Python 子进程去调它，多一层进程、还依赖本机 `python3`——打包成 exe 后 `sys.executable`
指向应用自己，起不了另一个解释器。所以这里用 `httpx` 直接发 JSON-RPC。
代价是丢了 `schema` 的便利，因此**参数形状在本文件里常量化并由单测钉住**：
真机上若引擎的参数名不同，只需要改 `_ARGS` 那几个构造函数。

## 安全边界（重要）

引擎**有写工具**（插入、替换、`save_file`），而解析是"读用户文件"的场景：
若解析链路能触达写工具，一个被投毒文档就可能变成"改用户文件"。
所以 `call()` 入口先断言工具名在 `_ALLOWED_TOOLS` 里，命中写工具直接 `ValueError`。
白名单是**代码常量，不进设置**——设置里的开关用户能改，代码里的边界用户改不了。
本模块也**不注册成 Agent 工具**：模型无法直接调用它，只能经由解析入口被动使用。

## 实例归属（重要）

`get_pool_status` 命中说明用户已经开着 / 之前开过这个文件：复用它的 `file_id`，标记
`owned = False`，结束时**绝不能关**（关掉等于把用户正在编辑的文档关掉）。
只有自己 `open_file` 打开的实例才 `owned = True`、才在 finally 里 `close_file`。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：上下文管理器，保证"自己开的实例一定被关掉"
from contextlib import contextmanager
# 标准库：缓存键要判断文件是否被改过（size + mtime）
from pathlib import Path
# 标准库：调用超时由设置给（毫秒），换算成秒
from typing import Any, Iterator
# 标准库：日志只记路径、字符数、耗时，绝不打印正文
import logging
# 标准库：把引擎放在 text 里的业务 JSON 解出来
import json
# 标准库：端点探测与缓存要加锁（解析可能在被线程池并发调用）
import threading
# 标准库：失败冷却用单调时钟
import time
# 第三方：MCP over HTTP 就是普通 JSON-RPC over HTTP，不需要 MCP SDK
import httpx
# 项目内：鉴权 token（桌面壳拉起引擎时写进进程环境，配置里读）
from app.config import settings
# 项目内：设置读取（office.* 五个键）；键未注册时退回默认值
from app.services.settings_registry import get_setting

# 本模块专用 logger
log = logging.getLogger(__name__)

# 自动探测的端口范围（含两端）：与桌面壳拉起引擎时用的范围一致
_PORT_RANGE: tuple[int, ...] = tuple(range(39099, 39109))
# MCP 端点路径：editor_sdk 把所有工具挂在同一个 JSON-RPC 入口上
_MCP_PATH: str = "/mcp"
# 探测单个端口的超时（秒）。必须很短：探 10 个端口最坏也只花 8 秒，且探测结果会缓存
_PROBE_TIMEOUT: float = 0.8
# 探测失败后的冷却时间（秒）：避免"引擎没启动"时每个文件都白等一轮探测
_COOLDOWN_SECONDS: float = 30.0
# 演示文稿最多读多少页：防一个 3000 页的 PPT 把上下文和内存一起打爆
MAX_SLIDE_PAGES: int = 200
# 文本缓存最多留几条（批量索引 50 个文件时，同一文件常被读两三次）
_CACHE_SIZE: int = 200

# ---- 只读白名单 ---------------------------------------------------------- #
# 允许解析链路调用的"取文本"工具。都符合 *_get_* / *_list_* / *_find /
# *_resolve_* / *_calculate_* 的只读语义，任何一个都不能改文档内容。
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "doc_resolve_document_structure",
    "doc_get_outline",
    "doc_get_text",
    "doc_list_textbox_and_comment",
    "doc_list_comments",
    "doc_find_text",
    "sheet_get_sheet_info",
    "sheet_get_used_range",
    "sheet_get_cell_data",
    "sheet_list_sheets",
    "sheet_find_value",
    "slide_get_info",
    "slide_get_page_info",
    "slide_get_text",
    "slide_get_notes_text",
    "slide_list_pages",
})

# 生命周期工具：不产出正文，但必须允许调用，否则读不了也关不掉。
# 单独一组而不是混进 READ_ONLY_TOOLS，是为了让"哪些能读正文"这件事在代码里一眼看得清。
# 注意 open_file 只允许 `open_with_existing=True`（后台装载、不弹预览、不进用户视图）。
_LIFECYCLE_TOOLS: frozenset[str] = frozenset({
    "get_pool_status",
    "open_file",
    "close_file",
})

# call() 的实际准入集合：只读 + 生命周期，其余一律拒绝
_ALLOWED_TOOLS: frozenset[str] = READ_ONLY_TOOLS | _LIFECYCLE_TOOLS

# 折叠引擎返回结构时要跳过的键：这些是 id / 类型 / 层级，不是正文
_SKIP_KEYS: frozenset[str] = frozenset({
    "file_id", "id", "type", "kind", "level", "index", "page", "sheet",
    "start_row", "start_col", "row_count", "column_count", "width", "height",
})

# 折叠返回结构的最大深度：形状嵌套（组合形状里套分组）不能把递归打穿
_MAX_DEPTH: int = 12
# 单次折叠最多收集多少个文本块：再多的结构细节对理解内容也没帮助
_MAX_BLOCKS: int = 5000

# 端点缓存：成功时记住可用地址；失败时记下"冷却到什么时候"
_endpoint_lock = threading.Lock()
# 已探测到的端点（如 http://127.0.0.1:39099）；None 表示还没探到或已失效
_cached_endpoint: str | None = None
# 冷却截止时间（time.monotonic() 的绝对值）；当前时间小于它就不再重试
_retry_after: float = 0.0

# 文本缓存：(绝对路径, 字节数, mtime_ns) -> 解析结果
_text_cache: dict[tuple[str, int, int], str] = {}
# 文本缓存的锁
_cache_lock = threading.Lock()

# JSON-RPC 的请求 id 计数器（递增即可，引擎不校验唯一性）
_request_ids = iter(range(1, 10**9))


class OfficeCliUnavailable(RuntimeError):
    """探测不到（或调用失败于）Office 引擎端点。

    调用方**据此降级**，不得当致命错误抛出：用户只是没装/没启动引擎，
    打开一个 .docx 不应该变成一次报错。
    """


def reset_for_test() -> None:
    """清空端点缓存失败冷却与文本缓存（测试用，也用于"用户刚启动了引擎"后的手动重试）。"""
    global _cached_endpoint, _retry_after
    with _endpoint_lock:
        _cached_endpoint = None
        _retry_after = 0.0
    with _cache_lock:
        _text_cache.clear()


def _setting(key: str, default: Any) -> Any:
    """读一个 office.* 设置；键未注册或读失败时退回默认值。

    为什么容错：解析链路不该因为"设置表还没注册"就整体不可用
    （例如被脚本单独 import、或在迁移前的旧库里跑）。
    """
    try:
        value = get_setting(key)
    except Exception:  # noqa: BLE001 - 设置读不到属于可恢复情况，按默认值继续
        return default
    return default if value is None else value


def enabled() -> bool:
    """Office 引擎总开关是否打开（office.enabled）。"""
    return bool(_setting("office.enabled", True))


def _timeout_ms() -> int:
    """单次调用超时（毫秒），夹在 1000~120000 之间。"""
    try:
        value = int(_setting("office.timeout_ms", 15000))
    except (TypeError, ValueError):
        return 15000
    return max(1000, min(120000, value))


def _auth_headers() -> dict[str, str]:
    """构造请求头：引擎若配了 token 就要带 Authorization。"""
    token = (getattr(settings, "editor_sdk_token", "") or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _base_url(port: int) -> str:
    """端口 → 端点根地址（引擎只监听本机回环）。"""
    return f"http://127.0.0.1:{port}"


def _port_candidates() -> list[int]:
    """本次要探测的端口列表：设置里固定了端口就只探它，否则按范围顺序探。"""
    try:
        fixed = int(_setting("office.port", 0))
    except (TypeError, ValueError):
        fixed = 0
    if 0 < fixed <= 65535:
        return [fixed]
    return list(_PORT_RANGE)


def _probe(base: str) -> bool:
    """探测一个端点是否是可用的 MCP 服务（发一次 tools/list，能拿到 result 就算通）。"""
    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_ids),
        "method": "tools/list",
        "params": {},
    }
    try:
        response = httpx.post(
            f"{base}{_MCP_PATH}", json=payload, headers=_auth_headers(), timeout=_PROBE_TIMEOUT,
        )
    except (httpx.HTTPError, OSError):
        # 连不上 / 端口没人监听 / 超时：都算"这个端口没有引擎"
        return False
    if response.status_code != 200:
        return False
    try:
        data = response.json()
    except ValueError:
        # 200 但不是 JSON：端口被别的服务占了
        return False
    return isinstance(data, dict) and "result" in data


def endpoint(*, refresh: bool = False) -> str | None:
    """返回可用的引擎端点；探测不到返回 None（不抛异常，调用方决定是否降级）。

    :param refresh: 忽略缓存与冷却，强制重新探测（用户刚启动引擎时用）
    :return: 形如 ``http://127.0.0.1:39099``；不可用时为 None
    """
    global _cached_endpoint, _retry_after
    with _endpoint_lock:
        if not refresh:
            if _cached_endpoint:
                return _cached_endpoint
            if time.monotonic() < _retry_after:
                # 还在冷却期内：直接认失败，别让每个文件都等一轮探测
                return None
        for port in _port_candidates():
            base = _base_url(port)
            if _probe(base):
                _cached_endpoint = base
                _retry_after = 0.0
                return base
        # 全部失败：清掉旧缓存并进入冷却
        _cached_endpoint = None
        _retry_after = time.monotonic() + _COOLDOWN_SECONDS
        return None


def _decode_call_result(result: dict[str, Any]) -> dict[str, Any]:
    """把 MCP 的 `result` 解成普通字典。

    MCP 的 tools/call 返回 ``{"content": [{"type": "text", "text": "..."}]}``：
    引擎把业务结果 JSON 序列化在 text 里，所以这里优先尝试 `json.loads`，
    解析不出来就退回 ``{"text": 原文}``（有些工具直接返回人读的文本）。
    """
    content = result.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        joined = "\n".join(text for text in texts if isinstance(text, str))
        try:
            parsed = json.loads(joined)
        except ValueError:
            return {"text": joined}
        return parsed if isinstance(parsed, dict) else {"text": joined}
    if isinstance(result, dict):
        return result
    return {"text": str(result)}


def _invalidate_endpoint() -> None:
    """把缓存的端点作废：下次调用会重新探测（引擎可能刚被关掉或换了端口）。"""
    global _cached_endpoint
    with _endpoint_lock:
        _cached_endpoint = None


def call(tool: str, args: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    """调用引擎的一个**白名单内**工具，返回解析后的结果字典。

    :param tool: 工具名，必须在 `_ALLOWED_TOOLS` 里（写工具会被拒绝）
    :param args: 工具参数
    :param timeout_ms: 本次调用超时（毫秒）
    :return: 工具返回的业务字典
    :raises ValueError: 工具名不在白名单（解析链路试图调用写工具）
    :raises OfficeCliUnavailable: 端点不可用 / HTTP 非 200 / 引擎返回 error
    """
    if tool not in _ALLOWED_TOOLS:
        # 明确报错而不是静默拒绝：这是"代码写错了"级别的问题，必须能被测试抓住
        raise ValueError(
            f"解析链路不允许调用工具 {tool}（只允许只读与生命周期工具）"
        )
    base = endpoint()
    if base is None:
        raise OfficeCliUnavailable("未探测到本地 Office 引擎（editor_sdk）")

    payload = {
        "jsonrpc": "2.0",
        "id": next(_request_ids),
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    try:
        response = httpx.post(
            f"{base}{_MCP_PATH}",
            json=payload,
            headers=_auth_headers(),
            timeout=max(1.0, timeout_ms / 1000.0),
        )
    except (httpx.HTTPError, OSError) as exc:
        # 连接断了：把端点缓存作废，下一次重新探测（引擎可能刚被关掉）
        _invalidate_endpoint()
        raise OfficeCliUnavailable(f"调用 Office 引擎失败：{exc}") from exc

    if response.status_code != 200:
        raise OfficeCliUnavailable(f"Office 引擎返回 HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise OfficeCliUnavailable("Office 引擎返回的不是合法 JSON") from exc
    if isinstance(data, dict) and data.get("error"):
        error = data["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise OfficeCliUnavailable(f"Office 引擎报错：{message}")
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise OfficeCliUnavailable("Office 引擎没有返回 result")
    return _decode_call_result(result)


def _file_id_of(payload: dict[str, Any]) -> int | None:
    """从 get_pool_status / open_file 的返回里取出实例 id；取不到返回 None。"""
    value = payload.get("file_id")
    if isinstance(value, int):
        return value
    # 有些实现返回 {"files": [{"file_id": 3, ...}]}：取第一个
    files = payload.get("files")
    if isinstance(files, list) and files and isinstance(files[0], dict):
        inner = files[0].get("file_id")
        if isinstance(inner, int):
            return inner
    return None


@contextmanager
def _instance(path: Path) -> Iterator[int]:
    """复用一个已打开的实例，或后台新开一个；退出时只关自己开的那个。

    :param path: 目标文件的**绝对路径**（相对路径在反查里不是同一份文件）
    :return: 可用于后续 doc_* / sheet_* / slide_* 调用的 file_id
    :raises OfficeCliUnavailable: 打开失败（加密 / 损坏 / 后缀与内容不符）
    """
    timeout = _timeout_ms()
    file_id: int | None = None
    owned = False
    # 1) 先问 pool：用户可能正开着这个文件，复用最省时间也最不容易出错
    try:
        pool = call("get_pool_status", {"file_path": str(path)}, timeout)
        file_id = _file_id_of(pool)
    except OfficeCliUnavailable:
        # pool 查不动就当作"没开过"，继续走 open_file
        file_id = None
    if file_id is None:
        # 2) 后台装载：open_with_existing=True 表示"已有实例就复用，没有就静默打开"
        opened = call(
            "open_file", {"file_path": str(path), "open_with_existing": True}, timeout,
        )
        file_id = _file_id_of(opened)
        owned = True
        if file_id is None:
            raise OfficeCliUnavailable(f"打开文档失败：{path.name}")
    try:
        yield file_id
    finally:
        # 3) 只关自己打开的：关用户实例等于把用户的编辑器关掉
        if owned:
            try:
                call("close_file", {"file_id": file_id}, timeout)
            except (OfficeCliUnavailable, ValueError) as exc:
                # 关不掉不影响已经读到的内容，只记日志
                log.warning("关闭 Office 实例失败（file_id=%s）：%s", file_id, exc)


def _collect_text(value: Any, depth: int = 0) -> list[str]:
    """把引擎返回的任意嵌套结构里的**正文**按顺序收集成文本块列表。

    引擎不同工具返回的形状不一样（`{"text": "..."}`、`{"blocks": [{"text": ...}]}`、
    `{"paragraphs": [...]}`），与其为每个工具写一个解析器，不如统一"抓所有字符串叶子"：
    跳过 id/类型/坐标这类键（`_SKIP_KEYS`），并限制递归深度。

    :param value: 引擎返回的任意 JSON 值
    :param depth: 递归深度（内部用）
    :return: 按出现顺序排列的非空文本块（已 strip）
    """
    if depth > _MAX_DEPTH:
        return []
    texts: list[str] = []
    if isinstance(value, str):
        text = value.strip("\r\n")
        if text.strip():
            texts.append(text)
    elif isinstance(value, list):
        for item in value:
            texts.extend(_collect_text(item, depth + 1))
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _SKIP_KEYS:
                continue
            texts.extend(_collect_text(item, depth + 1))
    return texts


def _text_of(payload: dict[str, Any]) -> str:
    """把一个工具返回折叠成一段纯文本（按行拼接，去掉空块，块数有上限）。"""
    blocks = _collect_text(payload)[:_MAX_BLOCKS]
    return "\n".join(block for block in blocks if block.strip())


def _cached(kind: str, path: Path, reader: Any) -> str:
    """按 (路径, 大小, mtime) 缓存解析结果，避免批量索引时反复读同一个文件。

    :param kind: 解析器类别（doc / sheet / slide），与路径一起构成缓存键
    :param path: 绝对路径
    :param reader: 真正干活的零参函数
    :return: 解析出的文本
    """
    try:
        stat = path.stat()
        key = (f"{kind}:{path}", stat.st_size, stat.st_mtime_ns)
    except OSError:
        # 文件都 stat 不到就别缓存了，直接读（让上层给出更准确的原因）
        return reader()
    with _cache_lock:
        hit = _text_cache.get(key)
    if hit is not None:
        return hit
    text = reader()
    with _cache_lock:
        if len(_text_cache) >= _CACHE_SIZE:
            # 朴素 FIFO：插入顺序即 dict 顺序，丢掉最早的一条
            _text_cache.pop(next(iter(_text_cache)), None)
        _text_cache[key] = text
    return text


def read_doc(path: Path) -> str:
    """读 Word 品类（.docx/.doc/.dot/.wps/.wpt/.docm）的正文，返回纯文本。

    doc 品类**没有**"导出全文"的单一工具，必须拼结构树：
    结构树给正文，大纲补标题层级，文本框/批注补结构树里不一定有的内容。

    :param path: 文档绝对路径
    :return: 带 `[第 N 段]` 标记的纯文本
    :raises OfficeCliUnavailable: 端点不可用或打开失败（调用方据此降级）
    """
    path = Path(path).resolve()

    def _read() -> str:
        """真正执行一次读取（拆出来是为了能整体进缓存）。"""
        timeout = _timeout_ms()
        with _instance(path) as file_id:
            structure = call("doc_resolve_document_structure", {"file_id": file_id}, timeout)
            # 大纲与文本框是"补充材料"：失败不应该毁掉整次解析
            outline = _try_call("doc_get_outline", {"file_id": file_id}, timeout)
            extras = _try_call("doc_list_textbox_and_comment", {"file_id": file_id}, timeout)
        # 三段分别打标记：模型与用户都能看出"这段是正文，那段是批注"，
        # 而不是把批注当成正文的一部分去总结
        sections: list[str] = []
        for label, payload in (
            ("正文", structure),
            ("大纲", outline),
            ("文本框与批注", extras),
        ):
            if payload is None:
                continue
            body = _text_of(payload)
            if body.strip():
                sections.append(f"[{label}]\n{body}")
        body_text = "\n\n".join(sections)
        if not body_text.strip():
            raise OfficeCliUnavailable(f"引擎没有读出正文：{path.name}")
        return _normalize(body_text)

    return _cached("doc", path, _read)


def read_sheet(path: Path) -> str:
    """读 Excel 品类（.xlsx/.xls/.xlt/.xlsm）的所有子表，返回纯文本。

    行/列上限来自 office.max_rows / office.max_cols（不是常量），超限标注截断。

    :param path: 工作簿绝对路径
    :return: 每个子表一段，前缀 `[Sheet 名称]`
    :raises OfficeCliUnavailable: 端点不可用或打开失败
    """
    path = Path(path).resolve()

    def _read() -> str:
        """真正执行一次读取。"""
        timeout = _timeout_ms()
        try:
            max_rows = max(1, int(_setting("office.max_rows", 5000)))
        except (TypeError, ValueError):
            max_rows = 5000
        try:
            max_cols = max(1, int(_setting("office.max_cols", 40)))
        except (TypeError, ValueError):
            max_cols = 40

        blocks: list[str] = []
        with _instance(path) as file_id:
            info = call("sheet_get_sheet_info", {"file_id": file_id}, timeout)
            for name in _sheet_names(info):
                blocks.append(
                    _render_sheet(file_id, name, timeout, max_rows=max_rows, max_cols=max_cols)
                )
        if not blocks:
            raise OfficeCliUnavailable(f"引擎没有读出工作表：{path.name}")
        return _normalize("\n\n".join(blocks))

    return _cached("sheet", path, _read)


def _sheet_names(info: dict[str, Any]) -> list[str]:
    """从 sheet_get_sheet_info 的返回里取出子表名列表（保持原顺序）。"""
    raw = info.get("sheets") or info.get("sheet_names") or []
    names: list[str] = []
    for item in raw:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("sheet")
            if isinstance(name, str):
                names.append(name)
    return names


def _render_sheet(
    file_id: int, name: str, timeout: int, *, max_rows: int, max_cols: int,
) -> str:
    """渲染单个子表：先取真实已用区域，再分页取单元格，最后拼成 `a | b` 的文本行。

    :param file_id: 实例 id
    :param name: 子表名
    :param timeout: 单次调用超时（毫秒）
    :param max_rows: 最多渲染多少行
    :param max_cols: 最多渲染多少列
    :return: 该子表的文本块（首行是 `[Sheet 名称]`）
    """
    used = _try_call("sheet_get_used_range", {"file_id": file_id, "sheet": name}, timeout) or {}
    # 真实边界由引擎给；拿不到就按上限兜底，宁可多问一次也不要漏内容
    rows = _int_of(used.get("row_count"), max_rows)
    cols = _int_of(used.get("column_count"), max_cols)
    capped_rows = min(rows, max_rows)
    capped_cols = min(cols, max_cols)
    cells = _try_call(
        "sheet_get_cell_data",
        {
            "file_id": file_id,
            "sheet": name,
            "start_row": 0,
            "start_col": 0,
            "row_count": capped_rows,
            "column_count": capped_cols,
        },
        timeout,
    ) or {}
    lines = [_render_row(row) for row in _cell_rows(cells)]
    lines = [line for line in lines if line.strip()]
    head = f"[Sheet {name}]"
    if rows > capped_rows:
        lines.append(f"…（超过 {max_rows} 行，已截断；本表实际 {rows} 行）")
    if cols > capped_cols:
        lines.append(f"…（超过 {max_cols} 列，已截断；本表实际 {cols} 列）")
    return "\n".join([head, *lines])


def _int_of(value: Any, default: int) -> int:
    """把可能是字符串/缺失的计数值转成非负整数。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _cell_rows(payload: dict[str, Any]) -> list[Any]:
    """从 sheet_get_cell_data 的返回里取出"行的集合"。

    形状可能是 `{"rows": [[..],[..]]}` 或 `{"cells": [{"row":0,"values":[..]}]}`，
    两种都归一成"每行一个 list"。
    """
    rows = payload.get("rows")
    if isinstance(rows, list):
        return rows
    cells = payload.get("cells")
    if isinstance(cells, list):
        indexed: dict[int, list[Any]] = {}
        for item in cells:
            if not isinstance(item, dict):
                continue
            row_index = _int_of(item.get("row"), 0)
            values = item.get("values")
            if isinstance(values, list):
                indexed[row_index] = values
        return [indexed[key] for key in sorted(indexed)]
    return []


def _render_row(row: Any) -> str:
    """把一行单元格渲染成 `a | b | c`（空值留空、竖线转义，避免破坏表格观感）。"""
    if isinstance(row, dict):
        values = row.get("values") or row.get("cells") or []
    elif isinstance(row, list):
        values = row
    else:
        return str(row)
    cells = []
    for value in values:
        text = "" if value is None else str(value)
        # 竖线是列分隔符，正文里的竖线要转义，否则看的人分不清列
        cells.append(text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " "))
    return " | ".join(cells)


def read_slide(path: Path) -> str:
    """读 PPT 品类（.pptx/.ppt/.pps/.pot）的所有页，返回纯文本。

    每页先取形状信息（标题、文本框、表格摘要）再取文本；超过 200 页截断。

    :param path: 演示文稿绝对路径
    :return: 每页一段，前缀 `[Slide N]`
    :raises OfficeCliUnavailable: 端点不可用或打开失败
    """
    path = Path(path).resolve()

    def _read() -> str:
        """真正执行一次读取。"""
        timeout = _timeout_ms()
        blocks: list[str] = []
        with _instance(path) as file_id:
            info = call("slide_get_info", {"file_id": file_id}, timeout)
            page_count = _int_of(info.get("page_count"), 0) or len(info.get("pages") or [])
            limit = min(page_count, MAX_SLIDE_PAGES)
            for page_no in range(1, limit + 1):
                page_info = _try_call(
                    "slide_get_page_info", {"file_id": file_id, "page": page_no}, timeout,
                ) or {}
                page_text = _try_call(
                    "slide_get_text", {"file_id": file_id, "page": page_no}, timeout,
                ) or {}
                body = "\n".join(
                    part for part in (_text_of(page_info), _text_of(page_text)) if part.strip()
                )
                blocks.append(f"[Slide {page_no}]\n{body}".rstrip())
            if page_count > limit:
                blocks.append(f"…（超过 {MAX_SLIDE_PAGES} 页，已截断；本文件实际 {page_count} 页）")
        if not any(block.strip() for block in blocks):
            raise OfficeCliUnavailable(f"引擎没有读出幻灯片：{path.name}")
        return _normalize("\n\n".join(blocks))

    return _cached("slide", path, _read)


def _try_call(tool: str, args: dict[str, Any], timeout_ms: int) -> dict[str, Any] | None:
    """调用一个"可选"工具：失败只记日志并返回 None，不让它毁掉整次解析。

    典型例子：`doc_get_outline`（没有标题的文档会返回空）与 `doc_list_textbox_and_comment`
    （纯正文文档可能不支持）。这些失败是正常的，不该触发降级。
    """
    try:
        return call(tool, args, timeout_ms)
    except (OfficeCliUnavailable, ValueError) as exc:
        log.debug("可选工具 %s 调用失败（忽略）：%s", tool, exc)
        return None


def _normalize(text: str) -> str:
    """统一换行符：Windows 文档常见 `\\r\\n`，进上下文前统一成 `\\n`。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def status() -> dict[str, Any]:
    """给设置页看的引擎状态快照（不做重探测，避免每次打开设置页都等一轮）。

    :return: ``{"enabled": bool, "endpoint": str|None, "cooldown_seconds": float}``
    """
    with _endpoint_lock:
        cooldown = max(0.0, _retry_after - time.monotonic())
        current = _cached_endpoint
    return {
        "enabled": enabled(),
        "endpoint": current,
        "cooldown_seconds": round(cooldown, 1),
    }
