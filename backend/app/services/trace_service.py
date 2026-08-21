# app/services/trace_service.py
"""Agent 执行轨迹落库（OPS-6）。

三条硬约束（改这个文件前先看）：
    1. **失败绝不影响对话**：所有函数内部吞异常、只记日志。轨迹是"事后复盘"用的，
       不能因为磁盘满或表不存在就把用户这一轮弄挂。
    2. **开关是 `trace.enabled`**：关掉后不产生任何写入（连 seq 计数都不动），
       这样"关掉后零影响"是真的零影响，而不是"少写一点"。
    3. **不存大文本**：payload 里的长字符串会被截断到 2k 字符；工具输出的完整内容
       本来就已经被 EXT-5 落到 `tool-out-*` 里，这里只存它的引用与长度。

seq 的语义：一轮内的步号，从 0 递增。之所以自己维护而不是用数据库自增 id：
    回放要按"这一轮的顺序"读，而全局自增 id 会被其它并发会话穿插，
    直接 order by id 会读出错乱的顺序。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：日志（落库失败时留痕）
import logging
# 标准库：生成轮次 id
import uuid
# 标准库：时间戳与过期清理
from datetime import datetime, timedelta
# 标准库：线程锁（SSE 在多个线程/协程里并发写）
import threading
# 标准库：Any 标注 payload
from typing import Any

# SQLAlchemy：查询与删除，func 用于聚合（统计每个会话/轮次的事件条数）
from sqlalchemy import delete, func, select

# 项目内：数据库会话
from app.db.db_config import get_session
# 项目内：轨迹实体
from app.entity.trace import TraceEvent

# 本模块专用 logger
log = logging.getLogger("trace")

# payload 里单个字符串最多保留多少字符。超过就截断并标注，
# 避免"模型一次读了 8000 字文件"把 trace 表撑爆
_MAX_STRING_CHARS = 2000

# 最多同时跟踪多少个轮次的 seq（防止异常情况下无界增长）
_MAX_TRACKED_TURNS = 200


# turn_id → 下一个可用的 seq
_seq_by_turn: dict[str, int] = {}
# 保护 _seq_by_turn
_seq_lock = threading.Lock()


def is_enabled() -> bool:
    """轨迹留存是否开启（设置键 `trace.enabled`，读不到时按关闭处理）。

    为什么读不到按关闭：轨迹是"锦上添花"，读配置失败时更应该少做事情，
    而不是往一个未知状态的数据库里写。
    """
    try:
        # 项目内：延迟导入，避免模块导入期依赖数据库
        from app.services.settings_registry import get_setting

        return bool(get_setting("trace.enabled"))
    except Exception:
        return False


def _next_seq(turn_id: str) -> int:
    """取该轮的下一个步号（从 0 开始）。

    :param turn_id: 轮次 id
    :return: 步号
    """
    with _seq_lock:
        seq = _seq_by_turn.get(turn_id, 0)
        _seq_by_turn[turn_id] = seq + 1
        # 防御性清理：正常情况下 end_turn 会删，这里兜住"忘记调 end_turn"的路径
        if len(_seq_by_turn) > _MAX_TRACKED_TURNS:
            for key in list(_seq_by_turn)[: _MAX_TRACKED_TURNS // 2]:
                _seq_by_turn.pop(key, None)
        return seq


def _shrink(value: Any, depth: int = 0) -> Any:
    """把 payload 压到"能存进 JSON 列且不撑爆表"的规模。

    :param value: 原始值
    :param depth: 当前递归深度（超过 4 层直接字符串化，避免病态嵌套）
    :return: 可 JSON 序列化的值
    """
    if depth > 4:
        return str(value)[:_MAX_STRING_CHARS]
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING_CHARS else value[:_MAX_STRING_CHARS] + "…"
    if isinstance(value, dict):
        return {str(k): _shrink(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_shrink(item, depth + 1) for item in list(value)[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # 模型对象、异常等：转字符串，别让 json.dumps 崩掉
    return str(value)[:_MAX_STRING_CHARS]


def begin_turn(
    session_id: str,
    *,
    mode: str = "agent",
    extra: dict[str, Any] | None = None,
) -> str:
    """开启一轮轨迹（并写下 turn_start 事件），返回轮次 id。

    注意：turn_start 由本函数自己写，**调用方不要再写一遍**——
    重复写会让回放时看到两条"这一轮开始"，看起来像 bug。

    :param session_id: 会话 id
    :param mode: 本轮模式（agent / doc）
    :param extra: 追加到 turn_start payload 的字段（如 message_chars）
    :return: turn_id；轨迹关闭时返回空串（调用方据此跳过后续所有写入）
    """
    if not is_enabled():
        return ""
    turn_id = f"t{uuid.uuid4().hex[:12]}"
    with _seq_lock:
        _seq_by_turn[turn_id] = 0
    payload: dict[str, Any] = {"mode": mode}
    if extra:
        payload.update(extra)
    record(session_id, turn_id, "turn_start", payload=payload)
    return turn_id


def end_turn(turn_id: str) -> None:
    """一轮结束，清掉它的 seq 计数。

    :param turn_id: 轮次 id
    """
    if not turn_id:
        return
    with _seq_lock:
        _seq_by_turn.pop(turn_id, None)


def record(
    session_id: str,
    turn_id: str,
    kind: str,
    *,
    name: str = "",
    payload: dict[str, Any] | None = None,
    duration_ms: int = 0,
) -> None:
    """写一条轨迹事件；任何失败都只记日志。

    :param session_id: 会话 id
    :param turn_id: 轮次 id；空串表示本轮不记（轨迹关闭）
    :param kind: 事件类型
    :param name: 工具名/阶段名
    :param payload: 结构化内容（会被截断）
    :param duration_ms: 该步耗时（毫秒）
    """
    if not turn_id:
        return
    try:
        seq = _next_seq(turn_id)
        with get_session() as s:
            s.add(TraceEvent(
                session_id=session_id,
                turn_id=turn_id,
                seq=seq,
                kind=kind,
                name=(name or "")[:64],
                payload_json=_shrink(payload) if payload else None,
                duration_ms=max(0, int(duration_ms)),
            ))
    except Exception as exc:  # 轨迹写失败不能影响对话
        log.warning("写轨迹失败（%s/%s）：%s", kind, name, exc)


def list_events(session_id: str, *, turn_id: str | None = None, limit: int = 500) -> list[dict]:
    """按顺序读某个会话（可选某一轮）的轨迹。

    :param session_id: 会话 id
    :param turn_id: 只看某一轮；None 表示整个会话（按写入顺序）
    :param limit: 最多返回多少条
    :return: 事件字典列表
    """
    with get_session() as s:
        stmt = select(TraceEvent).where(TraceEvent.session_id == session_id)
        if turn_id:
            stmt = stmt.where(TraceEvent.turn_id == turn_id).order_by(TraceEvent.seq)
        else:
            stmt = stmt.order_by(TraceEvent.id)
        rows = s.scalars(stmt.limit(limit)).all()
        return [
            {
                "id": row.id,
                "session_id": row.session_id,
                "turn_id": row.turn_id,
                "seq": row.seq,
                "kind": row.kind,
                "name": row.name,
                "payload": row.payload_json,
                "duration_ms": row.duration_ms,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


def list_trace_sessions(limit: int = 50) -> list[dict]:
    """列出"有轨迹的会话"，供轨迹回放页选一个会话看（ARCH-7 回放入口）。

    为什么需要它：原来只有 `GET /trace/sessions/{id}`——必须先知道 session_id 才能看轨迹，
    而 session_id 用户根本记不住（那是 uuid）。回放页得先能"挑一个"。

    :param limit: 最多返回多少个会话（按最近有轨迹的时间倒序）
    :return: [{"session_id","event_count","turn_count","started_at","last_at"}]
    """
    with get_session() as s:
        last_at = func.max(TraceEvent.created_at)
        rows = s.execute(
            select(
                TraceEvent.session_id,
                func.count(TraceEvent.id),
                # 一轮的轨迹有很多条，这里按 turn_id 去重数"聊了几轮"
                func.count(func.distinct(TraceEvent.turn_id)),
                func.min(TraceEvent.created_at),
                last_at,
            )
            .group_by(TraceEvent.session_id)
            .order_by(last_at.desc())
            .limit(limit)
        ).all()
    return [
        {
            "session_id": session_id,
            "event_count": int(event_count or 0),
            "turn_count": int(turn_count or 0),
            "started_at": started.isoformat() if started else None,
            "last_at": last.isoformat() if last else None,
        }
        for session_id, event_count, turn_count, started, last in rows
    ]


def list_turns(session_id: str, limit: int = 50) -> list[dict]:
    """列出某个会话里的轮次（按最近一轮在前），供回放页按轮切换。

    回放的最小单位是"一轮"而不是"一条事件"：用户想复盘的是"这一次提问，
    Agent 先想了什么、调了哪些工具、最后怎么收尾"，跨轮混在一起看没有意义。

    :param session_id: 会话 id
    :param limit: 最多返回多少轮
    :return: [{"turn_id","event_count","mode","started_at","last_at"}]
    """
    with get_session() as s:
        rows = s.execute(
            select(
                TraceEvent.turn_id,
                func.count(TraceEvent.id),
                func.min(TraceEvent.created_at),
                func.max(TraceEvent.created_at),
            )
            .where(TraceEvent.session_id == session_id)
            .group_by(TraceEvent.turn_id)
            .order_by(func.max(TraceEvent.created_at).desc())
            .limit(limit)
        ).all()
        # 每轮的第一条（seq=0）是 turn_start，它的 payload 里记着 mode（agent / doc）
        starts = s.execute(
            select(TraceEvent.turn_id, TraceEvent.payload_json)
            .where(TraceEvent.session_id == session_id, TraceEvent.seq == 0)
        ).all()
    modes = {turn_id: (payload or {}).get("mode", "") for turn_id, payload in starts}
    return [
        {
            "turn_id": turn_id,
            "event_count": int(event_count or 0),
            "mode": modes.get(turn_id, ""),
            "started_at": started.isoformat() if started else None,
            "last_at": last.isoformat() if last else None,
        }
        for turn_id, event_count, started, last in rows
    ]


def recent(limit: int = 2000) -> list[dict]:
    """最近的轨迹事件（诊断包用，跨会话）。

    :param limit: 最多返回多少条
    :return: 事件字典列表（按 id 升序，便于阅读）
    """
    with get_session() as s:
        rows = s.scalars(
            select(TraceEvent).order_by(TraceEvent.id.desc()).limit(limit)
        ).all()
    # 倒序取出来后再翻回来，保证导出文件是"时间正序"，人读起来更顺
    return [
        {
            "session_id": row.session_id,
            "turn_id": row.turn_id,
            "seq": row.seq,
            "kind": row.kind,
            "name": row.name,
            "payload": row.payload_json,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in reversed(rows)
    ]


def purge_older_than(days: int) -> int:
    """删掉超过 N 天的轨迹（`trace.keep_days`）。

    为什么必须能清理：每轮对话就是几十条记录，用一年下来单靠这张表就能占掉几十 MB，
    而超过一周的轨迹在排查问题时基本没用。

    :param days: 保留天数（<=0 表示不清理）
    :return: 删除条数
    """
    if days <= 0:
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    try:
        with get_session() as s:
            result = s.execute(delete(TraceEvent).where(TraceEvent.created_at < cutoff))
            return int(result.rowcount or 0)
    except Exception as exc:
        log.warning("清理轨迹失败：%s", exc)
        return 0


def reset_for_test() -> None:
    """清空 seq 计数（用例隔离用，不删库）。"""
    with _seq_lock:
        _seq_by_turn.clear()
