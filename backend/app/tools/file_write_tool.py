# app/tools/file_write_tool.py
"""
写文件类原子工具：新建/覆盖文件、对已有文件做局部修改。暴露给 DeepSeek Agent。

写操作有副作用，所以这里比只读工具多三道保险：
    1. 受保护目录拒绝写入：规则表在 tool_utils.PATH_RULES，本模块只负责调用
       再加上本后端自身源码与数据库（只禁写、允许读，防止 AI 改坏自己）
    2. 覆盖已有文件、修改已有文件之前，调用 LangGraph 的 interrupt() 暂停整个 Agent，
       由前端弹窗让用户同意 / 拒绝（human-in-the-loop），用户同意后才真正落盘
    3. 覆盖或修改前自动备份为 "<原文件名>.<时间戳>.bak"，改错了可以手动恢复

interrupt() 的两个要点（读代码前先记住）：
    - 它通过抛出 GraphInterrupt 异常让图暂停，所以工具里的 `except Exception` 必须先放行
      GraphBubbleUp（GraphInterrupt 的父类），否则暂停请求会被当成普通错误吞掉
    - 用户决定后，LangGraph 会把这个工具函数**从头重新执行一遍**，执行到 interrupt() 时直接返回
      用户的决定；所以 interrupt() 之前只能做只读的校验，备份、写盘必须放在它之后

修改方式为什么是"精确字符串替换"而不是"按行号改"：
    模型数行号很容易差一两行；要求给出原文片段 old_text，且原文中必须唯一出现，
    改动位置就是确定的，找不到或出现多次都会明确报错让模型重新读文件。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、list[Path] 等新语法
from __future__ import annotations

# 标准库：shutil.copy2 备份文件（连同修改时间等元数据一起复制）
import shutil
# 标准库：生成备份文件名里的时间戳
from datetime import datetime
# 标准库：路径对象，拼备份路径、创建父目录、读写字节
from pathlib import Path

# LangChain 工具装饰器：把普通函数变成模型可调用的工具，docstring 会作为工具说明发给模型
from langchain_core.tools import tool
# LangGraph 中断异常的基类：工具的兜底 except 里要原样抛出它，让"暂停等待确认"生效
from langgraph.errors import GraphBubbleUp

from app.tools.policy import Action, Kind, POLICIES, make_tool
# 项目内：工具公共底座——返回格式、绝对路径校验、路径包含判断、编码识别、二进制嗅探、暂停请用户确认
from app.tools import file_guard
# 项目内：按文件路径的互斥锁（TASK Phase 2 并行车道兜底，见 doc/26 §5.3 L3）
from app.tools.path_lock import path_lock
# 项目内：当前线程绑定的会话 id（读改写校验与登记都按会话区分）
from app.tools.session import current_session_id
from app.tools.tool_utils import (
    OP_WRITE,
    path_decision,
    detect_text_encoding,
    fmt,
    human_size,
    is_binary_file,
    resolve_abs_path,
    RICH_DOC_SUFFIXES,
)

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

# 单次写入内容的长度上限（单位：字符，约 1MB），防止模型一次生成超大文件
_MAX_WRITE_CHARS = 1_000_000




def _preview(text: str, limit: int = 300) -> str:
    """截断长文本，用于确认弹窗展示（避免把整份文件内容塞进 SSE 事件）。

    :param text: 原文
    :param limit: 最多保留的字符数
    :return: 截断后的文本，超长时末尾带 "…（共 N 字符）"
    """
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字符）"


def _backup(p: Path) -> Path:
    """把已有文件复制一份 "<文件名>.<时间戳>.bak" 放在同目录，修改出错时可手动恢复。

    :param p: 已存在的文件
    :return: 备份文件路径
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(f"{p.name}.{stamp}.bak")
    shutil.copy2(p, bak)
    return bak

def _precheck_write(p: Path) -> str | None:
    """
    只检查目标路径本身。创建父目录时不需要额外检查——
    若父目录落在受保护目录内，目标路径也一定命中同一条规则（same_or_under 按路径前缀比较）。
    写盘前的两项检查：安全策略（能否写这个路径）+ 格式约束（能否按文本写）。

    与 path_decision 的分工：
        - path_decision 管"这个位置允不允许动"（受保护目录、工作区白名单）
        - 这里管"这个文件本身能不能按文本处理"（二进制格式、目标是目录）

    :param p: 已 resolve 的绝对路径
    :return: 不允许写入时返回原因；允许时返回 None
    """
    reason = path_decision(p, OP_WRITE)
    if reason:
        return reason
    if p.suffix.lower() in RICH_DOC_SUFFIXES:
        return f"不支持直接写 {p.suffix} 文件（这是二进制格式），可以改写成 .md / .txt"
    if p.is_dir():
        return f"{p} 是一个目录，不能当文件写入"
    return None


