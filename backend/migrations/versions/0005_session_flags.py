"""0005_session_flags —— UX-4 收尾：会话置顶 / 归档

为什么加这两列：
    「最近会话」列表按 updated_at 倒序，用得越勤的会话反而会被新会话挤下去；
    用户需要一个"这条别动，永远放最上面"的置顶位。而不再需要但舍不得删的会话，
    则要一个"收起来、不出现在列表里"的归档位——两者都是**会话级开关**，
    删掉会丢历史，所以必须落库，不能只存在前端内存里。

两列都带 server_default，是为了存量行能直接读到 False（SQLite 加非空列时必须有默认值）。

Revision ID: 0005_session_flags
Revises: 0004_memories
Create Date: 2026-10-21
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
revision: str = "0005_session_flags"
# 上一个版本
down_revision: Union[str, None] = "0004_memories"
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
    """给 chat_session 加 pinned / archived 两列（对存量库无破坏，且可重复执行）。"""
    columns = _existing_columns("chat_session")
    if not columns:
        # 表还不存在：交给 create_all 建（它建出来的表本来就带新列）
        return

    if "pinned" not in columns:
        # 置顶标记：True 时列表排序时排在最前（0/1 存 boolean）
        op.add_column("chat_session", sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.text("0"),
            comment="是否置顶：置顶会话排在最近会话列表最前",
        ))
    if "archived" not in columns:
        # 归档标记：True 时默认不出现在列表里（数据仍在，可导出/恢复）
        op.add_column("chat_session", sa.Column(
            "archived", sa.Boolean(), nullable=False, server_default=sa.text("0"),
            comment="是否归档：归档会话默认不列出",
        ))


def downgrade() -> None:
    """回退：去掉两列（SQLite 走 batch 模式重写表）。"""
    columns = _existing_columns("chat_session")
    if not columns:
        return
    with op.batch_alter_table("chat_session") as batch:
        if "archived" in columns:
            batch.drop_column("archived")
        if "pinned" in columns:
            batch.drop_column("pinned")
