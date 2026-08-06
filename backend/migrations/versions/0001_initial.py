"""0001_initial —— 初始迁移基线（对应 doc/24 OPS-1）

这一版把**当前已有的全部表结构冻结**下来，让今后加字段可以走
`alembic revision --autogenerate`平滑升级，而不是靠裸 create_all 蒙混。

为什么是手写而不是 autogenerate（重要经验）：
    对着**已经建好表**的库跑 autogenerate，它会认为"数据库里多出来的表应该删掉"，
    于是生成一份 DROP TABLE 的反向迁移——本项目会连LangGraph 的
    checkpoints / writes（对话检查点）一起删掉，直接毁掉用户历史对话。
    所以基线必须手写：逐张表 CREATE，与现有结构逐字段对齐。

**范围说明**：
    - 收录业务表（app_settings / chat_* / audit_logs / task_info）与 RAG 表
      （documents / chunks / index_meta）；
    - **不收录** LangGraph 的 checkpoints / writes——它们由 langgraph 自己建、自己管
      （见 app/agents/rag_agent.py 的 SqliteSaver），不归 ORM 管，交给 Alembic 反而危险。

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-20
"""
# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# typing：标注 revision 链与 downgrade 参数
from typing import Sequence, Union

# Alembic 核心：op 执行 DDL
from alembic import op
# SQLAlchemy：列类型
import sqlalchemy as sa


