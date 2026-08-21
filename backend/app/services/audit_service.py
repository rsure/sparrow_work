# app/services/audit_service.py
"""
审计落库服务：把工具调用记录写进 SQLite，并提供查询接口。

设计取舍：
    写审计**不能影响工具本身的结果**——落库失败（磁盘满、表不存在）时只记日志、不抛给模型。
    审计是"事后追责"用的，不该成为"工具跑不动"的原因。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：写日志，落库失败时至少留下痕迹
import logging
# 标准库：时间戳
from datetime import datetime

# SQLAlchemy：select 构造查询
from sqlalchemy import select

# 项目内：数据库会话工厂
from app.db.db_config import get_session
# 项目内：审计实体
from app.entity.audit_log import AuditLog

# 本模块专用 logger
log = logging.getLogger("audit")

# output_digest 最多保存多少字符（只保留前若干字符，够定位问题即可）
_DIGEST_CHARS = 500


def record(
    *,
    session_id: str,
    tool: str,
    kind: str,
    target: str,
    detail: str = "",
    level: str = "allow",
    decision: str = "none",
    outcome: str = "skipped",
    output: str = "",
) -> None:
    """写入一条审计记录；任何失败都只写日志，不向上抛。

    :param session_id: 会话 id
    :param tool: 工具名
    :param kind: 操作类型（read/write/exec/net）
    :param target: 目标描述
    :param detail: 动作说明（确认弹窗里那段话）
    :param level: 裁决等级 allow/ask/deny
    :param decision: 用户选择 approved/rejected/none
    :param outcome: 执行结果 ok/fail/skipped
    :param output: 工具返回文本（会被截断保存）
    """
    try:
        with get_session() as s:
            s.add(AuditLog(
                session_id=session_id,
                tool=tool,
                kind=kind,
                target=target,
                detail=detail,
                level=level,
                decision=decision,
                outcome=outcome,
                output_digest=(output or "")[:_DIGEST_CHARS],
            ))
    except Exception as e:  # 审计失败不能影响业务
        log.warning("写审计记录失败: %s", e)


def list_logs(*, session_id: str | None = None, tool: str | None = None,
              limit: int = 100) -> list[dict]:
    """查询审计记录（按时间倒序），供前端"操作记录"页使用。

    :param session_id: 只看某个会话；None 表示不限
    :param tool: 只看某个工具；None 表示不限
    :param limit: 最多返回多少条
    :return: 记录字典列表（字段与 AuditLog 列一一对应，时间转成可读字符串）
    """
    with get_session() as s:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if session_id:
            stmt = stmt.where(AuditLog.session_id == session_id)
        if tool:
            stmt = stmt.where(AuditLog.tool == tool)
        rows = s.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "session_id": r.session_id,
                "tool": r.tool,
                "kind": r.kind,
                "target": r.target,
                "detail": r.detail,
                "level": r.level,
                "decision": r.decision,
                "outcome": r.outcome,
                "output_digest": r.output_digest,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
            }
            for r in rows
        ]