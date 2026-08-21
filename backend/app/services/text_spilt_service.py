"""把文件切成语义自包含、可溯源的块。

三条设计原则（讲义 21.5）：
1. 自包含   —— 单独拿出来也能读懂，所以带 heading_path
2. 不破坏结构 —— 代码块 / 表格 / 列表项不能被切一半
3. 可溯源   —— 每块记录文件路径 + 行号区间，否则回答给不出引用
"""
# 让类型注解延迟求值（PEP 563），便于用 `str | None`、`list[Chunk]` 这种新语法
from __future__ import annotations


# re：按分隔符切分文本（_split_keep）与匹配 Markdown 标题（HEADING_RE）
import re
# bisect_right：在"每行起始偏移"数组里二分查找，把偏移换算成行号（O(log n)）
from bisect import bisect_right
# pathlib.Path：读文件、取扩展名、算相对路径
from pathlib import Path
# 项目内：切片实体（本模块的产物就是一批 Chunk）
from app.entity.chunk import Chunk




def estimate_tokens(text: str) -> int:
    """粗估 token：中文 1 字 ≈ 0.7，其他 4 字符 ≈ 1。只用于上下文预算估算。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return max(1, int(cjk * 0.7 + (len(text) - cjk) / 4))


def _line_starts(text: str) -> list[int]:
    """每行起始偏移的前缀数组。配合 bisect 把「偏移→行号」做成 O(log n)。

    若对每个 chunk 都调 text.count("\\n", 0, offset)，1MB 文档上会慢到肉眼可见。
    """
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    """把字符偏移换算成 1 起始的行号（二分查找，O(log n)）。

    :param starts: _line_starts() 产出的"每行起始偏移"数组
    :param offset: 目标字符偏移（负数按 0 处理）
    """
    return bisect_right(starts, max(0, offset))     # 1-based


# 从"最像语义边界"到"最不像"，最后两项是兜底，保证一定切得动
DEFAULT_SEPARATORS: tuple[str, ...] = (
    "\n\n", "\n", "。", "！", "？", "；", "，", " ", "",
)


def _split_keep(text: str, sep: str) -> list[str]:
    """按 sep 切分，但把 sep 留在**前一个**片段末尾。

    这样所有片段拼起来严格等于原文（不丢字符）。
    "切完拼回来等于原文"是切片器最重要的不变式，必须单测。
    """
    if sep == "":
        return list(text)
    parts = re.split(f"({re.escape(sep)})", text)
    out = [parts[i] + parts[i + 1] for i in range(0, len(parts) - 1, 2)]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _split_spans(
        text: str, base: int, fileSize: int, seps: tuple[str, ...]
) -> list[tuple[str, int]]:
    """递归切分 → [(片段, 在原文中的起始偏移)]。不变式：每个片段长度 <= fileSize。"""
    if len(text) <= fileSize:
        return [(text, base)]
    if not seps or seps[0] == "":
        return [(text[i : i + fileSize], base + i) for i in range(0, len(text), fileSize)]

    atoms = _split_keep(text, seps[0])
    if len(atoms) <= 1:                      # 这个分隔符没出现，降级
        return _split_spans(text, base, fileSize, seps[1:])

    out: list[tuple[str, int]] = []
    cursor = base
    for atom in atoms:
        if len(atom) <= fileSize:
            out.append((atom, cursor))
        else:                                # 单个原子仍超长，继续降级
            out.extend(_split_spans(atom, cursor, fileSize, seps[1:]))
        cursor += len(atom)
    return out


def _merge_with_overlap(
        spans: list[tuple[str, int]], fileSize: int, overlap: int
) -> list[tuple[str, int]]:
    """贪心拼到接近 fileSize，块间保留 overlap 个字符重叠。

    overlap 的实现：新块的 buf 先放上一块末尾的 tail，再接新原子；
    buf_start 相应往前挪 len(tail)，否则行号会漂。
    """
    chunks: list[tuple[str, int]] = []
    buf, buf_start = "", 0
    for atom, offset in spans:
        if not buf:
            buf, buf_start = atom, offset
            continue
        if len(buf) + len(atom) <= fileSize:
            buf += atom
            continue
        chunks.append((buf, buf_start))
        # 只回退到"接上当前原子后仍不超过 fileSize"的长度，保证不变式成立
        tail_len = min(overlap, fileSize - len(atom)) if overlap > 0 else 0
        tail = buf[-tail_len:] if tail_len > 0 else ""
        buf = tail + atom
        buf_start = offset - len(tail)
    if buf.strip():
        chunks.append((buf, buf_start))
    return chunks


def split_fixed(text: str, fileSize: int = 500, overlap: int = 80) -> list[str]:
    """最朴素的固定长度切片。保留它是因为它是所有对比实验的对照组——
    不亲手量一遍，你不会相信"按语义边界切"到底好了多少。"""
    if fileSize <= 0:
        raise ValueError("fileSize 必须 > 0")
    if not 0 <= overlap < fileSize:
        raise ValueError("overlap 必须满足 0 <= overlap < fileSize")
    step = fileSize - overlap
    out: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + fileSize]
        if piece.strip():
            out.append(piece)
        if start + fileSize >= len(text):
            break
    return out


# Markdown 标题正则：组1 = # 号个数（即标题级 1~6），组2 = 标题文字；MULTILINE 让 ^ 匹配每一行行首
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$", re.MULTILINE)


def _split_sections(text: str) -> list[tuple[str, str, int]]:
    """按 Markdown 标题切 section → [(heading_path, 文本, 起始偏移)]。

    heading_path 是"祖先标题 > 当前标题"，同时服务于两件事：
    给检索结果加语义前缀、给前端做章节折叠。
    """
    marks = [(m.start(), len(m.group(1)), m.group(2).strip())
             for m in HEADING_RE.finditer(text)]
    if not marks:
        return [("", text, 0)]

    sections: list[tuple[str, str, int]] = []
    if marks[0][0] > 0 and text[: marks[0][0]].strip():
        sections.append(("", text[: marks[0][0]], 0))     # 第一个标题之前的前言

    stack: list[str] = []
    for i, (pos, level, title) in enumerate(marks):
        del stack[level - 1 :]                            # 同级或更深的标题出栈
        stack.append(title)
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        sections.append((" > ".join(stack), text[pos:end], pos))
    return sections


def split_markdown(text: str, path: str, fileSize: int = 500, overlap: int = 80) -> list[Chunk]:
    """本项目默认切片器：先按标题分节，节内递归切，带完整元数据。"""
    if not 0 <= overlap < fileSize:
        raise ValueError("overlap 必须满足 0 <= overlap < fileSize")

    line_starts = _line_starts(text)
    chunks: list[Chunk] = []
    index = 0
    for heading_path, section, sec_off in _split_sections(text):
        spans = _split_spans(section, sec_off, fileSize, DEFAULT_SEPARATORS)
        for raw, offset in _merge_with_overlap(spans, fileSize, overlap):
            body = raw.strip()
            if not body:
                continue
            lead = len(raw) - len(raw.lstrip())      # strip 会改偏移，补回去
            start_off = offset + lead
            chunks.append(Chunk(
                text=body,
                path=path,
                chunk_index=index,                   # ★ 只对入库的块递增，不留空洞
                start_line=_line_of(line_starts, start_off),
                end_line=_line_of(line_starts, start_off + len(body) - 1),
                heading_path=heading_path,
            ))
            index += 1
    return chunks


# 可索引的文本类扩展名白名单（统一小写、带点）：split_file 只处理这些后缀，其余文件直接跳过
TEXT_EXTS = frozenset({
    ".md", ".markdown", ".txt", ".rst",
    ".py", ".ts", ".tsx", ".js", ".vue", ".java", ".go", ".sql",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".csv", ".log", ".html", ".css",
})
MAX_FILE_BYTES = 2 * 1024 * 1024      # 2MB 以上基本是数据文件，索引它没意义


def _read_text(path: Path) -> str | None:
    """读文本，失败返回 None（跳过），绝不抛异常中断整批索引。"""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def split_file(path: Path, root: Path, fileSize: int = 500, overlap: int = 80) -> list[Chunk]:
    """切一个文件。非文本类 / 读不出来 / 空文件 → 返回空列表。"""
    if path.suffix.lower() not in TEXT_EXTS:
        return []
    text = _read_text(path)
    if not text or not text.strip():
        return []
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() in {".md", ".markdown", ".rst"}:
        return split_markdown(text, rel, fileSize, overlap)

    # 其余按段落/句子边界切（代码文件里的空行天然就是逻辑块边界）
    line_starts = _line_starts(text)
    spans = _split_spans(text, 0, fileSize, DEFAULT_SEPARATORS)
    out: list[Chunk] = []
    for i, (raw, offset) in enumerate(_merge_with_overlap(spans, fileSize, overlap)):
        body = raw.strip()
        if not body:
            continue
        lead = len(raw) - len(raw.lstrip())
        start = offset + lead
        out.append(Chunk(
            text=body, path=rel, chunk_index=i,
            start_line=_line_of(line_starts, start),
            end_line=_line_of(line_starts, start + len(body) - 1),
        ))
    return out