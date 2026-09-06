"""UX-7 三档权限 + UX-9 预算熔断的回归测试。

为什么必须测这几条：
    权限模式改的是"要不要弹确认框"这一层，写错了不会报错，只会**静默放行**——
    这是最危险的一类 bug。预算熔断同理：拦不住最多多花钱，但拦错了会把正常任务掐死。
    这里把四条安全不变量钉住：
      1. allow 模式跳过弹窗，但 DENY 早已在更上游拦下（本函数根本不会被调用）；
      2. workspace 模式查 approvals 命中即放行；
      3. 只有用户勾了"记住"才写授权；
      4. 预算超限选"继续"后该维度本轮不再拦。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：时间戳（预算的时长维度需要）
import time

# 测试框架：monkeypatch 替换外部依赖
import pytest

# 项目内：被测试的策略层与工具层
from app.tools import policy
from app.tools import tool_utils
from app.tools.budget import TurnBudget
from app.services import approval_service


def _action() -> policy.Action:
    """构造一个写文件操作，供 _resolve_ask 使用。"""
    return policy.Action(tool="write_file", kind=policy.Kind.WRITE, target="D:/tmp/a.txt")


def _decision() -> policy.Decision:
    """构造一个 ASK 裁决结果（只用到标题与正文）。"""
    return policy.Decision(policy.Level.ASK, reason="AI 准备写入文件", title="确认写入")


def test_allow_mode_skips_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """permission.mode=allow：不弹窗直接放行（DENY 在更上游已被拦，不在本函数职责内）。"""
    called: list[int] = []

    def fake_ask(*_args, **_kwargs):
        """记录被调用（不该被调用）。"""
        called.append(1)
        return True, False

    monkeypatch.setattr(tool_utils, "ask_user_decide", fake_ask)

    session = policy.SessionContext(session_id="s1", permission_mode="allow")
    assert policy._resolve_ask("write_file", _action(), _decision(), session) is True
    assert called == [], "完全授权模式下不应再弹确认框"


def test_workspace_mode_uses_existing_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """workspace 模式：该工作区已授权过这个工具就直接放行，且不再弹窗。"""
    monkeypatch.setattr(approval_service, "exists", lambda workspace_id, tool: workspace_id == "w1" and tool == "write_file")
    called: list[int] = []
    monkeypatch.setattr(tool_utils, "ask_user_decide", lambda *a, **k: (called.append(1), True, False)[1:])

    session = policy.SessionContext(session_id="s1", permission_mode="workspace", workspace_id="w1")
    assert policy._resolve_ask("write_file", _action(), _decision(), session) is True
    assert called == []


def test_workspace_mode_remembers_only_when_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """记住与否必须由用户勾选决定：没勾不写库，勾了才写。"""
    saved: list[tuple[str, str]] = []

    monkeypatch.setattr(approval_service, "exists", lambda *_a: False)
    monkeypatch.setattr(approval_service, "upsert", lambda ws, tool, kind="", target="": saved.append((ws, tool)))

    session = policy.SessionContext(session_id="s1", permission_mode="workspace", workspace_id="w1")

    # 场景 A：同意但没勾"记住"
    monkeypatch.setattr(tool_utils, "ask_user_decide", lambda *a, **k: (True, False))
    assert policy._resolve_ask("write_file", _action(), _decision(), session) is True
    assert saved == []

    # 场景 B：同意且勾了"记住"
    monkeypatch.setattr(tool_utils, "ask_user_decide", lambda *a, **k: (True, True))
    assert policy._resolve_ask("write_file", _action(), _decision(), session) is True
    assert saved == [("w1", "write_file")]


def test_ask_mode_never_writes_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """ask 模式（默认）：每次都要问，即使前端误传 remember 也不该写授权。"""
    saved: list[tuple[str, str]] = []
    monkeypatch.setattr(approval_service, "upsert", lambda ws, tool, kind="", target="": saved.append((ws, tool)))
    # 前端传了 remember=true，但 allow_remember=False 时 ask_user_decide 会把它压成 False
    monkeypatch.setattr(tool_utils, "ask_user_decide", lambda *a, **k: (True, bool(k.get("allow_remember"))))

    session = policy.SessionContext(session_id="s1", permission_mode="ask", workspace_id="w1")
    assert policy._resolve_ask("write_file", _action(), _decision(), session) is True
    assert saved == []


# --------------------------------------------------------------------------- #
# UX-9 预算
# --------------------------------------------------------------------------- #
def test_budget_thresholds_and_release() -> None:
    """三个维度分别能触发；释放后不再触发；关闭开关后一律不触发。"""
    # started_at 用"现在"，否则 duration 维度会因为 1970 年到现在而恒超限（用例自身的坑）
    budget = TurnBudget(session_id="s1", started_at=time.time(), max_tokens=100, max_cost=1.0, max_seconds=3600.0)
    budget.add_usage({"input_tokens": 60, "output_tokens": 60}, price_in=0, price_out=0)

    hit = budget.exceeded()
    assert hit is not None and hit[0] == "tokens"

    budget.release("tokens")
    assert budget.exceeded() is None, "用户选继续后该维度本轮不该再拦"

    budget.add_usage({"input_tokens": 1_000_000, "output_tokens": 0}, price_in=2.0, price_out=0)
    hit = budget.exceeded()
    assert hit is not None and hit[0] == "cost"

    # 关掉总开关：任何维度都不再拦
    budget.guard_enabled = False
    assert budget.exceeded() is None


def test_budget_cost_conversion() -> None:
    """费用按「元/百万 token」折算：1000 输入 token × 2 元/百万 = 0.002 元。"""
    budget = TurnBudget(session_id="s1", started_at=time.time())
    budget.add_usage({"input_tokens": 1000, "output_tokens": 0}, price_in=2.0, price_out=8.0)
    assert round(budget.cost, 6) == 0.002


def test_resolve_budget_blocks_when_user_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户选「停止」时返回 FAIL 文案（而不是抛异常），让模型能自行收尾。"""
    budget = TurnBudget(session_id="s1", started_at=time.time(), max_tokens=1)
    budget.add_usage({"input_tokens": 10, "output_tokens": 10})

    monkeypatch.setattr("app.tools.budget.get_budget", lambda session_id: budget)
    monkeypatch.setattr(tool_utils, "ask_budget", lambda dimension, current, limit: False)

    note = policy._resolve_budget("write_file", policy.SessionContext(session_id="s1"))
    assert note is not None
    assert "预算超出" in note


