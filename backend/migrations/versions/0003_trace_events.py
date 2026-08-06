"""0003_trace_events —— OPS-6 Agent trace 结构化留存

为什么现在建这张表：
    OPS-6 的**事件契约**在 M2 就冻结了（`GET /api/chat/events`），但落到库里一直没有表，
    导致"这一轮为什么慢 / 在第几步卡住"只能翻控制台日志。本表把每轮的
    turn_start / tool_call / tool_result / confirm / budget / done / error 都记下来，
    既能回放，也能作为 OPS-3 诊断包的取证材料。

Revision ID: 0003_trace_events
Revises: 0002_usage_approvals
Create Date: 2026-10-20
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# typing：标注 revision 链
from typing import Sequence, Union

# Alembic 核心：op 执行 DDL
from alembic import op
# SQLAlchemy：列类型与约束
import sqlalchemy as sa


# 本次迁移的版本号
revision: str = "0003_trace_events"
# 上一个版本
down_revision: Union[str, None] = "0002_usage_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    """当前库里已有的表名集合。

    :return: 表名集合
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """建 trace_events 表（可重复执行）。

    为什么要判存在：本项目 `init_db()` 的 create_all **先于** Alembic 运行，
    新实体一加就会被提前建出来；此时再 `create_table` 会撞 "table already exists"。
    详见 0002 里同一处说明。
    """
    if "trace_events" in _table_names():
        return

    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键"),
        sa.Column("session_id", sa.String(length=64), nullable=False, comment="会话 id（thread_id）"),
        sa.Column("turn_id", sa.String(length=64), nullable=False, comment="轮次 id（一次用户请求一个）"),
        sa.Column("seq", sa.Integer(), nullable=False, comment="轮内步号，回放顺序以它为准"),
        sa.Column("kind", sa.String(length=16), nullable=False, comment="事件类型"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="工具名/阶段名"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="结构化内容（大对象只存引用）"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, comment="该步耗时（毫秒）"),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_events")),
    )
    # 单列索引：按会话 / 按事件类型过滤（"最近的报错"这类查询）
    op.create_index("ix_trace_events_session_id", "trace_events", ["session_id"], unique=False)
    op.create_index("ix_trace_events_turn_id", "trace_events", ["turn_id"], unique=False)
    op.create_index("ix_trace_events_kind", "trace_events", ["kind"], unique=False)
    op.create_index("ix_trace_events_created_at", "trace_events", ["created_at"], unique=False)
    # 复合索引：回放"某会话某一轮"是最高频查询
    op.create_index(
        "idx_trace_session_turn", "trace_events",
        ["session_id", "turn_id", "seq"], unique=False,
    )


def downgrade() -> None:
    """回退：删索引与表。"""
    if "trace_events" not in _table_names():
        return
    for index in (
        "idx_trace_session_turn",
        "ix_trace_events_created_at",
        "ix_trace_events_kind",
        "ix_trace_events_turn_id",
        "ix_trace_events_session_id",
    ):
        op.drop_index(index, table_name="trace_events")
    op.drop_table("trace_events")
