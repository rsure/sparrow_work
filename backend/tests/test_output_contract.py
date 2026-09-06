"""EXT-5 工具输出治理契约的回归测试。

为什么这些用例重要：
    1. 截断是"上下文保险丝"——失效不会报错，只会让模型上下文悄悄变贵，必须靠测试盯住；
    2. 续读标记必须能取回**完整**内容，否则截断就变成了"丢数据"；
    3. 关闭开关后必须完全不截断（用户可以主动退出治理）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：pytest 的 fixture 与断言
import pytest

# 项目内：被测试的治理层
from app.tools import output_contract


@pytest.fixture(autouse=True)
def _clean_state():
    """每个用例前后清空"最近一次截断"登记，避免用例之间互相影响。"""
    output_contract.reset_for_test()
    yield
    output_contract.reset_for_test()


def test_short_output_not_truncated() -> None:
    """未超阈值的输出应原样返回，且不落盘、不产生续读标记。"""
    text = "OK: 共 3 个文件"
    result = output_contract.truncate_tool_output(text, max_chars=8000, persist=False)

    assert result.output == text
    assert result.total_chars == len(text)
    assert result.truncated is False
    assert result.continuation_ref is None


def test_long_output_truncated_with_metadata() -> None:
    """超长输出应被截断：保留原文前缀、记录原始字符数、给出续读标记。"""
    text = "OK: " + ("x" * 8000)
    result = output_contract.truncate_tool_output(
        text, max_chars=100, session_id="s1", tool_name="read_file"
    )

    assert result.truncated is True
    assert result.total_chars == 8004
    # 截断后仍然保留 OK 前缀与前 100 个字符（模型据此判断成败）
    assert result.output.startswith("OK: xxx")
    assert result.output[:100] == text[:100]
    assert "已截断" in result.output
    assert result.continuation_ref is not None
    assert result.continuation_ref.startswith("tool-out-")


def test_continuation_roundtrip() -> None:
    """落盘的完整内容必须能按续读标记原样取回。"""
    text = "OK: " + ("y" * 500)
    result = output_contract.truncate_tool_output(text, max_chars=50)

    assert result.continuation_ref is not None
    restored = output_contract.read_continuation(result.continuation_ref)
    assert restored == text


def test_continuation_ref_invalid_returns_none() -> None:
    """非法前缀 / 不存在的标记应返回 None，而不是抛异常。"""
    assert output_contract.read_continuation("") is None
    assert output_contract.read_continuation("llm.model") is None
    assert output_contract.read_continuation("tool-out-does-not-exist") is None


def test_apply_contract_respects_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭 `context.tool_output_truncate` 后不应截断（显式覆盖开关）。"""
    text = "z" * 500
    result = output_contract.apply_output_contract(
        text, tool_name="grep_files", enabled=False, max_chars=100
    )

    assert result.truncated is False
    assert result.output == text


def test_apply_contract_truncates_by_max_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关打开时按显式阈值截断，并登记"最近一次截断"供 tool_end 事件读取。"""
    result = output_contract.apply_output_contract(
        "a" * 300, tool_name="list_dir", session_id="s2", enabled=True, max_chars=100
    )

    assert result.truncated is True
    assert result.total_chars == 300
    # take 语义：取一次就没了，避免同一结果被下一轮工具调用复用
    assert output_contract.take_last_truncation("s2", "list_dir") is not None
    assert output_contract.take_last_truncation("s2", "list_dir") is None


def test_take_last_truncation_isolated_by_session() -> None:
    """不同会话的同名工具不串味。"""
    output_contract.truncate_tool_output("q" * 200, max_chars=10, session_id="a", tool_name="read_file")

    assert output_contract.take_last_truncation("b", "read_file") is None
    assert output_contract.take_last_truncation("a", "read_file") is not None
