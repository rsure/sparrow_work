# app/entity/trace.py
"""Agent 执行轨迹表（OPS-6）：把一轮对话的每个关键步骤结构化留存。

与审计表（audit_logs）的分工——两者看着像，但回答的问题不同：
    audit_logs  只记"有副作用的工具调用"，面向**追责**：谁批准了哪次落盘；
    trace_events 记这一轮的**全过程**（开始、每次工具调用与结果、确认、预算、结束、报错），
                 面向**回放与排查**：为什么这一轮花了 40 秒、模型在第几步卡住了。

为什么按 (session_id, turn_id, seq) 组织：
    一轮用户请求 = 一个 turn；turn 内步骤按 seq 递增。回放时按 seq 顺序重放即可，
    不需要依赖时间戳（同一毫秒内可能有多条，排序会不稳定）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：时间戳
from datetime import datetime

# SQLAlchemy：列类型、索引、ORM 基类
from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

# 项目内：ORM 基类
from app.entity.models import Base


class TraceEvent(Base):
    """一条执行轨迹事件。"""

    __tablename__ = "trace_events"

    # 主键（自增）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 会话 id（= LangGraph 的 thread_id），回放时按它取整轮
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    # 轮次 id：一次用户请求一个；同一轮的 steer / confirm / budget 都归到它下面
    turn_id: Mapped[str] = mapped_column(String(64), index=True)
    # 轮内步号：从 0 开始递增，回放顺序以它为准（不依赖时间戳）
    seq: Mapped[int] = mapped_column(Integer)
    # 事件类型：turn_start / tool_call / tool_result / confirm / budget / answer / done / error
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # 相关名字：工具名、阶段名；没有则为空串
    name: Mapped[str] = mapped_column(String(64), default="")
    # 结构化内容；大对象只存 EXT-5 的 continuation 引用，不存全文（见服务层说明）
    payload_json: Mapped[dict | None] = mapped_column(
        # none_as_null：Python None 存成 SQL NULL，而不是字符串 'null'
        # （否则 IS NULL 查不出来，导出诊断包时会多出一堆空事件）
        JSON(none_as_null=True), nullable=True,
    )
    # 该步耗时（毫秒）；不适用时为 0
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 记录时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    # 复合索引：查"某个会话某一轮"是最高频的查询（回放、诊断包）
    __table_args__ = (
        Index("idx_trace_session_turn", "session_id", "turn_id", "seq"),
    )