# 本次迁移的版本号（手写固定成可读的 0001_initial，便于长期追溯）
revision: str = "0001_initial"
# 上一个版本：None 表示这是链上的第一个迁移
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建出全部业务表与 RAG 表（与迁移前 create_all 的结果逐字段一致）。"""

    # ---------------- 业务表（app/db/db_config.Base）----------------
    # 应用设置：键值对，value 存 JSON 字符串（见 services/setting_service.py）
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False, comment="设置键，组.键命名空间"),
        sa.Column("value", sa.Text(), nullable=False, comment="设置值（JSON 序列化后的文本）"),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )

    # 对话会话：前端"最近会话"列表的数据源
    op.create_table(
        "chat_session",
        sa.Column("session_id", sa.String(length=32), nullable=False, comment="会话 id（thread_id）"),
        sa.Column("title", sa.String(length=200), nullable=False, comment="会话标题（取首条消息摘要）"),
        sa.Column("mode", sa.String(length=16), nullable=False, comment="对话模式：agent / doc"),
        sa.Column("message_count", sa.Integer(), nullable=False, comment="消息条数，用于列表展示"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_chat_session")),
    )

    # 对话消息：一条可见消息（提问/回答、工具轨迹、结束原因）
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键"),
        sa.Column("session_id", sa.String(length=32), nullable=False, comment="所属会话"),
        sa.Column("role", sa.String(length=16), nullable=False, comment="角色：user / assistant / tool"),
        sa.Column("content", sa.Text(), nullable=False, comment="消息正文"),
        sa.Column("mode", sa.String(length=16), nullable=False, comment="对话模式：agent / doc"),
        sa.Column("tool_calls", sa.JSON(), nullable=True, comment="工具调用轨迹（JSON）"),
        sa.Column("finish_reason", sa.String(length=20), nullable=False, comment="结束原因"),
        sa.Column("elapsed", sa.Float(), nullable=True, comment="耗时（秒）"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_message")),
        # 会话被删时连带删掉它的消息，避免留下孤儿记录
        sa.ForeignKeyConstraint(["session_id"], ["chat_session.session_id"], ondelete="CASCADE"),
    )

    # 工具操作审计：谁在什么时候做了什么、结果如何
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键"),
        sa.Column("session_id", sa.String(length=64), nullable=False, comment="会话 id（脚本调用时为空串）"),
        sa.Column("tool", sa.String(length=64), nullable=False, comment="工具名"),
        sa.Column("kind", sa.String(length=16), nullable=False, comment="操作类型：read/write/exec/net"),
        sa.Column("target", sa.Text(), nullable=False, comment="操作目标（路径或命令）"),
        sa.Column("detail", sa.Text(), nullable=False, comment="裁决说明"),
        sa.Column("level", sa.String(length=8), nullable=False, comment="裁决等级：allow/ask/deny"),
        sa.Column("decision", sa.String(length=12), nullable=False, comment="用户决定：approved/rejected/none"),
        sa.Column("outcome", sa.String(length=12), nullable=False, comment="结果：ok/fail/skipped"),
        sa.Column("output_digest", sa.Text(), nullable=False, comment="输出摘要（不存全文，避免撑爆库）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="发生时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )

    # 文件扫描任务：一次扫描一行，记录进度与结果概览
    op.create_table(
        "task_info",
        sa.Column("task_id", sa.String(length=32), nullable=False, comment="任务 id"),
        sa.Column("path", sa.String(length=500), nullable=False, comment="扫描的根目录"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="状态：pending/running/done/failed"),
        sa.Column("scanned", sa.Integer(), nullable=False, comment="已扫描文件数"),
        sa.Column("total_bytes", sa.Integer(), nullable=False, comment="累计字节数"),
        sa.Column("skipped", sa.Integer(), nullable=False, comment="跳过的条目数"),
        sa.Column("error", sa.String(length=500), nullable=True, comment="失败原因"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("ended_at", sa.DateTime(), nullable=True, comment="结束时间"),
        sa.Column("result_json", sa.JSON(), nullable=True, comment="扫描结果汇总（JSON）"),
        sa.Column("files_json", sa.JSON(), nullable=True, comment="文件明细（JSON）"),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_task_info")),
    )

    # ---------------- RAG 表（app/entity/models.Base）----------------
    # 已导入文档：知识库的一篇文档
    # 注：主键写成 PRIMARY KEY（不带 AUTOINCREMENT）以对齐真实库的 `INTEGER PRIMARY KEY`。
    # SQLite 里 INTEGER PRIMARY KEY 本就是 rowid，别名，autoincrement 是多余的；
    # 若这里写 autoincrement=True，autogenerate 之后每次都会报"多出的自增"，
    # 生成一堆无意义的 alter 迁移来"修"它。
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键（SQLite 下即 rowid 别名）"),
        sa.Column("source", sa.String(length=1024), nullable=False, comment="来源绝对路径"),
        sa.Column("title", sa.String(length=512), nullable=True, comment="展示标题"),
        sa.Column("doc_hash", sa.String(length=64), nullable=False, comment="内容哈希（判断是否需要重新切片）"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        # 同一路径只入库一次，重复导入走更新
        sa.UniqueConstraint("source", name=op.f("uq_documents_source")),
    )

    # 文本切片：一篇文档切成若干块，每块带向量
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False, comment="自增主键（SQLite 下即 rowid 别名）"),
        sa.Column("doc_id", sa.Integer(), nullable=False, comment="所属文档 id"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="第几块（从 0 起）"),
        sa.Column("text", sa.Text(), nullable=False, comment="原始文本"),
        sa.Column("text_clean", sa.Text(), nullable=False, comment="清洗后用于向量的文本"),
        sa.Column("char_len", sa.Integer(), nullable=False, comment="字符数"),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("0"), nullable=False, comment="是否被截断"),
        sa.Column("content_hash", sa.String(length=64), nullable=False, comment="切片内容哈希"),
        sa.Column("embedding", sa.LargeBinary(), nullable=True, comment="向量（序列化后的 float32 数组）"),
        sa.Column("dim", sa.Integer(), nullable=True, comment="向量维度（用于校验是否与当前模型一致）"),
        sa.Column("model", sa.String(length=128), nullable=True, comment="生成该向量的模型名"),
        sa.Column("embedded_at", sa.DateTime(), nullable=True, comment="向量化时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        # 文档被删时连带删掉它的切片
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], name=op.f("fk_chunks_doc"), ondelete="CASCADE"),
        # 同一文档里不能出现两个相同序号的切片
        sa.UniqueConstraint("doc_id", "chunk_index", name=op.f("uq_chunk_doc_index")),
    )

    # 索引元信息：记录当前使用的向量模型与维度
    # 注：主键同样按真实库写成 `VARCHAR(64) PRIMARY KEY`（NOT NULL），
    # 而非依赖 SQLAlchemy 推断出来的可空列——推断值会让 autogenerate 反复提议改它。
    op.create_table(
        "index_meta",
        sa.Column("key", sa.String(length=64), nullable=False, comment="元信息键，如 embedding_model"),
        sa.Column("value", sa.Text(), nullable=False, comment="元信息值"),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_index_meta")),
    )

    # ---------------- 索引 ----------------
    # 这些索引在实体类里用 Index(...) 声明（见 entity/models.py 与 entity/chat_record.py）。
    # 必须写进基线，否则"由迁移建出来的新库"会缺索引，而"老库"有——
    # 于是同样的代码在新老库上性能表现不一致，这类问题很难查。
    op.create_index("idx_chat_message_session", "chat_message", ["session_id"], unique=False)
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"], unique=False)
    op.create_index("ix_audit_logs_tool", "audit_logs", ["tool"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("idx_chunks_doc", "chunks", ["doc_id"], unique=False)
    op.create_index("idx_chunks_hash", "chunks", ["content_hash"], unique=False)
    op.create_index("idx_chunks_embedded", "chunks", ["embedded_at"], unique=False)
    op.create_index("idx_chunks_model", "chunks", ["model"], unique=False)


def downgrade() -> None:
    """回退：先删索引、再按建表的逆序删表。

    注意：不会碰 LangGraph 的 checkpoints / writes —— 那是它自己管的数据，
    删掉等于毁掉用户的对话历史，因此这里有意不包含。
    """
    # 索引会随表一起消失，但显式删一遍更清晰，也便于将来调整顺序
    op.drop_index("idx_chunks_model", table_name="chunks")
    op.drop_index("idx_chunks_embedded", table_name="chunks")
    op.drop_index("idx_chunks_hash", table_name="chunks")
    op.drop_index("idx_chunks_doc", table_name="chunks")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tool", table_name="audit_logs")
    op.drop_index("ix_audit_logs_session_id", table_name="audit_logs")
    op.drop_index("idx_chat_message_session", table_name="chat_message")

    op.drop_table("index_meta")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("task_info")
    op.drop_table("audit_logs")
    op.drop_table("chat_message")
    op.drop_table("chat_session")
    op.drop_table("app_settings")