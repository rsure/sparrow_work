# app/tools/file_read_tool.py
"""
只读 + 知识库类原子工具：暴露给 DeepSeek Agent，由模型自由组合完成各种问题。

为什么是"原子工具"而不是"场景工具"：
    用户的问题无法穷举（统计文件夹、读需求文档答题、找某个问题在哪个文件……），
    每个场景写一个工具永远补不完。这里只提供 6 个基础能力，场景交给模型去组合：

    | 工具          | 能力                                   | 是否有副作用       |
    | ------------- | -------------------------------------- | ------------------ |
    | list_dir      | 列目录 / 统计文件数、大小、类型分布    | 无                 |
    | read_file     | 读任意文件全文（分段），读不了给元信息 | 无                 |
    | grep_files    | 按文件名或内容关键字在磁盘上找文件     | 无                 |
    | list_indexed_docs | 列出知识库里已导入的文档           | 无                 |
    | index_path    | 把文件/文件夹导入 RAG 知识库           | 写知识库           |
    | delete_index  | 从知识库删除文件/文件夹的记录          | 删知识库（弹窗确认）|
    | rag_search    | 在知识库里语义检索，可限定范围         | 无                 |

系统文件限制：
    所有路径都经过 tool_utils.resolve_abs_path，系统文件 / 系统目录直接拒绝；
    递归遍历（统计、搜索、导入文件夹）时自动跳过系统项，并在结果里报告跳过了多少个。

工具返回约定：
    统一返回 "OK: <msg>" 或 "FAIL: <msg>"（见 tool_utils.fmt）；
    返回原始事实（完整路径、数量、大小），总结交给模型，不在工具里替模型下结论。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、list[str] 等新语法
from __future__ import annotations

# 标准库：Counter 统计各文件后缀出现次数（"类型分布"）
from collections import Counter
# 标准库：路径对象，取文件名、相对路径、后缀
from pathlib import Path

# LangChain 工具装饰器：把普通函数变成模型可调用的工具，docstring 会作为工具说明发给模型
from langchain_core.tools import tool
# LangGraph 中断异常的基类：delete_index 的兜底 except 里要原样抛出它，让"暂停等待确认"生效
from langgraph.errors import GraphBubbleUp

# 项目内：RAG 文档库服务（入库、删除、检索、列文档）
from app.services.rag_store_service import RagStoreService
# 项目内：解析注册表——文件夹批量索引收哪些后缀，由"已注册解析器"决定
from app.services.document_parser import supported_suffixes
# 项目内：工具公共底座——返回格式、绝对路径校验、目录遍历、文本读取兜底、暂停请用户确认
from app.tools import file_guard
from app.tools.session import current_session_id
from app.tools.tool_utils import (
    RICH_DOC_SUFFIXES,
    WalkStats,
    ask_user,
    describe_file,
    detect_text_encoding,
    fmt,
    human_size,
    is_binary_file,
    read_text_any,
    resolve_abs_path,
    same_or_under,
    system_path_reason,
    walk_files,
)

# --------------------------------------------------------------------------- #
# 服务实例与常量
# --------------------------------------------------------------------------- #
# 模块级单例，避免每次工具调用都重新构造（FAISS 索引在进程内按维度共享）
_svc = RagStoreService(chunk_size=500, overlap=80)

# 导入"整个文件夹"时只收这些文档类后缀，避免把代码、日志、lock 文件一股脑灌进知识库；
# 单独指定某个文件时不受此限制，只要能读成文本就允许导入
# 文件夹批量索引时收哪些文件：由解析注册表派生，注册新格式后自动纳入
_FOLDER_INDEX_SUFFIXES = set(supported_suffixes())

# 递归统计 / 搜索时最多遍历的文件数，防止用户给一个磁盘根目录导致长时间卡住
_MAX_WALK_FILES = 50_000

# grep_files 读取内容时单个文件的体积上限（单位：字节，5MB），更大的文件只做文件名匹配
_GREP_MAX_FILE_BYTES = 5 * 1024 * 1024

# read_file 单次最多返回的字符数，太大会挤占模型上下文
_READ_MAX_CHARS = 20_000

# 从知识库一次性列出全部文档时的条数上限（用于按路径/文件名匹配文档）
_ALL_DOCS_LIMIT = 100_000


def all_indexed_docs() -> list[dict]:
    """取出知识库里所有文档的元信息（含 id / name / source / chunks）。

    公开函数：除了本模块的各工具，app/controllers/chat_controller.py 解析 `\\doc` 指令时也用它
    （要拿全部文档名去判断"用户写的是文件名还是问题的一部分"）。

    :return: list_documents 返回的字典列表（按 id 倒序，最新导入的在前）
    """
    return _svc.list_documents(limit=_ALL_DOCS_LIMIT)


def match_indexed_docs(scope: list[str]) -> tuple[list[dict], list[str]]:
    """在"已导入文档"里按绝对路径 / 文件夹 / 裸文件名匹配，返回命中的文档记录与没匹配上的条目。

    三种写法：
        - 绝对路径且是个文件：只匹配这一篇
        - 绝对路径且是个文件夹：匹配它自己以及它下面所有已导入的文档
        - 只有文件名（如 note.md）：按文件名精确匹配（不区分大小写）

    为什么要有这个函数：delete_index（删除要 doc_id）、resolve_scope（检索只要 source）、
    以及聊天页 `\\doc` 指令的解析，三处都要"把用户说的名字换成人库记录"。
    共用同一份规则，才不会出现"检索说找得到、删除却说找不到"这种自相矛盾。

    :param scope: 用户或模型给的路径 / 文件名列表
    :return: (命中的文档记录列表（按 source 去重并排序）, 没匹配上的原始条目)
    """
    docs = all_indexed_docs()
    matched: dict[str, dict] = {}       # source -> 文档记录，用它去重（同一文件夹写法可能命中同一篇）
    missing: list[str] = []
    for item in scope:
        text = (item or "").strip().strip('"').strip("'")
        if not text:
            continue
        p = Path(text).expanduser()
        if p.is_absolute():
            hits = [d for d in docs if same_or_under(d["source"], p.resolve())]
        else:
            low = text.lower()
            hits = [d for d in docs if Path(d["source"]).name.lower() == low]
        if hits:
            for d in hits:
                matched[d["source"]] = d
        else:
            missing.append(item)
    return [matched[s] for s in sorted(matched)], missing


def resolve_scope(scope: list[str]) -> tuple[list[str], list[str]]:
    """
    本模块唯一实现
    把模型（或前端的 `\\doc` 指令）给的检索范围换算成知识库里的 source 列表。

    匹配规则见 match_indexed_docs；这里只是把命中的记录压成 source 字符串
    （检索接口只认 source / doc_id，不需要整条记录）。

    :param scope: 路径或文件名列表
    :return: (匹配到的 source 列表, 没匹配上的条目)
    """
    matched, missing = match_indexed_docs(scope)
    return [d["source"] for d in matched], missing


def resolve_import_path(raw: str) -> Path:
    """把 index_path 收到的参数解析成磁盘上的绝对路径。

    支持两种写法：
        - 绝对路径：直接用（导入新文件必须走这条）
        - 已导入文档的文件名（如 note.md）：换算成这篇文档当初导入时用的绝对路径，
          于是"重新导入 note.md"这种说法也成立（常见于"把这份文档的索引刷新一下"）

    :param raw: 用户或模型给的路径 / 文件名
    :return: 磁盘上的绝对路径（不保证存在，调用方自行判断）
    :raises ValueError: 既不是绝对路径，也不匹配任何已导入文档
    """
    text = (raw or "").strip().strip('"').strip("'")
    if Path(text).expanduser().is_absolute():
        return resolve_abs_path(text)

    matched, _ = match_indexed_docs([text])
    if not matched:
        raise ValueError(
            f"「{text}」既不是绝对路径，也不是已导入文档的文件名。"
            f"导入新文件请给完整路径（如 D:\\docs\\a.md）；"
            f"不确定文档名可以先用 list_indexed_docs 查一下"
        )
    # 命中多篇同名文档（不同目录下的同名文件）时取第一篇：够用，且不会静默什么都不做
    return Path(matched[0]["source"])


# =========================================================================== #
# 工具 1：列目录 / 统计
# =========================================================================== #
@tool
def list_dir(path: str, recursive: bool = False, max_entries: int = 100) -> str:
    """列出目录内容并给出统计（文件数、子目录数、总大小、文件类型分布）；传入文件则返回该文件的元信息。

    适用：查看文件夹里有什么、比较几个文件夹谁的文件多/谁更大、找某类文件、了解目录结构。
    需要比较多个目录时，对每个目录分别调用一次。只读，不会导入或修改任何东西。

    :param path: 目录或文件的绝对路径
    :param recursive: False 只看当前这一层；True 递归统计所有子目录（会跳过 node_modules/.git 等）
    :param max_entries: 最多列出多少条明细（统计数字始终是完整的），默认 100
    :return: "OK: 统计信息 + 明细列表" 或 "FAIL: 原因"
    """
    try:
        p = resolve_abs_path(path)
        if not p.exists():
            return fmt(False, f"路径不存在: {p}")
        if p.is_file():
            return fmt(True, f"这是一个文件: {p}\n{describe_file(p)}")

        lines: list[str] = []
        if not recursive:
            # 只看当前层：先剔除系统项（如列 C:\ 时的 Windows、回收站），再目录在前、文件在后排序
            all_children = list(p.iterdir())
            children = sorted(
                (c for c in all_children if not system_path_reason(c)),
                key=lambda c: (not c.is_dir(), c.name.lower()),
            )
            hidden_system = len(all_children) - len(children)
            dirs = [c for c in children if c.is_dir()]
            files = [c for c in children if c.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            suffixes = Counter(f.suffix.lower() or "(无后缀)" for f in files)
            header = (
                f"目录 {p}（仅当前层）：子目录 {len(dirs)} 个，文件 {len(files)} 个，"
                f"文件总大小 {human_size(total_size)}"
            )
            if hidden_system:
                header += f"；已隐藏 {hidden_system} 个系统文件/目录（不允许处理）"
            for c in children[:max_entries]:
                lines.append(f"[目录] {c.name}/" if c.is_dir() else f"[文件] {c.name}  {describe_file(c)}")
            shown_total = len(children)
        else:
            stats = WalkStats()
            files = list(walk_files(p, max_files=_MAX_WALK_FILES, stats=stats))
            total_size = sum(f.stat().st_size for f in files)
            suffixes = Counter(f.suffix.lower() or "(无后缀)" for f in files)
            header = f"目录 {p}（递归）：文件 {len(files)} 个，总大小 {human_size(total_size)}"
            if stats.skipped_dirs:
                header += f"；已跳过 {stats.skipped_dirs} 个依赖/缓存目录（node_modules、.git 等）"
            if stats.skipped_system:
                header += f"；已跳过 {stats.skipped_system} 个系统文件/目录（不允许处理）"
            if stats.truncated:
                header += f"；⚠ 文件超过 {_MAX_WALK_FILES} 个，统计已截断、数字偏小"
            for f in files[:max_entries]:
                lines.append(f"[文件] {f.relative_to(p)}  {human_size(f.stat().st_size)}")
            shown_total = len(files)

        dist = "，".join(f"{suf} {n}" for suf, n in suffixes.most_common(10)) or "无"
        body = "\n".join(lines) if lines else "(空目录)"
        more = f"\n…其余 {shown_total - max_entries} 条未列出" if shown_total > max_entries else ""
        return fmt(True, f"{header}\n类型分布（前 10）：{dist}\n明细：\n{body}{more}")

    except Exception as e:
        return fmt(False, f"列目录失败: {e}")


# =========================================================================== #
# 工具 2：读文件
# =========================================================================== #
@tool
def read_file(path: str, offset: int = 0, max_chars: int = 8000) -> str:
    """读取一个文件的文本内容（支持 pdf、docx 及任何纯文本：txt/md/代码/json/csv/日志等）。

    适用：用户要求阅读、总结、基于某份文档回答问题。文档不大时优先直接读全文，
    比知识库检索更准确。内容较长时会分段返回，按提示用 offset 继续读后面的部分。
    图片、压缩包、xlsx 等二进制文件无法读取，只会返回大小/修改时间等元信息。

    :param path: 文件的绝对路径
    :param offset: 从第几个字符开始读，默认 0（从头读）
    :param max_chars: 本次最多返回多少字符，默认 8000，上限 20000
    :return: "OK: 文件头信息 + 正文片段" 或 "FAIL: 无法读取的原因 + 元信息"
    """
    try:
        p = resolve_abs_path(path)
        if not p.is_file():
            return fmt(False, f"文件不存在或不是文件: {p}")

        text, note = read_text_any(p)
        if text is None:
            return fmt(False, f"无法读取内容：{note}。文件元信息：{describe_file(p)}")

        # TASK §5.3 L2：登记"这个会话读过这份内容"，写前校验据此发现"读后被改过"
        file_guard.record_read(current_session_id(), p)

        max_chars = max(1, min(max_chars, _READ_MAX_CHARS))
        start = max(0, offset)
        end = min(len(text), start + max_chars)
        header = f"{p}（{note}，共 {len(text)} 字符，本次返回第 {start}~{end} 字符）"
        tail = (
            f"\n…[还剩 {len(text) - end} 字符未读，如需继续请用 offset={end} 再次调用]"
            if end < len(text) else ""
        )
        return fmt(True, f"{header}\n{text[start:end]}{tail}")

    except Exception as e:
        return fmt(False, f"读取失败: {e}")


# =========================================================================== #
# 工具 3：在磁盘上搜文件
# =========================================================================== #
@tool
def grep_files(root: str, keyword: str, max_results: int = 30) -> str:
    """在磁盘目录里按关键字找文件：同时匹配文件名和文件内容（不区分大小写），不要求文件已导入知识库。

    适用："XXX 写在哪个文件里""哪些文件提到了 XXX""找名字带 XXX 的文件"。
    结果给出完整路径和命中行，方便直接告诉用户位置。
    关键字是普通子串匹配（不是正则、不懂近义词），找不到时可以换个说法/同义词再试。

    :param root: 搜索起点（目录或单个文件）的绝对路径
    :param keyword: 关键字，按子串匹配
    :param max_results: 最多返回多少个命中文件，默认 30
    :return: "OK: 命中文件列表（路径 + 命中行）" 或 "FAIL: 原因"
    """
    try:
        base = resolve_abs_path(root)
        kw = keyword.strip().lower()
        if not kw:
            return fmt(False, "关键字为空")
        if not base.exists():
            return fmt(False, f"路径不存在: {base}")

        stats = WalkStats()
        candidates = [base] if base.is_file() else walk_files(base, max_files=_MAX_WALK_FILES, stats=stats)

        results: list[str] = []
        scanned = 0
        for f in candidates:
            if len(results) >= max_results:
                stats.truncated = True
                break
            scanned += 1
            name_hit = kw in f.name.lower()
            line_hits: list[str] = []
            # 太大的文件只比较文件名，不读内容
            if f.stat().st_size <= _GREP_MAX_FILE_BYTES:
                text, _ = read_text_any(f)
                if text:
                    for no, line in enumerate(text.splitlines(), start=1):
                        if kw in line.lower():
                            line_hits.append(f"    第 {no} 行: {line.strip()[:160]}")
                            if len(line_hits) >= 3:      # 每个文件最多展示 3 行，防止刷屏
                                break
            if name_hit or line_hits:
                tag = "文件名+内容" if (name_hit and line_hits) else ("文件名" if name_hit else "内容")
                results.append("\n".join([f"[{tag}命中] {f}", *line_hits]))

        summary = f"在 {base} 中扫描 {scanned} 个文件，命中 {len(results)} 个"
        if stats.skipped_dirs:
            summary += f"（跳过 {stats.skipped_dirs} 个依赖/缓存目录）"
        if stats.skipped_system:
            summary += f"（跳过 {stats.skipped_system} 个系统文件/目录）"
        if stats.truncated:
            summary += "；⚠ 已达到上限，可能还有更多结果"
        if not results:
            return fmt(True, f"{summary}。没有找到包含「{keyword}」的文件")
        return fmt(True, summary + "\n" + "\n".join(results))

    except Exception as e:
        return fmt(False, f"搜索失败: {e}")


# =========================================================================== #
# 工具 4：查看知识库里有哪些文档
# =========================================================================== #
@tool
def list_indexed_docs(keyword: str = "", limit: int = 50) -> str:
    """列出 RAG 知识库里已经导入的文档：文件名、完整路径、切片数、导入时间。

    适用：用户问"知识库里有哪些文档 / 我导入过什么"，
    或者在删除、限定检索范围之前先确认目标的**确切文件名**（文件名写错是最常见的失败原因）。
    只读，不会改动任何东西。

    :param keyword: 可选，按文件名做子串过滤（不区分大小写）；为空表示列出全部
    :param limit: 最多列出多少条，默认 50
    :return: "OK: 文档列表（含总数）" 或 "OK: 知识库还是空的"
    """
    try:
        docs = all_indexed_docs()
        kw = keyword.strip().lower()
        if kw:
            docs = [d for d in docs if kw in d["name"].lower()]
        if not docs:
            scope_desc = f"文件名含「{keyword}」的" if kw else ""
            return fmt(True, f"知识库里没有{scope_desc}已导入的文档")
        lines = [
            f"[{i}] {d['name']}（{d['chunks']} 个切片，{human_size(d['file_size'])}）\n    {d['source']}"
            for i, d in enumerate(docs[:limit], start=1)
        ]
        more = f"\n…另有 {len(docs) - limit} 篇未列出" if len(docs) > limit else ""
        return fmt(True, f"知识库里共有 {len(docs)} 篇已导入文档：\n" + "\n".join(lines) + more)
    except Exception as e:
        return fmt(False, f"查询知识库文档列表失败: {e}")


# =========================================================================== #
# 工具 5：导入知识库
# =========================================================================== #
def _collect_indexable(p: Path) -> tuple[list[Path], Counter]:
    """收集待导入的文件，并统计被跳过的文件类型（告诉模型/用户哪些没导）。

    - p 是文件：pdf/docx 或任何非二进制文本都允许（用户明确点名了这个文件）
    - p 是文件夹：只收 _FOLDER_INDEX_SUFFIXES 内的文档类文件

    :param p: 已存在的文件或目录
    :return: (待导入文件列表, 被跳过文件的后缀计数)
    """
    skipped: Counter = Counter()
    if p.is_file():
        if p.suffix.lower() in RICH_DOC_SUFFIXES or not is_binary_file(p):
            return [p], skipped
        skipped[p.suffix.lower() or "(无后缀)"] += 1
        return [], skipped

    picked: list[Path] = []
    for f in walk_files(p, max_files=_MAX_WALK_FILES, stats=WalkStats()):
        if f.suffix.lower() in _FOLDER_INDEX_SUFFIXES:
            picked.append(f)
        else:
            skipped[f.suffix.lower() or "(无后缀)"] += 1
    return picked, skipped


@tool
def index_path(path: str, force: bool = False) -> str:
    """把文件或文件夹导入 RAG 知识库（解析、切片、向量化），之后可以用 rag_search 检索。

    适用：用户明确要求"导入/加入知识库/建立索引"，或者文档太大无法用 read_file 读完、需要检索时。
    只想"看看/统计/读一下"时不要调用本工具，用 list_dir / read_file 即可。
    文件夹只导入 pdf/docx/txt/md；单独指定的文件只要是文本都能导入。内容未变化的文件会自动跳过。

    :param path: 文件或文件夹的绝对路径；也可以传"已导入文档的文件名"（如 note.md）来重新导入它
    :param force: True 表示强制重新切片和向量化（"重新导入""刷新索引"时使用），默认 False
    :return: "OK: 导入统计" 或 "FAIL: 原因"
    """
    try:
        p = resolve_import_path(path)
        if not p.exists():
            return fmt(False, f"路径不存在: {p}")

        files, skipped = _collect_indexable(p)
        skipped_msg = (
            "；跳过不支持的类型：" + "，".join(f"{s} {n} 个" for s, n in skipped.most_common(8))
            if skipped else ""
        )
        if not files:
            return fmt(False, f"没有可导入的文档: {p}{skipped_msg}")

        # 逐个导入，遇到失败继续，最后汇总（避免第 100 个失败导致前 99 个白导）
        actions: Counter = Counter()
        fail_list: list[str] = []
        total_chunks = total_new = 0
        for f in files:
            try:
                enc = "utf-8" if f.suffix.lower() in RICH_DOC_SUFFIXES else (detect_text_encoding(f) or "utf-8")
                r = _svc.index_file(f, force=force, encoding=enc)
                actions[r.action] += 1
                total_chunks += r.total_chunks
                total_new += r.new_chunks
            except Exception as e:
                fail_list.append(f"{f.name}: {e}")

        ok_count = sum(actions.values())
        if ok_count == 0:
            return fmt(False, f"全部导入失败: {'; '.join(fail_list[:3])}")

        msg = (
            f"{p}：成功 {ok_count}/{len(files)} 个文件"
            f"（新建 {actions['created']}，更新 {actions['updated']}，未变化跳过 {actions['skipped']}），"
            f"总切片 {total_chunks}，新向量 {total_new}{skipped_msg}"
        )
        if fail_list:
            msg += f"；{len(fail_list)} 个失败: {'; '.join(fail_list[:3])}"
        return fmt(True, msg)

    except Exception as e:
        return fmt(False, f"导入失败: {e}")


# =========================================================================== #
# 工具 6：从知识库删除
# =========================================================================== #
@tool
def delete_index(path: str) -> str:
    """从 RAG 知识库删除某个文件、或某个文件夹下所有文件的导入记录（切片和向量一起删；磁盘上的原文件不受影响）。

    支持两种写法：
    - 已导入文档的文件名，如 note.md（不确定有哪些文档时先用 list_indexed_docs 看一眼）
    - 文件或文件夹的绝对路径

    这是不可恢复的操作：找到匹配的文档后，系统会自动弹窗列出将删除的文档请用户确认，
    用户同意才删除，拒绝则返回 FAIL。直接调用即可，不需要先在对话里征求同意。

    :param path: 要删除的范围：已导入文档的文件名，或文件/文件夹的绝对路径
    :return: "OK: 删除结果" 或 "FAIL: 原因（含用户拒绝）"
    """
    try:
        matched, _missing = match_indexed_docs([path])
        if not matched:
            return fmt(False, (
                f"知识库中没有与「{path}」匹配的导入记录。"
                f"可以先调用 list_indexed_docs 查看已导入文档的确切名字"
            ))

        names = "\n".join(f"  - {d['source']}" for d in matched[:20])
        more = f"\n  …共 {len(matched)} 篇" if len(matched) > 20 else ""
        # 以上都是只读查询；真正删除前暂停请用户确认（同意后本函数会从头重跑，再走到这里拿到决定）
        approved = ask_user(
            "delete_index", "确认删除知识库记录",
            f"将从知识库删除 {len(matched)} 篇文档（磁盘上的原文件不受影响）：\n{names}{more}",
            {"path": path},
        )
        if not approved:
            return fmt(False, f"用户拒绝删除，知识库中 {len(matched)} 篇文档保持不变")

        deleted = _svc.delete_by_ids([d["id"] for d in matched])
        return fmt(True, f"已从知识库删除 {deleted} 篇文档：\n{names}{more}")

    except GraphBubbleUp:
        raise  # interrupt() 发出的"暂停等待确认"信号，必须交给 LangGraph 处理
    except Exception as e:
        return fmt(False, f"删除失败: {e}")



@tool
def rag_search(query: str, top_k: int = 5, scope: list[str] | None = None) -> str:
    """在 RAG 知识库（已导入的文档）中检索与问题相关的片段，结果带完整文件路径和相关度。

    适用：基于已导入文档回答问题、找"关于 XXX 的内容在哪个文件"。
    用户指定了文档/文件夹时，务必传 scope 限定范围，避免其它文档混进来。
    检索基于字面相似度，问题和文档用词差异大时可能漏检：可换关键词再搜，或改用 read_file 读原文。
    结果为空时如实告知用户，不要编造。

    :param query: 检索关键词或完整问题
    :param top_k: 返回片段条数，默认 5
    :param scope: 可选，限定检索范围：文件/文件夹的绝对路径，或已导入文档的文件名
    :return: "OK: 片段列表（路径、片段序号、相关度、原文）" 或 "FAIL: 原因"
    """
    try:
        sources = None
        scope_msg = "全部知识库"
        if scope:
            sources, missing = resolve_scope(scope)
            if not sources:
                return fmt(False, (
                    f"范围 {scope} 内没有已导入的文档；"
                    f"可以先用 list_indexed_docs 确认文档名，或用 index_path 把它导进来"
                ))
            scope_msg = f"{len(sources)} 篇指定文档"
            if missing:
                scope_msg += f"（未找到: {missing}）"

        hits = _svc.search(query, top_k=top_k, sources=sources)
        if not hits:
            return fmt(True, f"在{scope_msg}中未检索到与「{query}」相关的内容")

        parts = [
            f"[{i}] {h.source}（片段 #{h.chunk_index}，相关度 {h.score:.3f}）\n{h.text}"
            for i, h in enumerate(hits, start=1)
        ]
        return fmt(True, f"在{scope_msg}中检索到 {len(hits)} 个片段：\n\n" + "\n\n".join(parts))

    except Exception as e:
        return fmt(False, f"检索失败: {e}")


# 本模块对外暴露的工具列表，由 app/agents/rag_agent.py 与写文件工具合并后交给 agent；
# 顺序 = 提示词里【工具速查】的顺序：先只读、再知识库管理、最后检索
READ_TOOLS = [list_dir, read_file, grep_files, list_indexed_docs, index_path, delete_index, rag_search]
