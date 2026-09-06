# tests/test_trace.py
"""OPS-6 执行轨迹的单元测试。

测的都是"结构正确 + 失败不致命"这两类，而不是"内容好看"：
    轨迹一旦在某条异常路径上抛出去，就会把整轮对话弄挂——那是最不能接受的失败模式。

本文件的用例会往真实的 app.db 写 trace_events，所以每条结束后按 session_id 删掉，
避免污染开发者本机（与 conftest 清理对话记录同一个思路）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：生成唯一会话 id
import uuid
# 标准库：在同步用例里驱动 async 的收尾逻辑（本项目没装 pytest-asyncio）
import asyncio
# 标准库：时间（造一条"很久以前"的记录给清理用例）
from datetime import datetime, timedelta

# 测试框架
import pytest
# SQLAlchemy：删除与查询
from sqlalchemy import delete, select

# 项目内：被测服务
from app.db.db_config import get_session
from app.entity.trace import TraceEvent
from app.services import trace_service


@pytest.fixture()
def session_id():
    """一个唯一的会话 id，并在用例结束后删掉它产生的轨迹。"""
    sid = f"trace-test-{uuid.uuid4().hex[:8]}"
    trace_service.reset_for_test()
    yield sid
    with get_session() as s:
        s.execute(delete(TraceEvent).where(TraceEvent.session_id == sid))
    trace_service.reset_for_test()


def test_record_writes_events_in_seq_order(session_id: str) -> None:
    """同一轮内多条事件的 seq 必须递增，读回来按 seq 有序。"""
    turn = trace_service.begin_turn(session_id, mode="agent")
    trace_service.record(session_id, turn, "tool_call", name="read_file", payload={"input": {"path": "a"}})
    trace_service.record(session_id, turn, "tool_result", name="read_file", duration_ms=12)
    trace_service.record(session_id, turn, "done", payload={"finish_reason": "done"})

    events = trace_service.list_events(session_id, turn_id=turn)

    # begin_turn 自己会写一条 turn_start，所以是 4 条
    kinds = [event["kind"] for event in events]
    assert kinds == ["turn_start", "tool_call", "tool_result", "done"]
    assert [event["seq"] for event in events] == [0, 1, 2, 3]
    assert events[2]["duration_ms"] == 12


def test_disabled_turn_records_nothing(session_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """trace.enabled 关闭时：begin_turn 返回空串，record 直接跳过（零写入）。"""
    monkeypatch.setattr(trace_service, "is_enabled", lambda: False)

    turn = trace_service.begin_turn(session_id)
    assert turn == ""
    trace_service.record(session_id, turn, "tool_call", name="read_file")

    assert trace_service.list_events(session_id) == []


def test_end_turn_resets_seq(session_id: str) -> None:
    """结束一轮后，下一轮的 seq 从 0 重新开始（否则回放顺序会跨轮串起来）。"""
    first = trace_service.begin_turn(session_id)
    trace_service.record(session_id, first, "tool_call", name="a")
    trace_service.end_turn(first)

    second = trace_service.begin_turn(session_id)
    events = trace_service.list_events(session_id, turn_id=second)
    assert [event["seq"] for event in events] == [0]


def test_payload_is_shrunk(session_id: str) -> None:
    """超长字符串必须被截断：否则一次读 8000 字文件就能把 trace 表撑大。"""
    turn = trace_service.begin_turn(session_id)
    trace_service.record(session_id, turn, "tool_result", payload={"text": "字" * 5000, "n": 1})

    payload = trace_service.list_events(session_id, turn_id=turn)[-1]["payload"]
    assert len(payload["text"]) <= trace_service._MAX_STRING_CHARS + 1
    assert payload["text"].endswith("…")
    # 非字符串要原样保留（数字被转成字符串会让后续统计出错）
    assert payload["n"] == 1


def test_write_failure_does_not_raise(session_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """落库失败时只记日志：轨迹是附属品，不能因为它把对话弄挂。"""
    turn = trace_service.begin_turn(session_id)

    def broken():
        """模拟数据库不可用。"""
        raise RuntimeError("db is gone")

    monkeypatch.setattr(trace_service, "get_session", broken)
    # 不抛异常即为通过
    trace_service.record(session_id, turn, "tool_call", name="read_file")


def test_purge_older_than_removes_old_rows(session_id: str) -> None:
    """清理只删超过保留期的记录，新的必须留着。"""
    turn = trace_service.begin_turn(session_id)
    trace_service.record(session_id, turn, "done", payload={"finish_reason": "done"})

    # 手工把这一轮的所有记录都改成 30 天前（不能只改一条：那样剩下的新记录不会被清）
    with get_session() as s:
        rows = s.scalars(select(TraceEvent).where(TraceEvent.session_id == session_id)).all()
        assert len(rows) == 2
        for row in rows:
            row.created_at = datetime.now() - timedelta(days=30)

    removed = trace_service.purge_older_than(7)
    assert removed >= 1
    assert trace_service.list_events(session_id) == []


def test_purge_with_zero_days_is_noop(session_id: str) -> None:
    """keep_days=0 表示永不清理，不能把"0 天"理解成"全删"。"""
    turn = trace_service.begin_turn(session_id)
    trace_service.record(session_id, turn, "done")

    assert trace_service.purge_older_than(0) == 0
    assert len(trace_service.list_events(session_id)) == 2


def test_start_turn_writes_turn_start_exactly_once(session_id: str) -> None:
    """`_start_turn` 只能写一条 turn_start。

    这一条是被真实 bug 逼出来的：`trace_service.begin_turn` 内部已经写过
    turn_start，控制器里如果再加一条，回放时会看到"这一轮开始了两次"，
    看起来像并发错乱，排查成本很高。
    """
    # 项目内：直接驱动控制器的回合起止（这也是真实对话走的两步）
    from app.controllers.chat_controller import SessionState, _finish_turn, _start_turn

    sess = SessionState(session_id=session_id)
    _start_turn(sess, "读一下 a.py", "agent", "trace-test")

    async def _finish() -> None:
        """跑一次异步收尾（检查点删除是 async 的）。"""
        await _finish_turn(sess, "内容如下", "trace-test", finish_reason="done", elapsed=1.0)

    asyncio.run(_finish())

    kinds = [event["kind"] for event in trace_service.list_events(session_id)]
    assert kinds.count("turn_start") == 1
    assert kinds == ["turn_start", "done"]
