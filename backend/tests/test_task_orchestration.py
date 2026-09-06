# tests/test_task_orchestration.py
"""TASK 编排层测试（不调真实模型）。

为什么单独测编排而不是只测纯函数：
    编排层最容易错的是**状态机**——子任务被确认弹窗打断后能不能接着跑、
    游标会不会重复执行、done 会不会提前发。这些用纯函数测不出来，
    而真跑一遍模型又太慢太不稳，所以用假 `_drive_agent` 精确控制"跑完 / 被打断"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：唯一会话 id、异步收集
import asyncio
import uuid

# 测试框架
import pytest

# 项目内：被测控制器、规划器模块与计划模型
from app.controllers import chat_controller as cc
from app.schemas.task_plan import SubTask, TaskPlan
from app.services import settings_registry, task_planner


@pytest.fixture(autouse=True)
def _ensure_task_defs():
    """确保 task.* 的设置声明已注册。

    与 test_mcp 同理：其它用例会 `reset_for_test()` 清空注册表，
    这里每条用例前补一次，避免依赖执行顺序。
    """
    from app.services.task_settings_defs import register_task_defs

    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    register_task_defs()
    yield


def _plan() -> TaskPlan:
    """一个两子任务的计划。"""
    return TaskPlan(
        complexity="complex",
        reason="测试用",
        subtasks=[
            SubTask(id=1, title="第一步", description="写 A"),
            SubTask(id=2, title="第二步", description="写 B"),
        ],
    )


async def _collect(gen) -> list[str]:
    """把异步生成器里的帧收集起来（帧本身就是 SSE 字符串）。"""
    return [frame async for frame in gen]


def _patch_planner(monkeypatch: pytest.MonkeyPatch, plan: TaskPlan) -> None:
    """让规划器固定返回给定计划，汇总固定返回一句话。"""

    async def fake_plan(_message: str, *, max_subtasks: int = 5) -> TaskPlan:
        return plan

    async def fake_summary(_original: str, _plan: TaskPlan) -> str:
        return "全部完成。"

    monkeypatch.setattr(task_planner, "looks_complex", lambda _m: True)
    monkeypatch.setattr(task_planner, "make_plan", fake_plan)
    monkeypatch.setattr(task_planner, "summarize", fake_summary)


def _patch_agent(monkeypatch: pytest.MonkeyPatch, *, interrupt_on: str = "") -> list[str]:
    """用假 `_drive_agent` 替换真实 agent：按子任务输出一段文字。

    :param interrupt_on: 命中该子任务标题时模拟"停下等确认"（设置 pending_interrupt_id）
    :return: 记录调用顺序的列表
    """
    calls: list[str] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True):
        """模拟一次 agent 执行：追加一段文本并推一个 token 帧。"""
        content = graph_input["messages"][-1]["content"]
        calls.append(content)
        sess.turn_text.append("做完了这一步。")
        yield cc._sse("token", trace_id, {"text": "做完了这一步。"})
        if interrupt_on and interrupt_on in content:
            # 模拟工具层 interrupt()：控制器看到 pending_interrupt_id 就会认为"停下等确认"
            sess.pending_interrupt_id = "intr-1"
        # 注意：这里刻意不 done——与真实链路在 finalize=False 时一致

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    return calls


def _prepare(sess, plan: TaskPlan) -> TaskPlan:
    """把计划挂到会话上（模拟 `_run_with_tasks` 进入任务模式后的状态）。"""
    sess.task_plan = plan
    sess.task_cursor = 0
    sess.task_original = "把 A 和 B 都改一下"
    return plan


@pytest.fixture()
def session():
    """一个干净的会话对象（含本轮初始化）。"""
    sid = f"task-test-{uuid.uuid4().hex[:8]}"
    sess = cc.SessionState(session_id=sid)
    cc._start_turn(sess, "把 A 和 B 都改一下", "agent", "trace-test")
    yield sess
    # 收尾：结束轨迹 + 删掉测试会话的历史记录
    from app.services import chat_history_service as history
    from app.services import trace_service

    trace_service.end_turn(sess.trace_turn_id)
    history.delete_session(sid)


def test_plan_runs_all_subtasks_then_summarizes(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常路径：plan → 两个 task_start/task_end → 汇总 → done（subtasks 带状态）。"""
    plan = _prepare(session, _plan())
    _patch_planner(monkeypatch, plan)
    calls = _patch_agent(monkeypatch)

    stop_event = asyncio.Event()
    frames = asyncio.run(_collect(cc._drive_tasks(
        session, "trace-test", None, stop_event, max_iterations=10,
    )))

    joined = "".join(frames)
    assert joined.count("event: task_start") == 2
    assert joined.count("event: task_end") == 2
    assert "event: done" in joined
    # 两个子任务各执行一次（顺序与计划一致）
    assert len(calls) == 2
    assert "第一步" in calls[0] and "第二步" in calls[1]
    # done 里必须有子任务结果（OPS-6 契约字段）
    assert [item["status"] for item in session.subtask_results] == ["success", "success"]


