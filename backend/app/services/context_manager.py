# app/services/context_manager.py
"""上下文预算与压缩（ARCH-5）。

要解决的问题：
    checkpointer 里存的是**整段会话历史**，每一轮都会把它全部塞回模型。
    聊到几十轮之后，输入 token 会持续膨胀：慢、贵，最终直接超窗口报错。

做法（刻意保守）：
    1. **估算**当前历史占用（不追求精确，只用来触发决策）；
    2. 超过 `context.compress_threshold × 模型窗口` 时，把"较早的消息"交给模型总结成一段摘要；
    3. 保留最近 `context.keep_recent_n` 条原文，摘要 + 最近消息写回 checkpointer。

两条硬约束（踩过就知道疼）：
    - **不能把工具调用拆开**：`AIMessage(tool_calls=[...])` 与紧随其后的 `ToolMessage` 必须同生共死，
      只留一半会让下一次模型调用直接报"缺少 tool 结果"。
      所以切分点只能落在"用户消息"上（一轮的起点），而不是任意下标。
    - **摘要不能用 SystemMessage**：`create_agent` 每轮会自己在最前面插系统提示词，
      再塞一条 system 就变成"两条 system"，Anthropic 这类供应商会直接拒绝。
      这里用带明显标记的 HumanMessage，语义上不如 system 干净，但所有 provider 都能吃。

任何一步出错都**只记日志、继续原样调用模型**：压缩是优化，不是对话的前置条件。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：日志与耗时统计
import logging
# 标准库：Any 标注 LangChain 消息对象（它们来自 langchain_core，类型不必写死）
from typing import Any, Awaitable, Callable

# 项目内：模型注册表（取当前模型的上下文窗口）
from app.llm import registry as llm_registry

# 本模块专用 logger
log = logging.getLogger("chat.context")

# 取不到模型元数据时的保守上下文窗口（token）；宁可早压缩，也不要撞上 provider 的硬上限
FALLBACK_CONTEXT_WINDOW = 32_000

# 摘要请求里最多带多少字符的旧消息（避免"为了压缩反而先炸一次"）
_SUMMARY_INPUT_MAX_CHARS = 12_000

# 摘要结果的硬上限（字符）；模型偶尔会写很长，这里兜一层
_SUMMARY_OUTPUT_MAX_CHARS = 1_200

# 发给模型的摘要提示词模板：要求"只记事实与结论"，不要复述原文
_SUMMARY_PROMPT = (
    "下面是一段较早的对话记录（用户与 AI 助手，可能含工具调用结果）。"
    "请把它压缩成不超过 300 字的摘要，只保留：\n"
    "1) 用户的目标与约束；2) 已经确认的事实/结论；3) 已经做过且有效的操作；\n"
    "4) 还没解决的问题。不要复述原文，不要编造。\n\n"
    "对话记录：\n{content}"
)


def build_summary_prompt(text: str) -> str:
    """拼出发给模型的摘要请求（把旧消息塞进固定模板）。

    :param text: 旧消息拼接后的文本（调用方负责截断长度）
    :return: 完整提示词
    """
    return _SUMMARY_PROMPT.format(content=text)


def estimate_tokens(text: str) -> int:
    """粗略估算一段文本的 token 数。

    为什么不用 tiktoken：它要按模型下载词表（离线环境会失败），而且对中文的估算偏差
    与这里的分段估算差不多。这里的口径：CJK 字符按 1 token/字，其它字符按 4 字符/token。

    :param text: 待估算文本
    :return: 估算 token 数（空串返回 0）
    """
    if not text:
        return 0
    cjk = 0
    for ch in text:
        # 常用中文标点也按 1 token 计，避免"全是标点的段落"被严重低估
        if "\u4e00" <= ch <= "\u9fff" or ch in "，。！？；：、“”‘’（）「」『』【】《》…—":
            cjk += 1
    other = len(text) - cjk
    return cjk + max(0, other // 4) + 1


def estimate_messages_tokens(messages: list[Any]) -> int:
    """估算一组 LangChain 消息的总 token 数。

    :param messages: LangChain BaseMessage 列表
    :return: 估算总量
    """
    total = 0
    for message in messages:
        content = getattr(message, "content", "")
        # 多模态消息的 content 是 list（文本块 + 图片块），这里只统计文本部分
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in content
            )
        total += estimate_tokens(str(content))
        # tool_calls 的参数也是真实进上下文的 token，按 JSON 文本粗算
        for call in getattr(message, "tool_calls", None) or []:
            total += estimate_tokens(str(call))
    return total


def context_window() -> int:
    """当前模型的上下文窗口（token）；取不到时用保守默认值。

    :return: 窗口大小
    """
    try:
        provider, model = llm_registry.current_provider_and_model()
        spec = llm_registry.resolve_model_spec(provider, model or None)
        return int(spec.context_window) or FALLBACK_CONTEXT_WINDOW
    except Exception:
        return FALLBACK_CONTEXT_WINDOW


def should_compress(total_tokens: int, *, window: int, threshold_ratio: float) -> bool:
    """判断是否该压缩：占窗口比例超过阈值。

    :param total_tokens: 当前历史估算 token
    :param window: 模型上下文窗口
    :param threshold_ratio: 触发比例（设置键 context.compress_threshold，0.1~0.95）
    :return: True=该压缩
    """
    if window <= 0:
        return False
    return total_tokens >= window * max(0.1, min(0.95, threshold_ratio))


def split_messages(messages: list[Any], keep_recent: int) -> tuple[list[Any], list[Any]]:
    """把消息切成「要压缩的早期部分」与「原样保留的最近部分」。

    切分点必须落在一轮的开始（HumanMessage）：
        - 若落在 AIMessage 上，它前面的工具结果会被留下、工具调用被丢掉，模型会报错；
        - 若落在 ToolMessage 上，更是直接产生"孤儿工具结果"。

    :param messages: 全部消息（时间升序）
    :param keep_recent: 至少保留多少条最近消息
    :return: (早期消息, 最近消息)；无需压缩时返回 ([], messages)
    """
    if keep_recent <= 0:
        keep_recent = 1
    if len(messages) <= keep_recent:
        return [], messages

    index = len(messages) - keep_recent
    # 往前退到"某轮用户消息"的位置；退不到就放弃这次压缩（宁可多花点 token 也不要破坏结构）
    while index > 0 and getattr(messages[index], "type", "") != "human":
        index -= 1
    if index <= 0:
        return [], messages
    return messages[:index], messages[index:]


def mechanical_summary(messages: list[Any]) -> str:
    """不调用模型时的兜底摘要：摘录每轮的片段并说明"有 N 条被省略"。

    为什么要有它：摘要模型可能超时/超额/没配好，此时"丢掉早期原文 + 一句说明"
    仍然比"什么都不做然后超窗口"安全。

    :param messages: 被压缩的早期消息
    :return: 摘要文本（不含前缀标记）
    """
    lines: list[str] = []
    for message in messages:
        role = "用户" if getattr(message, "type", "") == "human" else "助手"
        content = getattr(message, "content", "")
        text = str(content).strip().replace("\n", " ")
        if not text:
            continue
        lines.append(f"- {role}：{text[:120]}")
        if len(lines) >= 12:
            break
    body = "\n".join(lines) or "- （这段历史没有可摘录的文本）"
    return f"较早的 {len(messages)} 条消息已省略，要点如下：\n{body}"


async def compress_messages(
    messages: list[Any],
    *,
    keep_recent: int,
    summarize: Callable[[str], Awaitable[str]] | None = None,
) -> list[Any]:
    """生成压缩后的消息列表（摘要 + 最近原文）。

    :param messages: 全部消息
    :param keep_recent: 最近保留多少条
    :param summarize: 摘要函数（入参是旧消息拼接文本，返回摘要）；None 或抛错时用机械摘要
    :return: 新消息列表；无需压缩时原样返回
    """
    head, tail = split_messages(messages, keep_recent)
    if not head:
        return messages

    summary = ""
    if summarize is not None:
        raw = []
        for message in head:
            content = str(getattr(message, "content", "")).strip()
            if content:
                raw.append(content)
        text = "\n".join(raw)[-_SUMMARY_INPUT_MAX_CHARS:]
        try:
            summary = (await summarize(text)).strip()
        except Exception:
            log.warning("上下文摘要失败，改用机械摘要", exc_info=True)
            summary = ""
    if not summary:
        summary = mechanical_summary(head)

    summary = summary[:_SUMMARY_OUTPUT_MAX_CHARS]

    # 项目内：延迟导入，避免把 langchain 的消息类在模块导入期就拉进来
    from langchain_core.messages import HumanMessage

    marker = HumanMessage(content=(
        f"【历史对话摘要｜较早的 {len(head)} 条消息已压缩，以下是要点】\n{summary}"
    ))
    log.info("上下文压缩：%d 条 → 1 条摘要 + %d 条最近消息", len(messages), len(tail))
    return [marker, *tail]
