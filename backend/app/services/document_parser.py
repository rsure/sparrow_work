# app/services/document_parser.py
"""文档解析注册表（EXT-4 阶段 1）：把「哪种后缀用哪个解析器」收口到一处。

改造前的问题（不是"不支持 xlsx"这么简单）：
    「哪些后缀算结构化文档」这件事散在 5 个地方——
        rag_store_service.load_file_text   的 if/elif 后缀链
        tool_utils.RICH_DOC_SUFFIXES
        file_read_tool._FOLDER_INDEX_SUFFIXES
        file_write_tool 的富文本判断
        file_browse_service._kind_of
    加一种格式要改一圈，而且很容易只改一半（比如 read_file 支持了、索引没支持）。
    于是同一个文件"能读但导不进知识库"这种割裂现象会长期存在。

改法：所有判断都从本注册表派生，新增格式 = 写 1 个 parser + 注册 1 行。

两类后缀的区别（很重要）：
    structured=True   —— 二进制/富文本（pdf、docx…）：**不能**按字节解码成文本，
                          必须走专用解析器；写文件时也要拒绝直接写。
    structured=False  —— 纯文本类（txt、md…）：按编码解码，失败可容错。

未注册的后缀仍会走"纯文本兜底"（保留改造前行为）：用户把 `.log`、`.csv` 丢进来时
我们不知道它是什么编码，但按文本试读一次通常是对的。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：dataclass 描述解析器、Path 表示文件路径、Callable 标注解析函数
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# 标准库：日志（解析失败要能看到原因，而不是抛给用户一串堆栈）
import logging

# 本模块专用 logger
log = logging.getLogger("services.document_parser")

# 纯文本解析时依次尝试的编码（gb18030 是 GBK 超集，覆盖 Windows 中文文件）
TEXT_ENCODINGS: tuple[str, ...] = ("utf-8", "gb18030")

# Excel 解析上限：单个 sheet 最多读多少行/列。
# 为什么要限：一个 10 万行的表读成文本是几十 MB，进模型等于直接把窗口打满；
# 截断比"读半小时然后失败"对用户更有用，提示里会写明截断位置。
MAX_XLSX_ROWS = 5_000
MAX_XLSX_COLS = 40


@dataclass(frozen=True)
class ParserSpec:
    """一个后缀对应的解析器。"""

    # 后缀（小写、带点，如 ".pdf"）
    suffix: str
    # 解析函数：输入文件路径，输出纯文本（多页/多段用 \n\n 分隔）
    parse: Callable[[Path], str]
    # 是否为结构化（二进制/富文本）：True 表示不能按文本解码、写文件时要拒绝
    structured: bool = False
    # 人类可读的格式名，用于提示文案（如 "PDF 文档"）
    label: str = ""


# 后缀 → 解析器。模块导入时由 _install_builtin_parsers() 填充。
PARSERS: dict[str, ParserSpec] = {}


def register_parser(
    suffix: str,
    parse: Callable[[Path], str],
    *,
    structured: bool = False,
    label: str = "",
    replace: bool = False,
) -> None:
    """注册（或替换）一个后缀的解析器。

    :param suffix: 后缀，大小写不敏感，内部统一小写
    :param parse: 解析函数（Path -> str）
    :param structured: 是否结构化格式
    :param label: 展示名
    :param replace: 已存在时是否覆盖；False 时抛 ValueError（防止两个模块抢同一后缀）
    :raises ValueError: 后缀非法 / 重复注册且未允许覆盖
    """
    key = (suffix or "").strip().lower()
    if not key.startswith(".") or len(key) < 2:
        raise ValueError(f"后缀必须以点开头（如 '.pdf'），收到 {suffix!r}")
    if key in PARSERS and not replace:
        raise ValueError(f"后缀 {key} 已有解析器，如需替换请传 replace=True")
    PARSERS[key] = ParserSpec(suffix=key, parse=parse, structured=structured, label=label or key)


def _parse_pdf(path: Path) -> str:
    """用 PyPDFLoader 逐页提取 PDF 文本。"""
    # 项目内：延迟导入 —— PDF 解析依赖较重，只有真解析时才加载
    from langchain_community.document_loaders import PyPDFLoader

    docs = PyPDFLoader(str(path)).load()
    return "\n\n".join(d.page_content for d in docs)


def _parse_docx(path: Path) -> str:
    """用 Docx2txtLoader 提取 .docx 文本（含表格里的文字）。"""
    from langchain_community.document_loaders import Docx2txtLoader

    docs = Docx2txtLoader(str(path)).load()
    return "\n\n".join(d.page_content for d in docs)


def _parse_xlsx(path: Path) -> str:
    """把 .xlsx 逐 sheet 读成「[Sheet 名] + 行文本」。

    三个取舍：
        - `data_only=True`：公式取**缓存值**（Excel 算过的结果），而不是 "=A1+B1"；
        - `read_only=True`：流式读取，避免大表整份进内存；
        - 行/列都设上限：超出部分显式标注截断，模型与用户都能看出"这里不全"。
    """
    # 项目内：延迟导入 —— openpyxl 只在真解析 Excel 时加载（打包时已列入 hiddenimports）
    from openpyxl import load_workbook

    workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        parts: list[str] = []
        for sheet in workbook.worksheets:
            lines: list[str] = []
            for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if index > MAX_XLSX_ROWS:
                    lines.append(f"…（超过 {MAX_XLSX_ROWS} 行，已截断）")
                    break
                cells = ["" if value is None else str(value) for value in row[:MAX_XLSX_COLS]]
                # 整行空白就跳过：Excel 里大量空行会让切片变得很碎
                if any(cell.strip() for cell in cells):
                    lines.append(" | ".join(cells).rstrip())
            if not lines:
                continue
            parts.append(f"[Sheet {sheet.title}]\n" + "\n".join(lines))
        return "\n\n".join(parts)
    finally:
        workbook.close()


def _parse_text(path: Path, encoding: str = "utf-8") -> str:
    """按文本读取：先按指定编码，失败再依次尝试 TEXT_ENCODINGS，最后容错解码。

    为什么不用 TextLoader：它对编码不符直接抛 RuntimeError，而我们希望"尽力读出来"——
    用户丢进来的 .txt 可能是 GBK、也可能是混编码的日志，读出来有乱码也好过整份失败。
    """
    data = path.read_bytes()
    text = ""
    for enc in [encoding, *TEXT_ENCODINGS]:
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if not text:
        # 全部失败：容错解码（会有乱码，但至少能入库、能被检索到部分关键词）
        text = data.decode("utf-8", errors="replace")
    # 统一换行符：Windows 文件是 \r\n，而切分器的分隔符写的是 "\n\n"。
    # 不归一化的话，"\n\n" 永远匹配不到 "\r\n\r\n"，整篇会被当成一个巨型片段。
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---- EXT-4：Office 家族统一委托本地 Office 引擎 -------------------------------- #
# 这一层只做"选路 + 降级"两件事，真正的解析在 app/services/office_cli.py：
#     office 引擎可用 → 走引擎（能读到表格、页、方框、批注）
#     引擎不可用     → 回落到改造前的解析器（行为与改造前一致）
# 把选路放在这里而不是注册表里，是因为注册表只认"后缀 → 函数"，
# 而"引擎在不在"是运行期才知道的事。

# 降级结果的统一前缀：RAG 入库侧（rag_store_service.index_file）看到它就拒绝入库，
# 否则二进制文件被当文本硬读出来的乱码会进知识库，之后每次检索都会命中一堆噪声。
DEGRADED_PREFIX = "[降级读取] "

# 引擎明确不支持、但用户手上很可能有的 Office 家族后缀 → 建议另存成的目标格式。
# 不注册进 PARSERS 是有意的：注册了就等于"声称能读"，而实际上只能读出一堆乱码。
UNSUPPORTED_OFFICE_SUFFIXES: dict[str, str] = {
    ".rtf": ".docx",
    ".odt": ".docx",
    ".et": ".xlsx",
    ".dps": ".pptx",
}


class UnsupportedOfficeFormat(ValueError):
    """后缀属于 Office 家族但引擎不支持（.rtf/.odt/.et/.dps），提示用户另存。"""


def is_degraded(text: str) -> bool:
    """判断一份解析结果是不是"降级读取"（引擎不可用时的文本兜底）。

    为什么要单独判：降级结果里有大量乱码，入库会污染检索。调用方据此跳过，
    而不是把前缀当正文一起切碎存起来。

    :param text: parse_document 的返回值
    :return: 是降级结果返回 True
    """
    return text.startswith(DEGRADED_PREFIX)


def _office_read(path: Path, kind: str, legacy: Callable[[Path], str]) -> str:
    """Office 文档的统一入口：优先用本地引擎解析，不可用时回落到 legacy。

    :param path: 文件路径
    :param kind: 品类，``doc`` / ``sheet`` / ``slide``
    :param legacy: 降级时使用的旧解析器（``_parse_text`` 表示没有专用旧实现）
    :return: 解析出的文本
    """
    # 项目内：延迟导入 —— 只有真解析 Office 文件时才需要 httpx 与引擎适配层
    from app.services import office_cli

    if not office_cli.enabled():
        # 用户关掉了 office.enabled：完全按改造前的方式解析，连探测都不做
        return legacy(path)

    readers = {
        "doc": office_cli.read_doc,
        "sheet": office_cli.read_sheet,
        "slide": office_cli.read_slide,
    }
    try:
        return readers[kind](path)
    except office_cli.OfficeCliUnavailable as exc:
        # 引擎没启动/没装/打不开这个文件：不是错误，退回旧实现即可
        log.info("Office 引擎不可用（%s），%s 改用旧解析器：%s", kind, path.name, exc)
    except Exception:
        # 引擎的内部错误也不该让"打开一个文档"整体失败
        log.warning("Office 引擎解析 %s 失败，改用旧解析器", path, exc_info=True)

    if legacy is _parse_text:
        # 没有专用旧实现：只能按文本硬读，二进制内容一定是乱码。
        # 加 [降级读取] 前缀是给 RAG 入库侧看的——它据此跳过，避免把乱码灌进知识库。
        return f"{DEGRADED_PREFIX}{_parse_text(path)}"
    try:
        return legacy(path)
    except Exception:
        # .doc/.wps 这类老二进制格式旧解析器也读不了：最后还是只能文本兜底
        log.info("旧解析器也读不了 %s，最后回落文本读取", path.name, exc_info=True)
        return f"{DEGRADED_PREFIX}{_parse_text(path)}"


def _parse_doc_office(path: Path) -> str:
    """Word 品类（.docx/.doc/.dot/.wps/.wpt/.docm）：引擎读结构树，否则回落 docx2txt。"""
    return _office_read(path, "doc", _parse_docx)


def _parse_sheet_office(path: Path) -> str:
    """Excel 品类（.xlsx/.xls/.xlt/.xlsm）：引擎逐子表读，否则回落 openpyxl。"""
    return _office_read(path, "sheet", _parse_xlsx)


def _parse_slide_office(path: Path) -> str:
    """PPT 品类（.pptx/.ppt/.pps/.pot）：引擎逐页读；没有旧实现，最后只能文本兜底。"""
    return _office_read(path, "slide", _parse_text)


def _install_builtin_parsers() -> None:
    """注册内置解析器（幂等）。新增格式时在这里加一行。"""
    register_parser(".pdf", _parse_pdf, structured=True, label="PDF", replace=True)
    # 纯文本类：同一套解码逻辑，注册成多个后缀便于 _FOLDER_INDEX_SUFFIXES 派生
    for suffix in (".txt", ".md", ".markdown"):
        register_parser(suffix, _parse_text, label="文本", replace=True)
    # ---- EXT-4：Office 家族（doc / sheet / slide 三个品类）----
    # 后缀表负责"这个文件算什么类型、要不要拒绝直接写"，真正的品类由引擎按文件头判断。
    # 所以这里把同品类的后缀一次注册全（.doc/.wps 是 Word 的，.xls 是 Excel 的……），
    # 都不需要各写一个解析器 —— 它们只是同一个入口的不同后缀。
    for suffix in (".docx", ".doc", ".dot", ".wps", ".wpt", ".docm"):
        register_parser(suffix, _parse_doc_office, structured=True, label="Word 文档", replace=True)
    for suffix in (".xlsx", ".xls", ".xlt", ".xlsm"):
        register_parser(suffix, _parse_sheet_office, structured=True, label="Excel 表格", replace=True)
    for suffix in (".pptx", ".ppt", ".pps", ".pot"):
        register_parser(suffix, _parse_slide_office, structured=True, label="PPT 演示", replace=True)


_install_builtin_parsers()


def supported_suffixes() -> frozenset[str]:
    """返回已注册解析器的后缀集合（由注册表派生，改动注册表即生效）。

    :return: 后缀集合（小写、带点）
    """
    return frozenset(PARSERS)


def structured_suffixes() -> frozenset[str]:
    """返回"结构化格式"的后缀集合（pdf/docx…）。

    用途：写文件时拒绝覆盖这类文件；工具层判断"能不能按文本解码"也用它。

    :return: 后缀集合
    """
    return frozenset(key for key, spec in PARSERS.items() if spec.structured)


def is_structured(path: Path | str) -> bool:
    """判断某个路径是不是结构化格式（按后缀）。

    :param path: 文件路径
    :return: 是结构化格式返回 True
    """
    suffix = Path(path).suffix.lower()
    spec = PARSERS.get(suffix)
    return bool(spec and spec.structured)


def parse_document(path: Path, encoding: str = "utf-8") -> str:
    """统一解析入口：按后缀找解析器；未注册的后缀按纯文本兜底。

    :param path: 文件路径
    :param encoding: 纯文本类文件的首选编码（pdf/docx 不使用）
    :return: 文件全文
    :raises UnsupportedOfficeFormat: 后缀是 Office 家族但引擎不支持（.rtf/.odt/.et/.dps）
    :raises OSError: 文件读不到
    """
    suffix = path.suffix.lower()
    hint = UNSUPPORTED_OFFICE_SUFFIXES.get(suffix)
    if hint is not None:
        # 不给"文本硬读"机会：.rtf/.odt 这类容器格式硬读出来是乱码，还不如直接告诉用户怎么办
        raise UnsupportedOfficeFormat(
            f"暂不支持直接读取 {suffix} 文件（{path.name}），"
            f"请用 Office / WPS 另存为 {hint} 后再导入"
        )
    spec = PARSERS.get(suffix)
    if spec is None:
        # 未注册后缀：按文本试读（保留改造前"其余扩展名一律当文本"的行为）
        return _parse_text(path, encoding)
    if spec.parse is _parse_text:
        return _parse_text(path, encoding)
    try:
        return spec.parse(path)
    except UnsupportedOfficeFormat:
        # 明确"不支持"的格式不降级：降级只会把乱码当正文交出去
        raise
    except Exception:
        # 结构化解析失败（PDF 加密、docx 损坏）：记日志并回落文本试读，
        # 让"至少能读到一点"优于"整份读不了"
        log.warning("解析 %s 失败，回落到文本读取", path, exc_info=True)
        return _parse_text(path, encoding)
