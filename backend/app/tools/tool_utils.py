# app/tools/tool_utils.py
"""
Agent 工具的公共底座：统一返回格式、路径校验、目录遍历、"任意文件尽量读成文本"。

设计思路（为什么要有这个文件）：
    用户的问题无法穷举，所以工具按"能力"拆成原子操作（列目录 / 读文件 / 搜索 / 写文件…），
    由模型自己组合。这些原子工具都要用到同样的几件事，集中放在这里：
    1. fmt：统一 "OK: ..." / "FAIL: ..." 返回格式，模型一眼能看出成败
    2. resolve_abs_path：只接受绝对路径，相对路径直接拒绝（后端工作目录不是用户心里的目录）；
       系统文件 / 系统目录一律拒绝（见 system_path_reason）
    3. walk_files：递归遍历时跳过 node_modules / .git 等巨型目录和系统项，并设上限防止卡死
    4. read_text_any：已知格式用专用解析器，未知格式尝试按文本解码，二进制只返回元信息
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、list[str] 等新语法
from __future__ import annotations

# 标准库：codecs.BOM_UTF8 用来识别带 BOM 的 UTF-8 文件（写回时要保留 BOM）
import codecs
# 标准库：os.walk 递归遍历时可以原地裁剪子目录（rglob 做不到），os.path.normcase 做路径大小写归一
import os
# 标准库：把文件修改时间戳格式化成人能读的本地时间
from datetime import datetime
# 标准库：路径对象，取后缀 / 判断文件或目录 / 读字节
from pathlib import Path
# 标准库：Iterator 标注 walk_files 这种"边遍历边产出"的生成器返回类型
from typing import Iterator

# LangGraph 人工确认：interrupt(payload) 暂停 Agent，把 payload 交给前端，恢复时返回用户的决定
from langgraph.types import interrupt

# 项目内：文档解析注册表（EXT-4）——pdf/docx 解析与"哪些后缀算富文本"都由它一处决定，
# 工具层不再各自维护后缀白名单（改造前这里 import 的是 RAG 服务，顺带把向量库依赖拖进了工具层）
from app.services.document_parser import (
    UNSUPPORTED_OFFICE_SUFFIXES,
    parse_document,
    structured_suffixes,
)
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
# 需要专用解析器的富文本格式（不能直接按字节解码）。
# 由解析注册表派生：注册一个新格式，工具层、写保护、预览分类会同时生效。
RICH_DOC_SUFFIXES = structured_suffixes()

# 递归遍历时默认跳过的目录名：依赖 / 缓存 / 版本库，体积大且对用户问题几乎没有价值
IGNORED_DIR_NAMES = {
    "node_modules", ".git", ".svn", ".hg", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "dist", "build", ".pytest_cache",
}

# 判断二进制时只看文件开头这么多字节（单位：字节），足够覆盖文件头又不至于读整份大文件
BINARY_SNIFF_BYTES = 8192

# 纯文本解码依次尝试的编码（带 BOM 的 UTF-8 另行识别为 utf-8-sig）；gb18030 是 GBK 的超集，覆盖 Windows 中文文件
TEXT_ENCODINGS = ("utf-8", "gb18030")

# read_text_any 允许读取的最大文件体积（单位：字节，20MB），再大就只返回元信息，防止撑爆内存和上下文
MAX_READ_BYTES = 20 * 1024 * 1024


def _env_dirs(*names: str) -> list[Path]:
    """按环境变量名取出目录路径，未设置的变量直接忽略（不同机器 / 系统上存在的变量不一样）。

    :param names: 环境变量名，如 "SystemRoot"
    :return: 已设置的目录路径列表
    """
    return [Path(os.environ[n]) for n in names if os.environ.get(n)]


# 系统目录：任何工具（读、搜、导入、写）都不允许进入。
# Windows 用环境变量取真实位置（系统盘不一定是 C:）；非 Windows 给出常见系统目录
if os.name == "nt":
    SYSTEM_DIRS = _env_dirs("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData") \
        or [Path(r"C:\Windows")]
else:
    SYSTEM_DIRS = [Path(d) for d in ("/bin", "/sbin", "/boot", "/dev", "/etc", "/proc", "/sys", "/usr", "/System", "/Library")]

# 各盘根目录下的系统项（名字小写）：回收站、还原点、启动文件、虚拟内存 / 休眠文件等
ROOT_SYSTEM_NAMES = {
    "$recycle.bin", "system volume information", "recovery", "boot", "bootmgr",
    "$windows.~bt", "$windows.~ws", "$winreagent", "config.msi",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp",
}

# Windows 文件属性中的"系统"位（FILE_ATTRIBUTE_SYSTEM），带这个属性的文件 / 目录由系统维护
_FILE_ATTRIBUTE_SYSTEM = 0x4
# Windows 文件属性中的"目录"位（FILE_ATTRIBUTE_DIRECTORY），用来区分系统属性落在文件还是目录上
_FILE_ATTRIBUTE_DIRECTORY = 0x10


# --------------------------------------------------------------------------- #
# 返回格式
# --------------------------------------------------------------------------- #
def fmt(success: bool, msg: str) -> str:
    """统一工具返回格式，让模型通过前缀直接判断成败，失败时能把原因转述给用户。

    :param success: 业务是否成功
    :param msg: 结果说明（中文，模型能直接理解）
    :return: "OK: ..." 或 "FAIL: ..."
    """
    return f"{'OK' if success else 'FAIL'}: {msg}"


# --------------------------------------------------------------------------- #
# 人工确认（human-in-the-loop）
# --------------------------------------------------------------------------- #
def _ask(
    tool_name: str,
    title: str,
    message: str,
    args: dict,
    *,
    allow_remember: bool = False,
) -> dict:
    """发起一次人工确认（interrupt），把用户的原始决定字典返回给调用方。

    为什么单独抽一层：确认有两种消费方式——只要"同不同意"（大多数工具），
    或还要"记不记住本工作区授权"（UX-7 的 workspace 模式）。抽出来后两种都能复用同一份 payload。

    :param tool_name: 触发确认的工具名
    :param title: 弹窗标题
    :param message: 弹窗正文（影响范围说明）
    :param args: 展示给用户的关键参数
    :param allow_remember: 是否在弹窗里提供「记住本工作区授权」勾选（仅 workspace 模式为 True）
    :return: LangGraph 恢复时传回的字典；非字典（旧前端/脚本）时返回空字典
    """
    payload = {
        "tool": tool_name,
        "title": title,
        "message": message,
        "args": args,
        # UX-7：前端据此决定是否渲染「记住本工作区授权」勾选框
        "can_remember": allow_remember,
    }
    decision = interrupt(payload)
    return decision if isinstance(decision, dict) else {}


def ask_user(
    tool_name: str,
    title: str,
    message: str,
    args: dict,
    *,
    allow_remember: bool = False,
) -> bool:
    """暂停 Agent 请用户确认有风险的操作（覆盖/修改文件、删除知识库记录），返回用户是否同意。

    原理：interrupt() 抛出 GraphInterrupt 让整张图暂停，chat_controller 把 payload 作为
    SSE 的 confirm_required 事件推给前端；用户点了同意/拒绝后，前端调 /chat/resume，
    LangGraph 重新执行调用本函数的那个工具，这一次 interrupt() 直接返回 {"approved": bool}。

    payload 字段与前端 ConfirmRequiredEvent 一一对应：tool / title / message / args / can_remember。
    调用方须知：本函数之前只能做只读校验；工具的 except Exception 要先放行 GraphBubbleUp。

    :param tool_name: 触发确认的工具名
    :param title: 弹窗标题
    :param message: 弹窗正文（影响范围说明）
    :param args: 展示给用户的关键参数（长文本应先截断）
    :param allow_remember: 是否提供「记住本工作区授权」选项（见 ask_user_decide）
    :return: True=用户同意；False=用户拒绝
    """
    return bool(_ask(tool_name, title, message, args, allow_remember=allow_remember).get("approved"))


def ask_user_decide(
    tool_name: str,
    title: str,
    message: str,
    args: dict,
    *,
    allow_remember: bool = False,
) -> tuple[bool, bool]:
    """人工确认的"完整版"：同时返回是否同意与是否记住授权（UX-7 workspace 模式用）。

    :param tool_name: 触发确认的工具名
    :param title: 弹窗标题
    :param message: 弹窗正文
    :param args: 展示给用户的关键参数
    :param allow_remember: 是否允许"记住本工作区"
    :return: (approved, remember)；remember 在 allow_remember=False 时恒为 False
    """
    decision = _ask(tool_name, title, message, args, allow_remember=allow_remember)
    approved = bool(decision.get("approved"))
    remember = bool(decision.get("remember")) and allow_remember
    return approved, remember


def ask_budget(dimension: str, current: float, limit: float) -> bool:
    """预算熔断的询问（UX-9）：本轮已超阈值，问用户「继续 / 停止」。

    复用同一个 interrupt 链路：chat_controller 看到 payload 里 `kind="budget"`，
    会把事件名换成 `budget_exceeded`（前端据此弹"继续 / 停止"而不是"同意 / 拒绝"）。

    :param dimension: 超限维度：tokens / cost / duration
    :param current: 当前累计值（单位随维度）
    :param limit: 阈值（单位随维度）
    :return: True=用户选择继续；False=用户选择停止
    """
    if dimension == "tokens":
        text = f"本轮已使用约 {int(current)} tokens，超过阈值 {int(limit)} tokens。"
    elif dimension == "cost":
        text = f"本轮已花费约 {current:.2f} 元，超过阈值 {limit:.2f} 元。"
    else:
        text = f"本轮已运行约 {current:.1f} 分钟，超过阈值 {limit:.0f} 分钟。"
    decision = interrupt({
        # 事件类型标记：chat_controller 据此把 confirm_required 换成 budget_exceeded
        "kind": "budget",
        "dimension": dimension,
        "current": current,
        "limit": limit,
        "title": "预算已超出",
        "message": f"{text}\n可以继续执行（本轮不再就这个维度提醒），或停止本轮。",
    })
    return bool(isinstance(decision, dict) and decision.get("approved"))


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def resolve_abs_path(raw: str) -> Path:
    """把模型传进来的路径字符串规范成绝对路径；不是绝对路径时直接报错。

    为什么拒绝相对路径：后端进程的工作目录是 backend/，用户说的 "docs 目录"
    在后端看来会变成 backend/docs，很容易读错地方甚至写错地方。
    报错信息会提示模型去向用户要完整路径（这本身就是一种"有歧义就追问"）。

    所有工具都经过这里取路径，因此"系统文件不允许处理"的限制也放在这里统一拦截。

    :param raw: 原始路径字符串，允许带首尾空格/引号和 ~（用户主目录）
    :return: 已 resolve 的绝对路径（不保证存在，调用方自行判断）
    :raises ValueError: 路径为空或不是绝对路径
    :raises PermissionError: 路径属于系统文件 / 系统目录
    """
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("路径为空")
    p = Path(text).expanduser()
    if not p.is_absolute():
        raise ValueError(f"需要绝对路径（如 D:\\docs），收到的是相对路径: {raw}；请向用户确认完整路径")
    # 用 resolve() 而不是 absolute()：它会解析符号链接，避免"软链接指向系统目录"绕过检查。
    p = p.resolve()
    reason = system_path_reason(p)
    if reason:
        raise PermissionError(f"{reason}，系统文件不允许读取、搜索、导入或修改")
    return p


def same_or_under(path: str | Path, base: str | Path) -> bool:
    """判断 path 是否就是 base，或位于 base 目录之下（Windows 下大小写不敏感）。

    用于"按文件夹删除索引""限定检索范围""禁止写入受保护目录"等场景。

    :param path: 被检查的路径
    :param base: 基准文件或目录
    :return: path == base 或 path 在 base 子树内时为 True
    """
    p = os.path.normcase(str(Path(path)))
    b = os.path.normcase(str(Path(base)))
    return p == b or p.startswith(b.rstrip("\\/") + os.sep)


def system_path_reason(p: Path) -> str | None:
    """判断路径是不是系统文件 / 系统目录，是的话说明原因。三条规则任一命中即算：

    1. 位于 SYSTEM_DIRS 之下（Windows 目录、Program Files、ProgramData 等）
    2. 是某个盘根目录下的系统项，或位于其中（回收站、System Volume Information、pagefile.sys 等）
    3. 文件本身带 Windows "系统"属性（如 desktop.ini、thumbs.db；目录上的系统属性不算）

    :param p: 绝对路径（不要求存在；不存在时跳过第 3 条）
    :return: 命中时返回原因；不是系统路径返回 None
    """
    for d in SYSTEM_DIRS:
        if same_or_under(p, d):
            return f"{p} 位于系统目录 {d}"
    parts = p.parts
    # parts[0] 是盘符根（如 "C:\\"），parts[1] 是根目录下的第一层名字
    if len(parts) >= 2 and parts[1].lower() in ROOT_SYSTEM_NAMES:
        return f"{p} 属于磁盘根目录下的系统项 {parts[1]}"
    try:
        # st_file_attributes 只在 Windows 上存在；lstat 不跟随链接，读的是链接本身的属性。
        # 只对文件生效：盘根目录（C:\）和用户自定义过图标的普通文件夹也会带"系统"属性，不能误伤
        attrs = getattr(p.lstat(), "st_file_attributes", 0)
        if attrs & _FILE_ATTRIBUTE_SYSTEM and not attrs & _FILE_ATTRIBUTE_DIRECTORY:
            return f"{p} 带有系统文件属性"
    except OSError:
        pass  # 不存在或无权限读取属性：交给调用方后续的存在性检查处理
    return None

# --------------------------------------------------------------------------- #
# 路径策略：声明式规则表（写保护 / 执行保护的唯一出处）
# --------------------------------------------------------------------------- #
# 为什么做成"数据表"而不是一串 if：
#   工具会越来越多（写文件、改文件、删除、执行命令……），每加一个就抄一遍 if 一定会漏。
#   把"哪些目录、允许哪些操作"写成数据，新增工具只要调用 path_decision 就自动获得全部规则。
#
# 目前只用到"写"和"执行"两类判定；"读"一律放行（系统目录已在 resolve_abs_path 拦截）。

# 本后端工程根目录（backend/）：app/tools/tool_utils.py → 向上两级
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 运行期允许写入/执行的根目录白名单；为空表示"除系统目录与受保护目录外均可写"。
# ARCH-3 之后它不再由前端传入，而是由**当前 active 工作区**的根目录并集驱动：
# services/workspace_settings_defs.py 订阅了 workspaces.* 变更事件，
# 切换工作区时会调用下面的 refresh_workspace_roots() 就地刷新本列表。
WORKSPACE_ROOTS: list[Path] = []


def refresh_workspace_roots() -> list[Path]:
    """按「当前 active 工作区」刷新写/执行白名单 WORKSPACE_ROOTS，并返回刷新后的列表。

    为什么要"就地刷新"而不是重新绑定一个列表：
        path_decision 每次调用都读模块级 WORKSPACE_ROOTS，而其它模块可能
        `from app.tools.tool_utils import WORKSPACE_ROOTS` 持有同一个列表对象。
        用 `WORKSPACE_ROOTS[:] = ...` 原地改内容，所有持有者都能立刻看到新白名单。

    读不到工作区（数据库未就绪 / 一个工作区都没有）时清空白名单，
    即"不限制"——这是改造前 WORKSPACE_ROOTS 一直为空时的既有行为，不引入新的行为差异。

    :return: 刷新后的 WORKSPACE_ROOTS（同一个列表对象）
    """
    try:
        # 项目内：延迟导入工作区服务。它会读数据库，而本模块被大量工具在导入期使用，
        # 直接顶层 import 容易在启动早期把数据库依赖带进来
        from app.services.workspace_service import get_active_roots

        roots = get_active_roots()
    except Exception:
        # 工作区读不到时按"不限制"处理，绝不因为配置读失败而挡掉所有工具调用
        roots = []
    # 统一成绝对路径对象后原地覆盖，保证拿到的一定是 Path 列表
    WORKSPACE_ROOTS[:] = [Path(p) for p in roots]
    return WORKSPACE_ROOTS


@dataclass(frozen=True)
class PathRule:
    """一条路径策略：某个目录（含其子树）允许做哪些操作。"""

    # 规则作用的根目录（绝对路径），其下所有子孙都受本规则约束
    root: Path
    # 允许的操作集合，取值见 ALLOWED_OPS；未列出的操作一律拒绝
    allow: frozenset[str]
    # 拒绝时给模型看的原因（要写清"这是什么目录、为什么不能动"）
    reason: str


# 允许的操作名（用字符串而不是枚举：写进日志、传给前端都直观）
OP_READ = "read"      # 读文件内容、列目录、搜索
OP_WRITE = "write"    # 新建 / 覆盖 / 修改 / 删除 / 移动文件
OP_EXEC = "exec"      # 以该路径为工作目录或参数去执行命令

# 受保护目录表：按顺序匹配，第一条命中的规则生效，所以"更具体的规则要放在前面"
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        root=BACKEND_ROOT,
        allow=frozenset({OP_READ}),
        reason=f"{BACKEND_ROOT} 是本后端自身的源码目录，允许读取、禁止改写与执行",
    ),
)


def path_decision(p: Path, op: str, roots: list[Path] | None = None) -> str | None:
    """判断某个绝对路径是否允许执行某类操作；不允许时说明原因。

    判定顺序（先紧后松）：
        1. 规则表命中 → 看该规则是否允许这个操作；不允许就拒绝（例如 backend 只许读）
        2. 未命中规则 → 若配置了工作区白名单，则要求路径落在白名单内；没配置则放行

    调用方：写盘 / 删除 / 移动前调 op=OP_WRITE；执行命令前对工作目录、以及命令里出现的路径参数调 op=OP_EXEC。
    读操作不需要调用它——系统目录已在 resolve_abs_path 里统一拒绝。

    :param p: 已经过 resolve 的绝对路径（调用方保证）
    :param op: 操作类型，取值 OP_READ / OP_WRITE / OP_EXEC
    :return: 允许时返回 None；不允许时返回中文原因（可直接作为工具的 FAIL 文案）
    """
    for rule in PATH_RULES:
        if same_or_under(p, rule.root):
            if op in rule.allow:
                return None
            return f"{p} 位于受保护目录 {rule.root}，禁止 {op} 操作（{rule.reason}）"

    effective_roots = list(roots) if roots is not None else WORKSPACE_ROOTS

    # 没命中受保护规则：工作区白名单只约束"有副作用"的操作，读一律放行
    if op == OP_READ or not WORKSPACE_ROOTS:
        return None
    if any(same_or_under(p, root) for root in WORKSPACE_ROOTS):
        return None
    allowed = "、".join(str(r) for r in WORKSPACE_ROOTS)
    return f"{p} 不在允许的工作区（{allowed}）内，禁止 {op} 操作"

# --------------------------------------------------------------------------- #
# 遍历
# --------------------------------------------------------------------------- #
class WalkStats:
    """walk_files 遍历过程中的附带统计，遍历结束后由调用方读取并告诉模型。"""

    def __init__(self) -> None:
        """初始化各项计数为 0。"""
        # 因命中 IGNORED_DIR_NAMES 而被整体跳过的目录个数
        self.skipped_dirs = 0
        # 因属于系统文件 / 系统目录而被跳过的条目个数（目录按 1 个计，不展开里面的文件）
        self.skipped_system = 0
        # 是否因为达到 max_files 上限而提前停止（True 表示统计结果不完整）
        self.truncated = False


def walk_files(root: Path, *, max_files: int, stats: WalkStats) -> Iterator[Path]:
    """递归产出 root 下的所有文件，跳过 IGNORED_DIR_NAMES 与系统文件 / 系统目录，最多产出 max_files 个。

    典型场景：用户让统计 "D:\\" 整个盘，遍历时会自动绕开回收站、System Volume Information 等。

    :param root: 起始目录（调用方保证是存在的目录）
    :param max_files: 产出文件数上限，防止扫描整个磁盘时卡死
    :param stats: 统计对象，遍历中会写入跳过目录数、跳过系统项数、是否截断
    :return: 文件路径生成器（目录内按名字排序，保证结果稳定）
    """
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地修改 dirnames 才能让 os.walk 不再进入这些目录
        kept = []
        for d in dirnames:
            if d in IGNORED_DIR_NAMES:
                stats.skipped_dirs += 1
            elif system_path_reason(Path(dirpath) / d):
                stats.skipped_system += 1
            else:
                kept.append(d)
        dirnames[:] = sorted(kept)
        for name in sorted(filenames):
            f = Path(dirpath) / name
            if system_path_reason(f):
                stats.skipped_system += 1
                continue
            if count >= max_files:
                stats.truncated = True
                return
            count += 1
            yield f


# --------------------------------------------------------------------------- #
# 文本读取（多层兜底）
# --------------------------------------------------------------------------- #
def human_size(n: int) -> str:
    """把字节数格式化成 B / KB / MB / GB，方便模型直接转述给用户。

    :param n: 字节数
    :return: 例如 "1.5 MB"
    """
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def describe_file(p: Path) -> str:
    """生成一个文件的元信息描述（大小 + 修改时间 + 后缀），无法读内容时作为兜底返回。

    :param p: 已存在的文件
    :return: 例如 "大小 1.2 MB，修改于 2026-10-14 10:30，类型 .png"
    """
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"大小 {human_size(st.st_size)}，修改于 {mtime}，类型 {p.suffix or '(无后缀)'}"


def is_binary_file(p: Path) -> bool:
    """嗅探文件开头是否含 NUL 字节，含则认为是二进制（图片、压缩包、exe 等）。

    这是 git / grep 等工具通用的近似判断：文本文件几乎不会出现 \\x00。
    已知限制：UTF-16 编码的文本也含 \\x00，会被误判为二进制。

    :param p: 已存在的文件
    :return: True 表示二进制，不应按文本解码
    """
    with p.open("rb") as f:
        return b"\x00" in f.read(BINARY_SNIFF_BYTES)


def detect_text_encoding(p: Path) -> str | None:
    """按 TEXT_ENCODINGS 依次尝试解码整份文件，返回第一个解码成功的编码。

    写文件（edit_file）时需要用原编码写回，入库时需要用正确编码读取，避免 GBK 文件乱码。
    带 BOM 的文件返回 utf-8-sig：解码时去掉 BOM，写回时再加上，保持文件原样。

    :param p: 已存在的纯文本文件
    :return: 编码名；全部失败时返回 None（调用方可退化为 utf-8 + errors="replace"）
    """
    data = p.read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    for enc in TEXT_ENCODINGS:
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return None


def read_text_any(p: Path) -> tuple[str | None, str]:
    """尽量把任意文件读成文本，读不了就说明原因。分层兜底：

    1. pdf / docx：用专用解析器（document_parser.parse_document）
    2. 二进制（含 NUL 字节）或超过 MAX_READ_BYTES：不读内容
    3. 其它任何后缀：按 TEXT_ENCODINGS 尝试解码，全失败则 utf-8 容错解码

    :param p: 已存在的文件
    :return: (文本, 说明)；文本为 None 表示无法读取内容，说明里写原因
    """
    size = p.stat().st_size
    if size > MAX_READ_BYTES:
        return None, f"文件过大（{human_size(size)}，上限 {human_size(MAX_READ_BYTES)}），只能提供元信息"
    if p.suffix.lower() in RICH_DOC_SUFFIXES:
        try:
            return parse_document(p), f"{p.suffix} 文档解析"
        except Exception as e:  # 文件损坏、加密 PDF 等
            return None, f"{p.suffix} 解析失败: {e}"
    # 引擎明确不支持的 Office 家族后缀（.rtf/.odt/.et/.dps）：
    # 这类容器格式按文本硬读出来是乱码，直接给"另存为"提示比返回乱码有用
    hint = UNSUPPORTED_OFFICE_SUFFIXES.get(p.suffix.lower())
    if hint is not None:
        return None, f"暂不支持直接读取 {p.suffix} 文件，请另存为 {hint} 后再试"
    if is_binary_file(p):
        return None, "二进制文件（图片/压缩包/可执行文件/xlsx 等），无法按文本读取"
    enc = detect_text_encoding(p)
    if enc is None:
        return p.read_bytes().decode("utf-8", errors="replace"), "编码无法识别，已容错解码（可能有乱码）"
    return p.read_bytes().decode(enc), f"文本，编码 {enc}"


