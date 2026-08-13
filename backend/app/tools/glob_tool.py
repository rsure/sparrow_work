# app/tools/glob_tool.py
"""
按模式查找文件：给一个目录和一个 glob 模式，返回匹配到的文件（含大小与修改时间）。

与既有工具的差别（选哪个用）：
    list_dir   看"这一层/整棵树里有什么"，给的是全量清单与统计
    grep_files 按**内容关键字**找，要读文件内容，慢且挑不出路径模式
    glob       按**路径模式**找，只看文件名与目录结构，不读内容，快且精确

安全：与其它只读工具完全一致——路径经 resolve_abs_path（系统目录拒绝），
遍历经 walk_files（跳过 node_modules/.git 等），因此本工具不需要用户确认。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：fnmatch 做"文件名/相对路径"的模式匹配（支持 * ? [seq]）
import fnmatch
# 标准库：Path 取相对路径、判断是否文件
from pathlib import Path

# LangChain 工具装饰器：把普通函数变成模型可调用的工具
from langchain_core.tools import tool

# 项目内：权限模型（Action / Kind / POLICIES / make_tool）
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：工具公共底座——返回格式、路径校验、遍历统计、大小格式化、文件描述
from app.tools.tool_utils import (
    OP_READ,
    WalkStats,
    describe_file,
    fmt,
    human_size,
    resolve_abs_path,
    walk_files,
)

# 遍历文件数上限，防止用户给盘符根目录时长时间卡住（与 file_read_tool._MAX_WALK_FILES 同量级）
_MAX_WALK_FILES = 50_000


def build_glob_action(root: str, pattern: str, max_results: int = 100) -> Action:
    """把 glob 的参数翻译成一次待裁决的只读操作。

    :param root: 搜索起点目录的绝对路径
    :param pattern: glob 模式（相对 root），如 "**/*.vue"
    :param max_results: 最多返回多少条
    :return: 供 policy.decide 裁决的 Action
    """
    p = resolve_abs_path(root)
    return Action(
        tool="glob",
        kind=Kind.READ,
        target=f"{p} / {pattern}",
        paths=(p,),
        preview={"root": str(p), "pattern": pattern, "max_results": max_results},
        detail=f"在 {p} 下按模式 {pattern} 查找文件",
    )


@tool
@make_tool(POLICIES["glob"], build_glob_action)
def glob(root: str, pattern: str, max_results: int = 100) -> str:
    """在目录下按**路径模式**查找文件，返回匹配文件的相对路径、大小与修改时间。

    适用："找出所有 .vue 文件""src 下面有几个测试文件""列出所有 2026 开头的日志"。
    模式是相对 root 的 glob 写法：`*` 匹配一段、`**` 匹配任意层目录、`?` 匹配一个字符。
    例：`**/*.vue`（任意层级的 vue 文件）、`*.log`（当前层日志）、`src/**/*.ts`（源码目录下的 ts）。
    只看路径模式、不读文件内容：要按**内容关键字**找请用 grep_files。

    :param root: 搜索起点的绝对路径（目录）
    :param pattern: glob 模式，相对 root，如 "**/*.vue"
    :param max_results: 最多返回多少条，默认 100
    :return: "OK: 匹配文件列表（含总数与截断提示）" 或 "FAIL: 原因"
    """
    try:
        base = resolve_abs_path(root)
        if not base.is_dir():
            return fmt(False, f"不是目录: {base}")
        pat = pattern.strip()
        if not pat:
            return fmt(False, "pattern 为空")

        stats = WalkStats()
        hits: list[Path] = []
        for f in walk_files(base, max_files=_MAX_WALK_FILES, stats=stats):
            rel = f.relative_to(base)
            # Path.match 不支持 "**" 跨目录语义，且对大小写敏感；
            # 统一转成 POSIX 风格字符串再用 fnmatch，并对 Windows 做大小写不敏感处理
            if fnmatch.fnmatch(rel.as_posix().lower(), pat.lower()):
                hits.append(f)

        summary = f"在 {base} 下按模式「{pattern}」匹配到 {len(hits)} 个文件"
        if stats.skipped_dirs:
            summary += f"（跳过 {stats.skipped_dirs} 个依赖/缓存目录）"
        if stats.skipped_system:
            summary += f"（跳过 {stats.skipped_system} 个系统文件/目录）"
        if stats.truncated:
            summary += f"；⚠ 遍历文件数达到 {_MAX_WALK_FILES} 上限，结果可能不全"
        if not hits:
            return fmt(True, summary)

        lines = [
            f"[{i}] {f.relative_to(base)}  {describe_file(f)}"
            for i, f in enumerate(hits[:max_results], start=1)
        ]
        if len(hits) > max_results:
            lines.append(f"…另有 {len(hits) - max_results} 个未列出（可调大 max_results 或缩小模式）")
        return fmt(True, summary + "\n" + "\n".join(lines))

    except Exception as e:
        return fmt(False, f"查找失败: {e}")


# 本模块对外暴露的工具列表
GLOB_TOOLS = [glob]