def build_write_action(path: str, content: str, overwrite: bool = False) -> Action:
    """把 write_file 的参数翻译成一次待裁决的写操作。

    :param path: 目标文件路径（模型给的原始字符串，这里负责解析成绝对路径）
    :param content: 写入内容（只取前若干字符进弹窗预览，避免事件体过大）
    :param overwrite: 是否覆盖已存在的文件
    :return: 供 policy.decide 裁决的 Action
    """
    # resolve_abs_path 会抛 ValueError/PermissionError（相对路径、系统路径）；
    # 让异常冒到 write_file 的 except 里，转成 FAIL 文案——保持与现有行为一致
    p = resolve_abs_path(path)
    action_word = "覆盖" if overwrite else "新建"
    return Action(
        tool="write_file",
        kind=Kind.WRITE,
        target=str(p),
        paths=(p,),
        preview={"path": str(p), "content": _preview(content), "overwrite": overwrite},
        detail=f"AI 将{action_word}文件：{p}（{len(content)} 字符）",
    )


def build_edit_action(path: str, old_text: str, new_text: str, replace_all: bool = False) -> Action:
    """把 edit_file 的参数翻译成一次待裁决的写操作。

    :param path: 目标文件路径（模型给的原始字符串，这里负责解析成绝对路径）
    :param old_text: 要被替换的原文片段（只取前若干字符进弹窗预览）
    :param new_text: 替换后的新内容
    :param replace_all: 是否替换所有出现位置
    :return: 供 policy.decide 裁决的 Action
    """
    p = resolve_abs_path(path)
    return Action(
        tool="edit_file",
        kind=Kind.WRITE,
        target=str(p),
        paths=(p,),
        preview={"path": str(p), "old_text": _preview(old_text), "new_text": _preview(new_text)},
        detail=f"AI 将修改文件：{p}",
    )


# =========================================================================== #
# 工具 7：新建 / 覆盖文件
# =========================================================================== #
@tool
@make_tool(POLICIES["write_file"], build_write_action)
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """新建一个文本文件并写入内容（txt/md/json/csv/代码等）；父目录不存在会自动创建。

    适用："帮我新建一个 xxx 文件""把总结保存成 md""生成一份配置文件"。
    无论新建还是覆盖，落盘前系统都会自动弹窗请用户确认；覆盖已有文件时额外自动备份为 .bak。
    目标文件已存在时，必须传 overwrite=true 才允许覆盖，否则返回 FAIL。
    只想改已有文件的一部分时，请用 edit_file，不要整份覆盖。

    :param path: 目标文件的绝对路径
    :param content: 要写入的完整文本内容
    :param overwrite: 目标已存在时是否覆盖，默认 False；True 时会触发用户确认
    :return: "OK: 写入结果（路径、大小、备份位置）" 或 "FAIL: 原因"
    """
    try:
        p = resolve_abs_path(path)
        reason = _precheck_write(p)
        if reason:
            return fmt(False, reason)
        # TASK Phase 2 §5.3 L3：从这里到写入完成都在"这个路径的独占锁"里。
        # 锁的是"读旧内容 → 判断能不能写 → 备份 → 落盘 → 更新登记"这一整段，
        # 只锁最后那一次 write 是不够的：两个线程可以同时通过上面的存在性判断。
        with path_lock(p):
            # TASK §5.3 L2：读后被别人改过就拒绝，避免整份回写覆盖掉那次改动
            stale = file_guard.check_write(current_session_id(), p)
            if stale:
                return fmt(False, stale)
            if len(content) > _MAX_WRITE_CHARS:
                return fmt(False, f"内容过长（{len(content)} 字符，上限 {_MAX_WRITE_CHARS}）")
            if p.exists() and not overwrite:
                return fmt(False, (
                    f"文件已存在: {p}。确实要整份覆盖请用 overwrite=true（会请用户确认）；"
                    "只改局部内容请用 edit_file"
                ))

            backup_msg = ""
            encoding = "utf-8"
            # 覆盖已有文件时才备份、才沿用原编码（避免 GBK 文件被改成 UTF-8 后其它程序读出乱码）
            if p.exists():
                if not is_binary_file(p):
                    encoding = detect_text_encoding(p) or "utf-8"
                backup_msg = f"，原文件已备份到 {_backup(p)}"

            created_dir = not p.parent.exists()
            p.parent.mkdir(parents=True, exist_ok=True)
            # newline="" 表示原样写入换行符，不让 Windows 把 \n 自动改成 \r\n
            with p.open("w", encoding=encoding, newline="") as f:
                f.write(content)

            # 写入成功：把登记更新成新内容，否则紧接着的第二次写入会被自己误判成"被改过"
            file_guard.record_write(current_session_id(), p)

        dir_msg = f"，并新建了目录 {p.parent}" if created_dir else ""
        action = "已覆盖" if backup_msg else "已新建"
        return fmt(True, f"{action} {p}（{human_size(p.stat().st_size)}，编码 {encoding}）{dir_msg}{backup_msg}")

    except GraphBubbleUp:
        raise  # interrupt() 发出的"暂停等待确认"信号，必须交给 LangGraph 处理
    except Exception as e:
        return fmt(False, f"写入失败: {e}")


