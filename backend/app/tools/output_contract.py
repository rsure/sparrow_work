# app/tools/output_contract.py
"""
工具输出治理契约（EXT-5）：给**所有**工具的出参套一层统一外壳 —— 超长截断 + 完整内容落盘续读。

为什么需要这一层（不做的后果）：
    工具输出会直接进模型上下文。`read_file` 读一份 3 万行的日志、`grep_files` 命中几千条，
    一次就能把上下文窗口顶满，后面所有推理都变贵、变慢，甚至直接报错。
    这一层的定位是「上下文保险丝」：模型默认只看前 N 个字符，需要细节时再按续读标记去取。

三个职责：
    1. truncate_tool_output()  按阈值截断，返回结构化结果（含原始字符数、是否截断、续读标记）
    2. apply_output_contract() 读设置开关后调用上一步，供 policy.make_tool 的统一出口使用
    3. read_continuation()     按续读标记取回完整内容（供将来「读取完整输出」工具/接口使用）

存储位置：完整内容写 `app_settings` 表的 `tool-out-<uuid>` 键（与 doc/28 T05 约定一致）。
    为什么不另建表：这一层要在 M2 就能用，而建表要走迁移；用已有的键值表零成本。
    代价是设置表会混入临时数据，所以：
      - 键前缀固定 `tool-out-`，`get_all_setting_values()` 会跳过它们（见 setting_service）；
      - 单条上限 _MAX_CONTINUATION_CHARS，超过就不落盘（截断照常生效，只是不能续读）。

对外约定（与前端 ToolEndEvent 一一对应）：
    output           模型/前端看到的（可能已截断的）文本
    total_chars      截断**前**的原始字符数
    truncated        是否发生了截断
    continuation_ref 续读标记（`tool-out-xxx`）；未截断或落盘失败时为 None
"""

# 让类型注解延迟求值（PEP 563），便于写 str | None
from __future__ import annotations

# 标准库：生成续读标记里的唯一后缀
import uuid
# 标准库：dataclass 描述截断结果（不可变，避免调用方误改）
from dataclasses import dataclass
# 标准库：模块级日志，落盘失败时留下线索但不打断工具调用
import logging

# 本模块专用 logger：日志里出现 "tools.output_contract" 就来自这里
log = logging.getLogger("tools.output_contract")

# 续读键的固定前缀：与普通设置键（组.键）区分开，便于清理与过滤
CONTINUATION_PREFIX = "tool-out-"

# 单条续读内容最多存多少字符（约 2M 字符）：再大就不落盘，避免把设置库撑爆
_MAX_CONTINUATION_CHARS = 2_000_000

# 截断时追加的提示文案模板：告诉模型"内容不全、怎么取全"
_TRUNCATE_NOTE = (
    "\n\n…（输出过长已截断：原文 {total} 字符，此处保留前 {kept} 字符。"
    "完整内容已保存，续读标记 {ref}；需要细节时请缩小查询范围后重试）"
)

# 续读标记取不回来时的提示（说明内容已被清理或从未落盘）
_MISSING_NOTE = "\n\n…（完整内容已不可用：续读标记 {ref} 不存在，可能是设置库被清理过）"


@dataclass(frozen=True)
class TruncateResult:
    """一次工具输出截断的结果。"""

    # 交给模型/前端的文本：未截断时就是原文，截断时是"前 N 字符 + 提示"
    output: str
    # 截断前的原始字符数（用于前端展示"原始 12345 字符"）
    total_chars: int
    # 是否发生了截断
    truncated: bool
    # 续读标记；未截断、或完整内容落盘失败时为 None
    continuation_ref: str | None = None


# 最近一次截断结果：{(session_id, tool_name): TruncateResult}
# 为什么用模块级字典而不是返回值透传：截断发生在 policy.make_tool 的统一出口，
# 而 tool_end 事件由 chat_controller 从 LangGraph 事件里转发，两处没有直接调用关系。
# 单机单用户、工具调用串行，用"最近一次"足够；键里带 session_id 避免跨会话串味。
_LAST: dict[tuple[str, str], TruncateResult] = {}


def _store_continuation(text: str) -> str | None:
    """把完整输出写进设置库，返回续读标记；失败时返回 None（调用方照常截断）。

    :param text: 完整输出文本
    :return: 形如 "tool-out-3f2a..." 的续读标记；超限或写库失败时为 None
    """
    if len(text) > _MAX_CONTINUATION_CHARS:
        log.warning("工具输出过大（%d 字符），跳过落盘续读", len(text))
        return None
    ref = f"{CONTINUATION_PREFIX}{uuid.uuid4().hex}"
    try:
        # 项目内：延迟导入，避免本模块在「设置表还没建好」的启动早期把数据库依赖带进来
        from app.services import setting_service

        setting_service.set_setting_value(ref, "string", text)
    except Exception:
        # 落盘失败不影响截断本身：模型仍然能拿到前 N 个字符
        log.exception("工具输出落盘失败，本次无法续读")
        return None
    return ref