def test_interrupt_pauses_then_resume_continues(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第一个子任务中途等确认：流停下（游标不前进）；resume 后接着收尾并跑第二个。

    这是最容易写错的一条：恢复时不能重发第一个子任务的指令，否则会重复执行。
    """
    plan = _prepare(session, _plan())
    _patch_planner(monkeypatch, plan)
    calls = _patch_agent(monkeypatch, interrupt_on="第一步")

    stop_event = asyncio.Event()
    first = asyncio.run(_collect(cc._drive_tasks(
        session, "trace-test", None, stop_event, max_iterations=10,
    )))
    first_joined = "".join(first)

    # 停在第一个子任务：只发了一个 task_start，没有 task_end，也没有 done
    assert first_joined.count("event: task_start") == 1
    assert "event: task_end" not in first_joined
    assert "event: done" not in first_joined
    assert session.task_cursor == 0
    assert session.pending_interrupt_id == "intr-1"

    # 模拟用户点了"同意"：控制器清掉中断，然后以 resume_current 继续
    session.pending_interrupt_id = None
    _patch_agent_noop(monkeypatch)

    second = asyncio.run(_collect(cc._drive_tasks(
        session, "trace-test", None, stop_event, max_iterations=10, resume_current=True,
    )))
    second_joined = "".join(second)

    # 第一子任务收尾 + 第二子任务完整执行 + 汇总
    assert second_joined.count("event: task_end") == 2
    assert second_joined.count("event: task_start") == 1  # 只有第二个子任务新开始
    assert "event: done" in second_joined
    assert len(calls) == 1  # resume 没有重发第一个子任务的指令


def _patch_agent_noop(monkeypatch: pytest.MonkeyPatch):
    """resume 之后第二个子任务用的假 agent（不打断）。"""
    calls: list[str] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True):
        content = graph_input["messages"][-1]["content"]
        calls.append(content)
        sess.turn_text.append("第二步也做完了。")
        yield cc._sse("token", trace_id, {"text": "第二步也做完了。"})

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    return fake_drive


def test_stop_aborts_remaining_subtasks(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """用户点终止：立刻返回，不再跑后面的子任务，也不发 done（stopped 由下层发过）。"""
    _prepare(session, _plan())
    _patch_planner(monkeypatch, _plan())
    _patch_agent(monkeypatch)

    stop_event = asyncio.Event()
    stop_event.set()

    frames = asyncio.run(_collect(cc._drive_tasks(
        session, "trace-test", None, stop_event, max_iterations=10,
    )))

    assert "event: done" not in "".join(frames)
    assert session.task_cursor == 0


def test_disabled_setting_falls_back_to_single_agent(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`task.decompose_enabled=false` 时必须完全走原来的单 agent 链路（零回归）。"""
    from app.services import settings_registry

    original = settings_registry.get_setting("task.decompose_enabled")
    settings_registry.put_settings({"task.decompose_enabled": False})
    try:
        called: list[int] = []

        async def fake_drive(*_args, **_kwargs):
            """单 agent 链路的替身。"""
            called.append(1)
            yield cc._sse("done", "t", {})

        monkeypatch.setattr(cc, "_drive_agent", fake_drive)
        frames = asyncio.run(_collect(cc._run_with_tasks(
            {"messages": [{"role": "user", "content": "把 A 和 B 都改一下"}]},
            "把 A 和 B 都改一下", session, "trace-test", None, 10, asyncio.Event(),
        )))

        assert len(called) == 1
        assert "event: done" in "".join(frames)
        # 没有进入任务模式
        assert session.task_plan is None
    finally:
        settings_registry.put_settings({"task.decompose_enabled": original})
