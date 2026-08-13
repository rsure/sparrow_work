# app/tools/file_ops_tool.py
"""
文件管理工具：移动、复制、删除、新建目录。补齐"只会读写单个文件"的缺口。

安全设计（四条，逐条对应下面的实现）：
    1. 所有路径（源 + 目标）都过 path_decision(OP_WRITE)：受保护目录不仅不能写，也不能被移动/删除
    2. 需要落盘的操作走 policy.make_tool 的统一确认：一次调用只弹一次窗，窗里列清全部动作
    3. 删除默认送系统回收站，直删（permanent=True）需要模型显式要求，且弹窗文案会明确警告
    4. 覆盖、以及"把目录移进自己子孙"这类结构性错误，在**只读预检**阶段就拦掉（不消耗用户的一次确认）

为什么是"一个工具带多个 item"而不是四个工具：
    移动/复制/删除的参数形状完全一样（源 + 目标），拆成四个工具会让提示词变长、模型更容易选错。
    真正需要分开的是**语义**（是否可逆、是否需要 overwrite），用 op 字段表达即可。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：shutil 做移动/复制（copytree 支持目录）；它与 send2trash 的分工要分清
import shutil
# 标准库：Path 拼接、判断存在性、取名字
from pathlib import Path

# 第三方：把文件/目录送进系统回收站（跨平台；直删不走它）
from send2trash import send2trash

# LangChain 工具装饰器：把普通函数变成模型可调用的工具
from langchain_core.tools import tool

# 项目内：权限模型
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：按路径的互斥锁（TASK Phase 2 并行车道兜底：同一路径不允许被两条道同时改动）
from app.tools.path_lock import path_lock
# 项目内：公共底座——返回格式、路径校验、路径包含判断、写入策略判定
from app.tools.tool_utils import (
    OP_WRITE,
    fmt,
    human_size,
    path_decision,
    resolve_abs_path,
    same_or_under,
)

# 允许的操作名（模型传的 op 字段只能是这三个）
_OP_MOVE = "move"
_OP_COPY = "copy"
_OP_DELETE = "delete"
# 合法 op 集合，用于参数校验
_VALID_OPS = frozenset({_OP_MOVE, _OP_COPY, _OP_DELETE})


# --------------------------------------------------------------------------- #
# 只读预检：把"结构性错误"和"需要确认的动作"分开
# --------------------------------------------------------------------------- #
def _delete_how(permanent: bool) -> str:
    """拼出"这次删除可不可恢复"的说明，供确认弹窗展示。

    :param permanent: True=直接删除（不进回收站），False=送入系统回收站
    :return: 中文说明
    """
    return "⚠ 直接删除（不进回收站，无法恢复）" if permanent else "移入系统回收站（可从回收站还原）"


def _plan_one(op: str, src: Path, dst: Path | None, overwrite: bool, permanent: bool = False) -> str:
    """对单个动作做只读预检，返回给弹窗看的一句说明；错误通过抛 ValueError 表达。

    这里**不做任何副作用**：因为 interrupt() 之后工具函数会从头重跑，
    只有放在 ask_user 之后的代码才会真正执行一次。所以预检必须保持"只读"。

    :param op: move / copy / delete
    :param src: 源路径（已 resolve）
    :param dst: 目标路径（move/copy 必填）
    :param overwrite: 目标已存在时是否允许覆盖
    :param permanent: 仅 delete 有效；True=直接删除（不进回收站）
    :return: 描述本次动作的一句话
    :raises ValueError: 源不存在、源/目标越界、把目录移进自己的子孙、目标已存在且未允许覆盖
    """
    if not src.exists():
        raise ValueError(f"源不存在: {src}")
    reason = path_decision(src, OP_WRITE)
    if reason:
        raise ValueError(reason)

    if op == _OP_DELETE:
        # 删除的说明必须写清"能不能恢复"——用户就是靠这句话决定要不要点同意
        return f"删除 {src} —— {_delete_how(permanent)}"

    if dst is None:
        raise ValueError(f"{op} 必须给出目标路径")
    reason = path_decision(dst, OP_WRITE)
    if reason:
        raise ValueError(reason)
    if same_or_under(dst, src):
        raise ValueError(f"目标 {dst} 位于源 {src} 之内，这会造成自我覆盖/无限嵌套，已拒绝")

    if dst.exists():
        if not overwrite:
            raise ValueError(f"目标已存在: {dst}。要覆盖请传 overwrite=true；想保留请换一个目标名")
        return f"用 {src} 覆盖 {dst}"

    return f"{'移动' if op == _OP_MOVE else '复制'} {src} → {dst}"


# --------------------------------------------------------------------------- #
# Action 构造
# --------------------------------------------------------------------------- #
# 单次调用最多允许的条目数，防止模型一次"整理"几千个文件把确认弹窗撑爆
_MAX_ITEMS = 200


def build_file_ops_action(op: str, items: list[dict], overwrite: bool = False,
                          permanent: bool = False) -> Action:
    """把 file_ops 的参数翻译成一次待裁决的写操作（预检失败会抛异常，由工具函数转成 FAIL）。

    :param op: move / copy / delete
    :param items: 每个元素形如 {"src": "绝对路径", "dst": "绝对路径"}
    :param overwrite: 目标已存在时是否允许覆盖
    :param permanent: 仅 delete 有效；True=直接删除
    :return: 供裁决的 Action
    :raises ValueError: op 非法、条目为空或过多、预检失败
    """
    if op not in _VALID_OPS:
        raise ValueError(f"op 只能是 {'/'.join(sorted(_VALID_OPS))}，收到 {op}")
    if not items:
        raise ValueError("items 为空")
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"单次最多处理 {_MAX_ITEMS} 个条目，收到 {len(items)}")

    plans: list[str] = []
    paths: list[Path] = []
    for it in items:
        src = resolve_abs_path(str(it.get("src", "")))
        dst = resolve_abs_path(str(it["dst"])) if it.get("dst") else None
        plans.append(_plan_one(op, src, dst, overwrite, permanent))
        paths.append(src)
        if dst is not None:
            paths.append(dst)

    return Action(
        tool="file_ops",
        kind=Kind.WRITE,
        target=f"{op} {len(plans)} 项",
        paths=tuple(paths),
        preview={"op": op, "plan": "\n".join(plans)},
        detail=f"AI 将执行 {len(plans)} 项文件操作（{op}）：\n" + "\n".join(plans),
    )

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
@tool
@make_tool(POLICIES["file_ops"], build_file_ops_action)
def file_ops(op: str, items: list[dict], overwrite: bool = False, permanent: bool = False) -> str:
    """对文件/文件夹做移动、复制或删除，支持一次处理多个条目（一次确认）。

    适用："把 D:\\草稿 里的 md 移到 D:\\归档""复制一份做备份""删掉刚才生成的临时文件"。
    删除默认送**系统回收站**（可还原）；确实要彻底删除时传 permanent=true（弹窗会明确警告）。
    目标已存在时默认拒绝，传 overwrite=true 才覆盖。
    只改名字/改位置不会改动文件内容；需要改内容请用 edit_file。

    :param op: 操作类型：move=移动 / copy=复制 / delete=删除
    :param items: 条目数组；每项形如 {"src": "源绝对路径", "dst": "目标绝对路径"}
                  （delete 时 dst 可省略；move/copy 必填）
    :param overwrite: 目标已存在时是否允许覆盖，默认 False（拒绝）
    :param permanent: 仅 delete 有效；True=直接删除不进回收站，默认 False
    :return: "OK: 各项执行结果汇总" 或 "FAIL: 原因"
    """
    try:
        done: list[str] = []
        failed: list[str] = []

        for it in items:
            src = resolve_abs_path(str(it.get("src", "")))
            dst = resolve_abs_path(str(it["dst"])) if it.get("dst") else None
            try:
                # 只锁 src，不锁 dst：两项互为源/目标（A→B 与 B→A）时，
                # "都锁"会按不同顺序取两把锁而互相等死；锁住源已经足够防住"同一文件被同时搬走"。
                with path_lock(src):
                    if op == _OP_DELETE:
                        # 送回收站或直删；两者都是不可逆操作，所以前面必须先经过用户确认
                        if permanent:
                            if src.is_dir():
                                shutil.rmtree(src)
                            else:
                                src.unlink()
                        else:
                            send2trash(str(src))
                        done.append(f"已删除 {src}")
                        continue

                    # 目标父目录不存在时自动创建（与 write_file 的行为保持一致）
                    assert dst is not None      # build_file_ops_action 已保证 move/copy 必有 dst
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists() and overwrite:
                        # 覆盖前先把旧目标送回收站：比直接删更安全，也只多一行代码
                        send2trash(str(dst))
                    if op == _OP_MOVE:
                        shutil.move(str(src), str(dst))
                    else:
                        if src.is_dir():
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)   # copy2 连修改时间等元数据一起复制
                    done.append(f"已{'移动' if op == _OP_MOVE else '复制'} {src} → {dst}")
            except Exception as e:
                # 单项失败不影响其余项（与 index_path 的批量策略一致），最后统一汇总
                failed.append(f"{src}: {e}")

        summary = f"{op} 完成 {len(done)}/{len(items)} 项"
        body = "\n".join(done)
        if failed:
            body += f"\n\n失败 {len(failed)} 项：\n" + "\n".join(failed[:5])
        return fmt(not failed or bool(done), f"{summary}\n{body}")

    except Exception as e:
        return fmt(False, f"文件操作失败: {e}")


# 本模块对外暴露的工具列表
FILE_OPS_TOOLS = [file_ops]