def test_budget_stop_blocks_rest_of_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户选「停止」后，本轮后续工具调用直接拒绝且不再弹窗（避免反复打扰）。"""
    budget = TurnBudget(session_id="s1", started_at=time.time(), max_tokens=1)
    budget.add_usage({"input_tokens": 10, "output_tokens": 10})

    asked: list[int] = []
    monkeypatch.setattr("app.tools.budget.get_budget", lambda session_id: budget)
    monkeypatch.setattr(tool_utils, "ask_budget", lambda *a: (asked.append(1), False)[1])

    session = policy.SessionContext(session_id="s1")
    first = policy._resolve_budget("write_file", session)
    assert first is not None and budget.blocked is True

    # 第二次：不再弹窗，但仍拒绝
    second = policy._resolve_budget("edit_file", session)
    assert second is not None
    assert len(asked) == 1, "选过停止之后不该再弹第二次"


def test_resolve_budget_continues_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户选「继续」：放行，并把该维度记进 released。"""
    budget = TurnBudget(session_id="s1", started_at=time.time(), max_tokens=1)
    budget.add_usage({"input_tokens": 10, "output_tokens": 10})

    monkeypatch.setattr("app.tools.budget.get_budget", lambda session_id: budget)
    monkeypatch.setattr(tool_utils, "ask_budget", lambda dimension, current, limit: True)

    assert policy._resolve_budget("write_file", policy.SessionContext(session_id="s1")) is None
    assert "tokens" in budget.released
