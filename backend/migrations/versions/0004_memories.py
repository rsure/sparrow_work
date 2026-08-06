"""0004_memories —— MEM 工作空间记忆

为什么建这张表：
    对话记录是**流水**（越用越长、检索靠关键词），用户真正需要的是从流水里提炼出的
    **结论**：定了什么方案、偏好什么写法、还有什么事没做。本表存这些一句话陈述，
    按工作区隔离，新对话开场时按相似度取回 top-K 注入，让模型不用每次从零理解项目。

Revision ID: 0004_memories
Revises: 0003_trace_events
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
revision: str = "0004_memories"
# 上一个版本
down_revision: Union[str, None] = "0003_trace_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    """当前库里已有的表名集合。

    :return: 表名集合
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """建 memories 表（可重复执行）。

    为什么要判存在：本项目 `init_db()` 的 create_all **先于** Alembic 运行，
    新实体一加就会被提前建出来；此时再 `create_table` 会撞 "table already exists"。
    详见 0002 里同一处说明。
    """
    if "memories" in _table_names():
        return

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键"),
        sa.Column(
            "workspace_id", sa.String(length=64), nullable=False, server_default="",
            comment="所属工作区 id（记忆按工作区隔离）",
        ),
        sa.Column("session_id", sa.String(length=64), nullable=True, comment="来源会话 id（溯源用）"),
        sa.Column("content", sa.Text(), nullable=False, comment="记忆正文（一句话陈述）"),
        sa.Column(
            "category", sa.String(length=16), nullable=False, server_default="fact",
            comment="preference / decision / fact / todo",
        ),
        sa.Column(
            "importance", sa.Integer(), nullable=False, server_default="3",
            comment="重要度 1~5，检索排序权重",
        ),
        sa.Column(
            "source", sa.String(length=16), nullable=False, server_default="auto",
            comment="auto=自动抽取 / manual=手动添加",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False, comment="正文 SHA-256（完全相同直接去重）"),
        sa.Column(
            "embedding", sa.LargeBinary(), nullable=True,
            comment="向量 BLOB（float32 小端）；为空表示尚未向量化",
        ),
        sa.Column("dim", sa.Integer(), nullable=True, comment="向量维度；与当前维度不符则不参与检索"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    # 按工作区取记忆是最高频查询（注入与列表都走它）
    op.create_index("idx_memories_workspace", "memories", ["workspace_id", "id"], unique=False)
    # 按正文哈希去重
    op.create_index("ix_memories_content_hash", "memories", ["content_hash"], unique=False)


def downgrade() -> None:
    """回退：删索引与表（记忆是可重建的派生数据，直接丢弃安全）。"""
    if "memories" not in _table_names():
        return
    op.drop_index("ix_memories_content_hash", table_name="memories")
    op.drop_index("idx_memories_workspace", table_name="memories")
    op.drop_table("memories")
