# tests/test_task_phase2.py
"""TASK Phase 2 自测：分道并行（L3）、文件锁、快照回滚（L4）、失败后重规划。

三个部分都**不调真实模型**：
    分道是纯函数；文件锁只起两个线程抢同一把锁；
    快照只碰临时目录；重规划用假规划器 + 假 `_drive_agent` 精确控制失败与确认。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：跑异步生成器、起线程验证锁、读写临时文件、唯一会话 id
import asyncio
import threading
import uuid

# 测试框架：临时目录、替换依赖
import pytest

# 项目内：被测控制器（重规划/车道恢复都在这里）
from app.controllers import chat_controller as cc
# 项目内：子任务与计划模型（造测试数据用）
from app.schemas.task_plan import SubTask, TaskPlan
# 项目内：被拆分、被测的分道与文件锁、快照服务
from app.services import task_scheduler, task_snapshot
from app.services import settings_registry, task_planner
# 项目内：文件锁（工具层用它兜底同文件并发写）
from app.tools import path_lock


@pytest.fixture(autouse=True)
def _ensure_task_defs():
    """确保 task.* 的设置声明已注册（其它用例会清空注册表，这里不依赖执行顺序）。"""
    from app.services.task_settings_defs import register_task_defs

    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    register_task_defs()
    yield


def _task(tid: int, files: list[str] | None = None, depends: list[int] | None = None) -> SubTask:
    """造一个子任务：只关心 id、涉及文件与依赖。

    :param tid: 子任务编号（计划内唯一）
    :param files: 该子任务会改的文件（决定分道）
    :param depends: 依赖的子任务编号
    :return: SubTask 实例
    """
    return SubTask(
        id=tid,
        title=f"第 {tid} 步",
        description=f"处理第 {tid} 步",
        files=list(files or []),
        depends_on=list(depends or []),
    )


# ---------------------------------------------------------------- 分道（L3）


def test_build_lanes_empty_and_single() -> None:
    """空计划没有车道；一个子任务自成一条车道。"""
    assert task_scheduler.build_lanes([]) == []
    lanes = task_scheduler.build_lanes([_task(1, ["a.md"])])
    assert [[t.id for t in lane] for lane in lanes] == [[1]]


def test_build_lanes_same_file_is_same_lane() -> None:
    """改同一个文件的子任务必须同道（否则两条车道会同时写它）。"""
    tasks = [_task(1, ["a.md"]), _task(2, ["b.md"]), _task(3, ["a.md"])]
    lanes = task_scheduler.build_lanes(tasks)
    assert sorted(sorted(t.id for t in lane) for lane in lanes) == [[1, 3], [2]]


def test_build_lanes_is_transitive_closure() -> None:
    """1↔2 因 a.md、2↔3 因 b.md 相邻，那么 1、2、3 必须三者同道（传递闭包）。"""
    tasks = [
        _task(1, ["a.md"]),
        _task(2, ["a.md", "b.md"]),
        _task(3, ["b.md"]),
    ]
    lanes = task_scheduler.build_lanes(tasks)
    assert len(lanes) == 1
    assert [t.id for t in lanes[0]] == [1, 2, 3]


def test_build_lanes_dependency_forces_same_lane() -> None:
    """跨车道依赖退化为同道：车道之间没有先后约束，依赖关系留到批外就是错的。"""
    tasks = [_task(1, ["a.md"]), _task(2, ["b.md"], depends=[1])]
    lanes = task_scheduler.build_lanes(tasks)
    assert len(lanes) == 1
    assert [t.id for t in lanes[0]] == [1, 2]


def test_build_lanes_orders_inside_lane_and_keeps_all_tasks() -> None:
    """车道内按依赖排序；分道不丢任务、不重复任务。"""
    tasks = [_task(1, ["a.md"], depends=[2]), _task(2, ["a.md"]), _task(3, ["c.md"])]
    lanes = task_scheduler.build_lanes(tasks)
    flat = task_scheduler.flatten_lanes(lanes)
    assert sorted(t.id for t in flat) == [1, 2, 3]
    same_lane = next(lane for lane in lanes if any(t.id == 1 for t in lane))
    assert [t.id for t in same_lane] == [2, 1]


def test_lane_index_maps_task_id_to_lane_number() -> None:
    """子任务 id → 车道号的映射要能被反查（并行日志与调试用）。"""
    lanes = task_scheduler.build_lanes([_task(1, ["a.md"]), _task(2, ["b.md"])])
    mapping = task_scheduler.lane_index(lanes)
    assert mapping == {1: 0, 2: 1}


# ---------------------------------------------------------------- 文件锁


def test_path_lock_serializes_same_path() -> None:
    """两条线程抢同一把锁时不能同时进入临界区（计数最多到 1）。"""
    inside: list[int] = []
    peak = [0]
    guard = threading.Lock()

    def worker() -> None:
        """反复进出临界区，记录并发峰值。"""
        for _ in range(50):
            with path_lock.path_lock("C:/tmp/lock-probe.md"):
                with guard:
                    inside.append(1)
                    peak[0] = max(peak[0], len(inside))
                with guard:
                    inside.pop()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] == 1
    # 引用计数必须回到 0，否则锁表会一直涨
    assert path_lock.locked_count() == 0


def test_path_lock_allows_different_paths_in_parallel() -> None:
    """不同文件互不阻塞（同一文件才串行，否则并行分道没意义）。"""
    held = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def first() -> None:
        """先占住 a.md，等第二个线程拿到 b.md 的锁再放。"""
        with path_lock.path_lock("C:/tmp/a.md"):
            order.append("a")
            held.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=first)
    thread.start()
    held.wait(timeout=5)
    with path_lock.path_lock("C:/tmp/b.md"):
        order.append("b")
    release.set()
    thread.join(timeout=5)

    assert order == ["a", "b"]


# ---------------------------------------------------------------- 快照回滚（L4）


def test_snapshot_and_restore_existing_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """改坏的文件要能还原成快照那一刻的内容。"""
    monkeypatch.setattr(task_snapshot, "snapshots_root", lambda: tmp_path / "snaps")
    target = tmp_path / "note.md"
    target.write_text("原始内容", encoding="utf-8")

    entries = task_snapshot.snapshot_files([str(target)], "turn-1", "1")
    assert entries[0]["existed"] is True

    target.write_text("被改坏了", encoding="utf-8")
    result = task_snapshot.restore(entries)

    assert result["restored"] == 1
    assert target.read_text(encoding="utf-8") == "原始内容"


def test_restore_removes_file_created_by_subtask(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """快照时还不存在的文件，回滚要把它删掉（那是失败子任务新建的）。"""
    monkeypatch.setattr(task_snapshot, "snapshots_root", lambda: tmp_path / "snaps")
    target = tmp_path / "new.md"
    entries = task_snapshot.snapshot_files([str(target)], "turn-2", "2")
    assert entries[0]["existed"] is False

    target.write_text("子任务新建的", encoding="utf-8")
    result = task_snapshot.restore(entries)

    assert result["removed"] == 1
    assert target.exists() is False


def test_snapshot_cleanup_removes_turn_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """一轮结束要把这一轮的快照目录整个删掉，别在数据目录里堆历史。"""
    monkeypatch.setattr(task_snapshot, "snapshots_root", lambda: tmp_path / "snaps")
    target = tmp_path / "a.md"
    target.write_text("x", encoding="utf-8")
    task_snapshot.snapshot_files([str(target)], "turn-3", "1")
    directory = task_snapshot.snapshot_dir("turn-3")
    assert directory.exists() is True

    task_snapshot.cleanup("turn-3")
    # 注意：这里不能再调 snapshot_dir() 去判断——它会顺手把目录建回来
    assert directory.exists() is False


# ---------------------------------------------------------------- 重规划后确认


def _plan() -> TaskPlan:
    """一个两子任务的计划（重规划用例的起点）。"""
    return TaskPlan(
        complexity="complex",
        reason="测试用",
        subtasks=[_task(1, ["a.md"]), _task(2, ["b.md"])],
    )


def test_plan_from_pending_rebuilds_and_rejects_garbage() -> None:
    """待确认的重规划数据要能还原成 TaskPlan；数据不全时宁可返回 None。"""
    pending = {
        "reason": "第 1 步失败，改走另一条路",
        "subtasks": [
            {"id": 1, "title": "重来一次", "description": "", "files": ["a.md"], "depends_on": []},
            {"id": 2, "title": "收尾", "description": "", "files": ["b.md"], "depends_on": [1]},
        ],
    }
    plan = cc._plan_from_pending(pending)
    assert plan is not None and len(plan.subtasks) == 2
    assert plan.reason.startswith("第 1 步失败")

    # 只有一个子任务 → 不算复杂任务，返回 None
    assert cc._plan_from_pending({"subtasks": [pending["subtasks"][0]]}) is None
    # 字段类型坏掉 → 返回 None（不让一次解析失败把整轮断掉）
    assert cc._plan_from_pending({"subtasks": [{"id": "x"}, {"id": "y"}]}) is None


def test_rejected_replan_keeps_original_plan(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户拒绝重规划时：原计划不变，剩下的子任务继续跑完并汇总。"""
    plan = _plan()
    session.task_plan = plan
    session.task_cursor = 1
    session.task_original = "把 A 和 B 都改一下"
    session.pending_action = "replan"
    session.task_replan_pending = {
        "reason": "换条路",
        "subtasks": [{"id": 1, "title": "新第 1 步", "files": [], "depends_on": []},
                     {"id": 2, "title": "新第 2 步", "files": [], "depends_on": []}],
    }
    # 真实链路上 `_run_resume_stream` 在分发前就把 pending_interrupt_id 清掉了，
    # 这里直接调 `_run_replan_resume`，得自己模拟这一步（否则 _drive_tasks 以为还在等确认）
    session.pending_interrupt_id = None
    seen: list[list[int]] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True):
        """子任务的替身：直接追加一句话，不产生输出帧；顺手记下当时的计划。"""
        seen.append([t.id for t in sess.task_plan.subtasks])
        sess.turn_text.append("做完了。")
        if False:  # pragma: no cover - 让函数保持异步生成器语义
            yield ""

    async def fake_summary(_original: str, _plan: TaskPlan) -> str:
        """汇总的替身。"""
        return "全部完成。"

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    monkeypatch.setattr(task_planner, "summarize", fake_summary)
    monkeypatch.setattr(cc, "_register_run", lambda _sid: asyncio.Event())
    monkeypatch.setattr(cc, "_unregister_run", lambda _sid, _ev: None)

    req = cc.ChatResumeRequest(session_id=session.session_id, interrupt_id="replan-1",
                               approved=False)
    frames = asyncio.run(_collect(cc._run_replan_resume(session, req, "trace-test", None)))
    text = "\n".join(frames)

    # 保留原计划：跑的还是原来那两个子任务，没有 plan_update，最后有 done
    # （注意不能在看结果时读 session.task_plan：_finish_turn 收尾时已经把它清掉了）
    assert seen and seen[0] == [1, 2]
    assert "event: plan_update" not in text
    assert "event: plan" in text
    assert session.task_replan_pending == {}
    assert session.pending_action is None
    assert "event: done" in text


