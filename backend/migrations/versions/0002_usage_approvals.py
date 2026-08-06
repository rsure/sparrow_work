"""0002_usage_approvals —— UX-5 用量落库 + UX-7 工作区授权表

本次两处结构变更（都来自 M5 前半批的实现）：

1. `chat_message` 增加 `usage_json` / `model` 两列
   —— 没有它们，Token/成本面板只能显示"本轮"，一旦切走或刷新就归零；
      存在消息行上还能正确处理"同一会话中途换模型"（每轮按当时单价记账）。
2. 新增 `approvals` 表
   —— `permission.mode=workspace` 的"记住本工作区授权"必须落库，
      否则重启后又要重新点一遍确认。

Revision ID: 0002_usage_approvals
Revises: 0001_initial
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
revision: str = "0002_usage_approvals"
# 上一个版本：接在基线之后
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    """当前库里已有的表名集合（一次查询，多处复用）。

    :return: 表名集合
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_columns(table: str) -> set[str]:
    """读出当前库里某张表已有的列名（用于把本次迁移做成可重复执行）。

    为什么需要"可重复"：本项目是 `init_db()` 的 create_all **先于** Alembic 运行的
    （见 app/db/db_config.py 的分工说明）。新表会被 create_all 提前建出来，
    随后迁移再 create_table 就会撞 "table already exists"。
    与其改启动顺序（会影响打包版无 migrations 时的兜底），不如让这条迁移自己判断。

    :param table: 表名；不存在时返回空集合（调用方需先用 _table_names 判断表是否存在）
    :return: 列名集合
    """
    if table not in _table_names():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """加两列 + 建授权表（对存量库无破坏，且可重复执行）。"""

    # ---- 1. chat_message 的用量与模型 ----
    # 两列都可空：老数据没有用量信息，读取侧按"没有统计"处理（面板显示 —）
    # 表不存在时整段跳过：那种库（只被 create_all 建了一部分表）会由 create_all 补齐，
    # 而 create_all 建出来的表本来就带新列。
    columns = _existing_columns("chat_message")
    if columns and "usage_json" not in columns:
        op.add_column("chat_message", sa.Column(
            "usage_json", sa.JSON(), nullable=True,
            comment="本轮真实 token 用量（input/output/total）",
        ))
    if columns and "model" not in columns:
        op.add_column("chat_message", sa.Column(
            "model", sa.String(length=120), nullable=True,
            comment="本轮使用的模型（provider/model）",
        ))

    # ---- 2. 工作区级授权 ----
    # create_all 可能已经建过这张表（见 _existing_columns 的说明），存在就跳过
    if "approvals" in _table_names():
        return

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键"),
        sa.Column("workspace_id", sa.String(length=64), nullable=False, comment="工作区 id"),
        sa.Column("tool", sa.String(length=64), nullable=False, comment="被授权的工具名"),
        sa.Column("kind", sa.String(length=16), nullable=False, comment="操作类型（展示用）"),
        sa.Column("target", sa.Text(), nullable=False, comment="首次授权目标（审计用，不参与匹配）"),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        # 同一工作区 + 同一工具只允许一条（upsert 依据）
        sa.UniqueConstraint("workspace_id", "tool", name="uq_approval_workspace_tool"),
    )
    op.create_index("idx_approvals_workspace", "approvals", ["workspace_id"], unique=False)


def downgrade() -> None:
    """回退：删索引与表，再去掉两列（SQLite 走 batch 模式重写表）。"""

    if "approvals" in _table_names():
        op.drop_index("idx_approvals_workspace", table_name="approvals")
        op.drop_table("approvals")

    # SQLite 不支持 DROP COLUMN 的旧版本用 batch 模式兼容；Alembic 会翻译成"建新表 + 拷贝"
    columns = _existing_columns("chat_message")
    if not columns:
        return
    with op.batch_alter_table("chat_message") as batch:
        if "model" in columns:
            batch.drop_column("model")
        if "usage_json" in columns:
            batch.drop_column("usage_json")
