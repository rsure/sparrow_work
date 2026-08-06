"""0006_memory_lifecycle —— MEM 增强：记忆的生命周期字段

为什么加这三列：
    记忆不再只增不减。要做"过期淘汰"，必须先能回答"这条记忆最近有没有被用到"——
    只按创建时间删，会把一条半年前写下、但这周刚被检索命中的偏好删掉。
    所以：
        last_used_at   最近一次被检索命中的时间（NULL 表示从未命中）
        use_count      累计命中次数（与 last_used_at 一起构成"有用程度"的证据）
        merged_count   被合并进来的次数（近似重复不再丢弃，而是合并到已有条目上）

三列都带 server_default，是为了存量行能直接读到 0（SQLite 加非空列时必须有默认值）；
last_used_at 允许为空——"从没用过"本身就是有意义的信息，不能拿 1970 年冒充。

Revision ID: 0006_memory_lifecycle
Revises: 0005_session_flags
Create Date: 2026-10-23
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
revision: str = "0006_memory_lifecycle"
# 上一个版本
down_revision: Union[str, None] = "0005_session_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    """当前库里已有的表名集合。

    :return: 表名集合
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_columns(table: str) -> set[str]:
    """读出某张表已有的列名（让本次迁移可重复执行）。

    为什么要判：本项目 `init_db()` 的 create_all **先于** Alembic 运行，
    新实体列会被提前建出来；此时再 add_column 会撞 "duplicate column name"。
    详见 0002 里同一处说明。

    :param table: 表名；不存在时返回空集合
    :return: 列名集合
    """
    if table not in _table_names():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """给 memories 加生命周期三列（对存量库无破坏，且可重复执行）。"""
    columns = _existing_columns("memories")
    if not columns:
        # 表还不存在：交给 create_all 建（它建出来的表本来就带新列）
        return

    if "last_used_at" not in columns:
        # 最近一次被检索命中的时间；NULL 表示从未命中
        op.add_column("memories", sa.Column(
            "last_used_at", sa.DateTime(), nullable=True,
            comment="最近一次被检索命中的时间（UTC；NULL=从未命中）",
        ))
    if "use_count" not in columns:
        # 累计命中次数
        op.add_column("memories", sa.Column(
            "use_count", sa.Integer(), nullable=False, server_default=sa.text("0"),
            comment="被检索命中的累计次数",
        ))
    if "merged_count" not in columns:
        # 被合并进来的次数
        op.add_column("memories", sa.Column(
            "merged_count", sa.Integer(), nullable=False, server_default=sa.text("0"),
            comment="被合并进这条记忆的次数（近似重复不再丢弃，而是合并）",
        ))


def downgrade() -> None:
    """回退：去掉三列（SQLite 走 batch 模式重写表）。"""
    columns = _existing_columns("memories")
    if not columns:
        return
    with op.batch_alter_table("memories") as batch:
        if "merged_count" in columns:
            batch.drop_column("merged_count")
        if "use_count" in columns:
            batch.drop_column("use_count")
        if "last_used_at" in columns:
            batch.drop_column("last_used_at")
