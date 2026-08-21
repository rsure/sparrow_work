# app/services/file_browse_service.py
"""
文件浏览服务：为"路径响应集成"提供两件事——
    1. 判定一个路径能不能在页面内预览，并生成给前端用的文件清单条目
    2. 安全地读出预览内容（或给出"为什么不能预览"的说明）

安全边界（与工具层完全一致，不另起一套规则）：
    路径必须过 resolve_abs_path（拒绝相对路径与系统目录），
    并且必须通过 path_decision(p, OP_READ) —— 所以受保护目录只读是允许的，
    而系统目录一律拒绝（与 Agent 工具看到的世界保持一致）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：base64 给图片接口用；这里只用于扩展名分类，不在这里编码
import mimetypes
# 标准库：路径对象与后缀判断
from pathlib import Path

# 项目内：公共底座（路径校验、编码探测、二进制嗅探、可读文本读取、大小格式化）
from app.tools.tool_utils import (
    OP_READ,
    RICH_DOC_SUFFIXES,
    detect_text_encoding,
    human_size,
    is_binary_file,
    path_decision,
    read_text_any,
    resolve_abs_path,
)

# 可以在 <img> 里直接显示的图片后缀
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}

# 预览接口单次最多返回多少字符（前端只做"看一眼"，不做全文编辑器）
PREVIEW_MAX_CHARS = 200_000


def _kind_of(p: Path) -> str:
    """判断文件属于哪一类（决定前端用哪种预览方式）。

    :param p: 已 resolve 的绝对路径
    :return: text / image / rich（pdf、docx）/ binary 之一
    """
    suffix = p.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in RICH_DOC_SUFFIXES:
        return "rich"
    # 先按后缀排除明显是二进制的，再用内容嗅探兜底（防止 .md 里其实塞了二进制）
    if is_binary_file(p):
        return "binary"
    return "text"


def describe(p: Path) -> dict:
    """生成一个文件清单条目（不含内容，供 done 事件的 files 数组使用）。

    :param p: 已 resolve 的绝对路径
    :return: 含 path/name/kind/previewable/size/size_text/reason 的字典
    """
    exists = p.exists() and p.is_file()
    kind = _kind_of(p) if exists else "missing"
    previewable = kind in ("text", "image", "rich")
    reason = ""
    if not exists:
        reason = "文件不存在或不是普通文件"
    elif kind == "binary":
        reason = "二进制文件，不支持在页面内预览"

    entry = {
        "path": str(p),
        "name": p.name,
        "kind": kind,
        # 能否在左侧面板里预览（false 时前端只提供"打开所在文件夹/用系统程序打开"）
        "previewable": previewable,
        "size": p.stat().st_size if exists else 0,
        "size_text": human_size(p.stat().st_size) if exists else "",
        "reason": reason,
    }
    # mimetypes 用它给 <img> / 下载链接提供 Content-Type，前端也用它判断是否图片
    entry["mime"] = mimetypes.guess_type(p.name)[0] or ""
    return entry


def build_catalog(paths: list[str]) -> list[dict]:
    """把一批路径字符串（来自标记）转成文件清单。

    单个路径解析失败（相对路径、系统目录）不会让整个清单失败——跳过并记下原因，
    这样 AI 回答里混入一条乱写的路径不会导致整个响应出错。

    :param paths: 标记里解析出的原始路径字符串
    :return: 文件清单条目列表（顺序与输入一致，已去重）
    """
    out: list[dict] = []
    for raw in dict.fromkeys(paths):
        try:
            p = resolve_abs_path(raw)
            if path_decision(p, OP_READ):
                continue    # 策略不允许读：不出现在清单里，前端也就不会去点它
            out.append(describe(p))
        except Exception:
            # 非法路径（相对路径 / 系统目录）直接跳过
            continue
    return out


def read_preview(path: str, max_chars: int = PREVIEW_MAX_CHARS) -> dict:
    """读取预览内容；不能预览时返回原因而不是抛异常（前端直接展示 reason）。

    :param path: 原始路径字符串（来自前端的点击事件）
    :param max_chars: 最多返回多少字符
    :return: 含 ok/kind/content/reason/truncated 的字典
    """
    try:
        p = resolve_abs_path(path)
    except Exception as e:
        return {"ok": False, "kind": "missing", "reason": f"路径不可访问: {e}", "content": ""}

    reason = path_decision(p, OP_READ)
    if reason:
        return {"ok": False, "kind": "denied", "reason": reason, "content": ""}
    if not p.exists() or not p.is_file():
        return {"ok": False, "kind": "missing", "reason": "文件不存在或不是普通文件", "content": ""}

    kind = _kind_of(p)
    if kind == "image":
        # 图片不走本接口的内容返回（前端直接用 /file/raw 当 <img> 的 src），
        # 这里只回元信息，避免把二进制塞进 JSON
        return {"ok": True, "kind": "image", "content": "", "reason": "",
                "raw_url": f"/file/raw?path={p}", "truncated": False}
    if kind in ("rich", "binary"):
        return {"ok": True, "kind": kind, "content": "",
                "reason": "该格式不支持在页面内预览，可用系统程序打开", "truncated": False}

    text, note = read_text_any(p)
    if text is None:
        # 读不出来（文件过大、损坏等）：按失败返回原因，避免把元组/None 当正文
        return {"ok": False, "kind": "text", "reason": note, "content": "", "truncated": False}
    truncated = len(text) > max_chars
    return {
        "ok": True,
        "kind": "text",
        "content": text[:max_chars],
        "reason": "",
        "encoding": detect_text_encoding(p) or "utf-8",
        "truncated": truncated,
    }


# `@` 文件候选一次最多给多少条：输入框是个下拉，太多了根本翻不完，
# 而且每多一条就多一次 os.walk 命中判断
MENTION_MAX_RESULTS = 20

# 搜索时单次最多扫多少个文件（防止在超大目录里把接口拖死；超了就把 truncated 置真）
MENTION_MAX_SCAN = 20_000


def _mention_score(name: str, rel: str, q: str) -> int:
    """给一个命中文件打排序分（越小越靠前）。

    为什么要打分而不是按目录顺序返回：用户敲 `@需求` 想要的是"文件名就叫这个"，
    而不是"路径最深处恰好含这两个字"的那一堆。

    :param name: 文件名（含后缀）
    :param rel: 相对工作区根目录的路径（用 / 分隔）
    :param q: 已转小写的查询串
    :return: 0=文件名以查询串开头，1=文件名包含，2=只在路径里包含
    """
    name_l = name.lower()
    if name_l.startswith(q):
        return 0
    if q in name_l:
        return 1
    return 2


def search_files(query: str, limit: int = MENTION_MAX_RESULTS) -> dict:
    """在当前工作区里按文件名/相对路径模糊搜索文件，供输入框的 `@` 候选列表使用。

    只在**当前工作区**里搜（不是整个磁盘）：
        这与 Agent 工具能看到的范围一致（见 tool_utils.WORKSPACE_ROOTS），
        也让候选列表天然"和这个项目相关"。查询为空时返回各工作区根目录下的前 limit 个文件，
        这样刚敲下 `@` 就能看到东西，而不是一片空白。

    :param query: 搜索关键词（大小写不敏感）；空串表示"列出一些文件"
    :param limit: 最多返回多少条候选
    :return: {"query", "items": [{path,name,rel,kind,size_text}], "roots": [str], "truncated": bool}
    """
    # 项目内：工作区根目录（用户没配工作区时返回空列表，这里如实反映"没得搜"）
    from app.services import workspace_service
    # 项目内：遍历工具（已内置忽略目录与系统目录过滤，与 Agent 的 glob 完全同一条规则）
    from app.tools.tool_utils import WalkStats, walk_files

    q = (query or "").strip().lower()
    roots = workspace_service.get_active_roots()
    matched: list[tuple[int, int, Path, Path]] = []   # (分数, 路径长度, 绝对路径, 根目录)
    stats = WalkStats()
    seen: set[str] = set()
    for root in roots:
        for p in walk_files(root, max_files=MENTION_MAX_SCAN, stats=stats):
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                # 理论上 walk_files 只产出 root 之下的路径；真越界就当它不在这个根里
                continue
            key = str(p).lower()
            if key in seen:
                continue
            if q and q not in p.name.lower() and q not in rel.lower():
                continue
            seen.add(key)
            matched.append((_mention_score(p.name, rel, q) if q else 2, len(rel), p, root))
            if len(matched) >= MENTION_MAX_SCAN:
                stats.truncated = True
                break

    # 先按"命中质量"，再按路径深浅（浅的更容易认出来）
    matched.sort(key=lambda item: (item[0], item[1], str(item[2]).lower()))

    items: list[dict] = []
    for _, _, p, root in matched[:limit]:
        try:
            rel = p.relative_to(root).as_posix()
            items.append({
                "path": str(p),
                "name": p.name,
                # 相对路径用于下拉里展示（比一长串绝对路径好认），也用于插入时的短写法
                "rel": rel,
                "kind": _kind_of(p),
                "size_text": human_size(p.stat().st_size),
            })
        except OSError:
            # 扫到之后文件又被删了：跳过，不要让整个候选列表失败
            continue

    return {
        "query": query or "",
        "items": items,
        "roots": [str(root) for root in roots],
        "truncated": bool(stats.truncated),
    }