# =========================================================================== #
# 工具 8：局部修改文件
# =========================================================================== #
@tool
@make_tool(POLICIES["edit_file"], build_edit_action)
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """修改已有文本文件：把其中的 old_text 原样替换为 new_text（精确匹配，区分大小写）。

    使用步骤：先用 read_file 读到原文，从中复制要改的那一段作为 old_text（包含足够的上下文
    让它在文件里只出现一次），再给出改好的 new_text。new_text 传空字符串表示删除这段内容。
    old_text 出现多次时默认拒绝；确实要全部替换时传 replace_all=true。
    校验通过后系统会自动弹窗请用户确认，同意后才修改（修改前自动备份），拒绝则返回 FAIL。
    不能修改 pdf/docx/图片等非纯文本文件。

    :param path: 目标文件的绝对路径
    :param old_text: 要被替换的原文片段（必须与文件内容逐字一致）
    :param new_text: 替换后的新内容
    :param replace_all: True 表示替换所有出现位置，默认 False（只允许唯一匹配）
    :return: "OK: 替换次数与备份位置" 或 "FAIL: 原因"
    """
    try:
        p = resolve_abs_path(path)
        if not p.is_file():
            return fmt(False, f"文件不存在: {p}（新建文件请用 write_file）")
        reason = _precheck_write(p)
        if reason:
            return fmt(False, reason)
        if is_binary_file(p):
            return fmt(False, f"{p} 是二进制文件，不能按文本修改")
        # TASK Phase 2 §5.3 L3：读原文 → 匹配 → 备份 → 写回，全部在路径锁里完成，
        # 否则两条车道同时"读旧内容再整份写回"就会丢掉对方那一处修改。
        with path_lock(p):
            stale = file_guard.check_write(current_session_id(), p)
            if stale:
                return fmt(False, stale)
            if not old_text:
                return fmt(False, "old_text 为空；在文件末尾追加内容时，请把文件最后一段作为 old_text")

            encoding = detect_text_encoding(p)
            if encoding is None:
                return fmt(False, f"无法识别 {p} 的编码，为避免写坏文件，不做修改")
            text = p.read_bytes().decode(encoding)

            # 模型生成的文本一般只用 \n；文件若是 Windows 的 \r\n，先统一成 \n 再匹配，写回时还原
            crlf = "\r\n" in text
            work = text.replace("\r\n", "\n") if crlf else text
            old = old_text.replace("\r\n", "\n")
            new = new_text.replace("\r\n", "\n")

            count = work.count(old)
            if count == 0:
                return fmt(False, "文件中没有找到 old_text；请先用 read_file 读取最新内容，逐字复制要改的片段")
            if count > 1 and not replace_all:
                return fmt(False, (
                    f"old_text 在文件中出现了 {count} 次，无法确定改哪一处；"
                    "请在 old_text 里多带几行上下文让它唯一，或确认要全部替换后传 replace_all=true"
                ))

            replaced = count if replace_all else 1
            result = work.replace(old, new) if replace_all else work.replace(old, new, 1)
            if crlf:
                result = result.replace("\n", "\r\n")

            bak = _backup(p)
            p.write_bytes(result.encode(encoding))
            file_guard.record_write(current_session_id(), p)
        return fmt(True, f"已修改 {p}：替换 {replaced} 处（编码 {encoding}），原文件已备份到 {bak}")

    except GraphBubbleUp:
        raise  # interrupt() 发出的"暂停等待确认"信号，必须交给 LangGraph 处理
    except Exception as e:
        return fmt(False, f"修改失败: {e}")


# 本模块对外暴露的工具列表，由 app/agents/rag_agent.py 与只读工具合并后交给 agent
WRITE_TOOLS = [write_file, edit_file]