def test_approved_replan_swaps_plan_and_restarts_cursor(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """用户采纳重规划时：换成新计划、游标归零、并广播 plan_update（pending=false）。"""
    session.task_plan = _plan()
    session.task_cursor = 2
    session.task_original = "把 A 和 B 都改一下"
    session.pending_action = "replan"
    session.task_replan_pending = {
        "reason": "换条路",
        "subtasks": [{"id": 11, "title": "新第 1 步", "files": [], "depends_on": []},
                     {"id": 12, "title": "新第 2 步", "files": [], "depends_on": []}],
    }
    # 同上：`_run_resume_stream` 会先清掉 pending_interrupt_id 再分发
    session.pending_interrupt_id = None
    seen: list[list[int]] = []
    session.pending_interrupt_id = None
    seen: list[list[int]] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True):
        """子任务的替身：记录到底跑了哪些子任务编号。"""
        seen.append([t.id for t in sess.task_plan.subtasks])
        sess.turn_text.append("做完了。")
        if False:  # pragma: no cover
            yield ""

    async def fake_summary(_original: str, _plan: TaskPlan) -> str:
        """汇总的替身。"""
        return "全部完成。"

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    monkeypatch.setattr(task_planner, "summarize", fake_summary)
    monkeypatch.setattr(cc, "_register_run", lambda _sid: asyncio.Event())
    monkeypatch.setattr(cc, "_unregister_run", lambda _sid, _ev: None)

    req = cc.ChatResumeRequest(session_id=session.session_id, interrupt_id="replan-2",
                               approved=True)
    frames = asyncio.run(_collect(cc._run_replan_resume(session, req, "trace-test", None)))
    text = "\n".join(frames)

    # 采纳重规划：新计划的子任务编号是 11/12，广播 plan_update（pending=false），最后有 done
    assert seen and seen[0] == [11, 12]
    assert '"pending": false' in text
    assert '"reason": "换条路"' in text
    assert "event: done" in text