def read_continuation(ref: str) -> str | None:
    """按续读标记取回完整输出。

    :param ref: 续读标记（TruncateResult.continuation_ref）
    :return: 完整文本；标记非法、不存在或已被清理时返回 None
    """
    if not ref or not ref.startswith(CONTINUATION_PREFIX):
        return None
    try:
        from app.services import setting_service

        value = setting_service.get_setting_value(ref)
    except Exception:
        log.exception("读取续读内容失败：%s", ref)
        return None
    return value if isinstance(value, str) else None


def truncate_tool_output(
    text: str,
    *,
    max_chars: int,
    session_id: str = "",
    tool_name: str = "",
    persist: bool = True,
) -> TruncateResult:
    """按阈值截断一段工具输出，并在需要时把完整内容落盘。

    只保留**前** max_chars 个字符而不是头尾各留一半：
    工具输出（文件内容、命令回显、检索摘要）的有效信息基本都在开头，
    砍掉尾部对模型判断"这是什么、成不成功"影响最小，也不会破坏 "OK:" / "FAIL:" 前缀。

    :param text: 工具的原始输出
    :param max_chars: 截断阈值（字符数）；<=0 视为不截断
    :param session_id: 会话 id，仅用于登记"最近一次截断"供 tool_end 事件读取
    :param tool_name: 工具名，同上
    :param persist: 是否把完整内容落盘（测试里传 False 可跳过写库）
    :return: TruncateResult
    """
    total = len(text or "")
    if max_chars <= 0 or total <= max_chars:
        result = TruncateResult(output=text, total_chars=total, truncated=False)
        if session_id and tool_name:
            _LAST[(session_id, tool_name)] = result
        return result

    ref = _store_continuation(text) if persist else None
    note = (
        _TRUNCATE_NOTE.format(total=total, kept=max_chars, ref=ref)
        if ref
        else _MISSING_NOTE.format(ref="(未生成)")
    )
    result = TruncateResult(
        output=f"{text[:max_chars]}{note}",
        total_chars=total,
        truncated=True,
        continuation_ref=ref,
    )
    if session_id and tool_name:
        _LAST[(session_id, tool_name)] = result
    return result


def apply_output_contract(
    text: str,
    *,
    tool_name: str,
    session_id: str = "",
    enabled: bool | None = None,
    max_chars: int | None = None,
) -> TruncateResult:
    """按当前设置（`context.tool_output_truncate` / `context.max_tool_output_chars`）执行截断。

    :param text: 工具的原始输出
    :param tool_name: 工具名（登记"最近一次截断"用）
    :param session_id: 会话 id（同上）
    :param enabled: 显式覆盖开关；None 表示读设置（读不到按开启处理）
    :param max_chars: 显式覆盖阈值；None 表示读设置（读不到用 8000）
    :return: TruncateResult
    """
    if enabled is None or max_chars is None:
        # 项目内：延迟导入，且任何异常都回落到保守默认值——治理层不该把工具调用打断
        try:
            from app.services.settings_registry import get_setting

            if enabled is None:
                enabled = bool(get_setting("context.tool_output_truncate"))
            if max_chars is None:
                max_chars = int(get_setting("context.max_tool_output_chars"))
        except Exception:
            if enabled is None:
                enabled = True
            if max_chars is None:
                max_chars = 8000

    if not enabled:
        return TruncateResult(output=text, total_chars=len(text or ""), truncated=False)
    return truncate_tool_output(
        text, max_chars=max_chars, session_id=session_id, tool_name=tool_name
    )


def take_last_truncation(session_id: str, tool_name: str) -> TruncateResult | None:
    """取走某个会话里某个工具「最近一次」的截断结果（取走即删除，避免串到下一轮）。

    :param session_id: 会话 id
    :param tool_name: 工具名
    :return: 截断结果；该工具这轮没跑过（或跑的是别的会话）时为 None
    """
    return _LAST.pop((session_id, tool_name), None)


def peek_last_truncation(session_id: str, tool_name: str) -> TruncateResult | None:
    """查看（不删除）最近一次截断结果，调试与测试用。

    :param session_id: 会话 id
    :param tool_name: 工具名
    :return: 截断结果或 None
    """
    return _LAST.get((session_id, tool_name))


def reset_for_test() -> None:
    """清空"最近一次截断"登记表，供用例之间隔离状态。"""
    _LAST.clear()
