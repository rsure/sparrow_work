"""ARCH-5 上下文压缩的回归测试。

重点不是"摘要写得好不好"（那是模型的事），而是三条结构性约束：
    1. 切分点必须落在**一轮的开始**，不能把 AIMessage(tool_calls) 与它的 ToolMessage 拆开；
    2. 摘要必须用 HumanMessage 承载（SystemMessage 会和 create_agent 自己的系统提示词打架）；
    3. 摘要模型失败时要有兜底，不能让"压缩失败"变成"对话失败"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：asyncio.run 直接在同步用例里跑协程（本项目没装 pytest-asyncio，不为一个用例加依赖）
import asyncio

# 测试框架：断言与 fixture
import pytest

# LangChain 消息类型：构造一段带工具调用的真实对话
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# 项目内：被测试的上下文管理器
from app.services import context_manager


def _conversation() -> list:
    """构造一段"两轮对话 + 一次工具调用"的消息序列（按下标描述见下面断言）。"""
    return [
        HumanMessage(content="第一轮问题"),                       # 0
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "a"}, "id": "c1"}]),  # 1
        ToolMessage(content="文件内容", tool_call_id="c1"),      # 2
        AIMessage(content="第一轮回答"),                          # 3
        HumanMessage(content="第二轮问题"),                       # 4
        AIMessage(content="第二轮回答"),                          # 5
        HumanMessage(content="第三轮问题"),                       # 6
        AIMessage(content="第三轮回答"),                          # 7
    ]


def test_estimate_tokens_counts_cjk_higher() -> None:
    """中文按 1 字 1 token 估算，应明显高于等长英文（按 4 字符 1 token）。"""
    assert context_manager.estimate_tokens("") == 0
    assert context_manager.estimate_tokens("你好世界") >= 4
    assert context_manager.estimate_tokens("你好世界") > context_manager.estimate_tokens("abcd")


def test_split_never_breaks_tool_call_group() -> None:
    """切分点必须回退到 HumanMessage：工具调用与其结果不能被拆到两边。"""
    head, tail = context_manager.split_messages(_conversation(), keep_recent=3)

    # tail 从 index=4（第二轮的用户消息）开始
    assert len(tail) == 4
    assert tail[0].type == "human"
    # head 里那条工具调用与它的 ToolMessage 都在（没有被拆走一半）
    assert any(getattr(m, "tool_calls", None) for m in head)
    assert any(isinstance(m, ToolMessage) for m in head)


def test_split_returns_empty_when_too_short() -> None:
    """消息条数不超过保留数时不做压缩。"""
    head, tail = context_manager.split_messages(_conversation()[:2], keep_recent=10)
    assert head == []
    assert len(tail) == 2


def test_should_compress_by_ratio() -> None:
    """按窗口比例判断：低于阈值不压，超过就压。"""
    assert context_manager.should_compress(100, window=1000, threshold_ratio=0.7) is False
    assert context_manager.should_compress(800, window=1000, threshold_ratio=0.7) is True


def test_compress_uses_human_message_marker() -> None:
    """压缩结果 = 一条带标记的 HumanMessage + 最近消息原文。"""
    messages = _conversation()

    async def fake_summary(text: str) -> str:
        """假的摘要函数：断言它确实收到了旧消息。"""
        assert "第一轮问题" in text
        return "用户先问了第一轮，AI 读了 a 文件。"

    result = asyncio.run(context_manager.compress_messages(
        messages, keep_recent=3, summarize=fake_summary,
    ))

    # 8 条 → 1 条摘要 + 4 条最近消息
    assert len(result) == 5
    assert result[0].type == "human", "摘要必须用 HumanMessage，不能用 SystemMessage"
    assert "历史对话摘要" in result[0].content
    assert "读了 a 文件" in result[0].content
    # 最近的消息一条不少
    assert result[-1].content == "第三轮回答"


def test_compress_falls_back_when_summary_fails() -> None:
    """摘要模型报错时用机械摘要兜底，而不是抛出去把对话弄挂。"""
    messages = _conversation()

    async def broken(_text: str) -> str:
        """模拟摘要模型超时/报错。"""
        raise RuntimeError("model timeout")

    result = asyncio.run(context_manager.compress_messages(
        messages, keep_recent=3, summarize=broken,
    ))
    assert "已省略" in result[0].content
    assert len(result) == 5