# ---------------------------------------------------------------- 会话状态复位


def test_finish_turn_cleans_lane_threads_and_snapshots(
    session, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """一轮结束时车道 thread 与快照目录都要清掉（否则 checkpointer 和数据目录越积越多）。"""
    monkeypatch.setattr(task_snapshot, "snapshots_root", lambda: tmp_path / "snaps")
    deleted: list[str] = []

    class _FakeSaver:
        """替代真实的异步检查点，只记下被清理的 thread。"""

        async def adelete_thread(self, thread_id: str) -> None:
            """记录一次删除（真实实现会去 app.db 删 checkpoints / writes）。"""
            deleted.append(thread_id)

    # 检查点现在是异步实现：控制器调用 adelete_thread，这里换成同样是 async 的假对象
    monkeypatch.setattr(cc, "checkpointer", _FakeSaver())

    session.task_lane_threads = ["sid#l0", "sid#l1"]
    target = tmp_path / "a.md"
    target.write_text("x", encoding="utf-8")
    session.task_snapshots = {1: task_snapshot.snapshot_files(
        [str(target)], session.trace_turn_id, "1")}
    turn_dir = task_snapshot.snapshot_dir(session.trace_turn_id)

    asyncio.run(cc._cleanup_task_resources(session))

    assert deleted == ["sid#l0", "sid#l1"]
    assert session.task_lane_threads == []
    assert session.task_snapshots == {}
    assert turn_dir.exists() is False


def test_task_concurrency_reads_setting(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """并发度取自 `task.max_parallel_subtasks`，并被夹在 1..4 之间。"""
    original = settings_registry.get_setting("task.max_parallel_subtasks")
    try:
        settings_registry.put_settings({"task.max_parallel_subtasks": 3})
        assert cc._task_concurrency() == 3
        settings_registry.put_settings({"task.max_parallel_subtasks": 4})
        assert cc._task_concurrency() == 4
        settings_registry.put_settings({"task.max_parallel_subtasks": 1})
        assert cc._task_concurrency() == 1
    finally:
        settings_registry.put_settings({"task.max_parallel_subtasks": original})


# ---------------------------------------------------------------- 并行执行


def test_parallel_lanes_run_each_subtask_once(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发度 2 时两条车道各跑一个子任务：每个只跑一次、各用独立 thread、最后有 done。"""
    original = settings_registry.get_setting("task.max_parallel_subtasks")
    settings_registry.put_settings({"task.max_parallel_subtasks": 2})
    session.task_plan = TaskPlan(
        complexity="complex",
        reason="测试用",
        subtasks=[_task(1, ["a.md"]), _task(2, ["b.md"])],
    )
    session.task_cursor = 0
    session.task_original = "把 A 和 B 都改一下"

    ran: list[str] = []
    threads: list[str | None] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True, thread_id=None, persist=True):
        """子任务的替身：记下跑了哪一步、用的哪个 thread_id，并推一个 token 帧。"""
        ran.append(graph_input["messages"][-1]["content"])
        threads.append(thread_id)
        # 让两条车道真的有机会交错执行（并行链路如果退化成串行，这里也不会报错，但线程 id 会重复）
        await asyncio.sleep(0.01)
        sess.turn_text.append("做完了。")
        yield cc._sse("token", trace_id, {"text": "做完了。"})

    async def fake_summary(_original: str, _plan: TaskPlan) -> str:
        """汇总的替身。"""
        return "全部完成。"

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    monkeypatch.setattr(task_planner, "summarize", fake_summary)

    try:
        frames = asyncio.run(_collect(cc._drive_tasks(
            session, "trace-test", None, asyncio.Event(), max_iterations=10,
        )))
        text = "\n".join(frames)
    finally:
        settings_registry.put_settings({"task.max_parallel_subtasks": original})

    assert len(ran) == 2
    # 两条车道各用独立 thread_id："<session>#l<n>"，不再共用主会话的 thread
    assert len(set(threads)) == 2
    assert all(tid and tid.startswith(f"{session.session_id}#l") for tid in threads)
    assert "event: done" in text
    # 两个车道的产出都并回了主会话文本（车道文本是整段并回来的，不是逐 token）
    assert "".join(session.turn_text).count("做完了。") == 2


def test_parallel_disabled_runs_serially(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发度 1（默认）时不走车道：所有子任务共用主会话的 thread_id。"""
    session.task_plan = TaskPlan(
        complexity="complex",
        reason="测试用",
        subtasks=[_task(1, ["a.md"]), _task(2, ["b.md"])],
    )
    session.task_cursor = 0
    session.task_original = "把 A 和 B 都改一下"
    threads: list[str | None] = []

    async def fake_drive(graph_input, sess, trace_id, http_request, max_iterations, stop_event,
                         *, verbose=False, finalize=True, thread_id=None, persist=True):
        """子任务的替身：只记录 thread_id，用来确认没分道。"""
        threads.append(thread_id)
        sess.turn_text.append("做完了。")
        yield cc._sse("token", trace_id, {"text": "做完了。"})

    async def fake_summary(_original: str, _plan: TaskPlan) -> str:
        """汇总的替身。"""
        return "全部完成。"

    monkeypatch.setattr(cc, "_drive_agent", fake_drive)
    monkeypatch.setattr(task_planner, "summarize", fake_summary)

    asyncio.run(_collect(cc._drive_tasks(
        session, "trace-test", None, asyncio.Event(), max_iterations=10,
    )))

    assert threads == [None, None]


@pytest.fixture()
def session():
    """一个干净的会话对象（含本轮初始化），用例结束清掉历史与轨迹。"""
    sid = f"task-p2-{uuid.uuid4().hex[:8]}"
    sess = cc.SessionState(session_id=sid)
    cc._start_turn(sess, "把 A 和 B 都改一下", "agent", "trace-test")
    yield sess
    # 项目内：收尾用的历史与轨迹服务
    from app.services import chat_history_service as history
    from app.services import trace_service

    trace_service.end_turn(sess.trace_turn_id)
    history.delete_session(sid)


async def _collect(gen) -> list[str]:
    """把异步生成器里的帧收集起来（帧本身就是 SSE 字符串）。"""
    return [frame async for frame in gen]
