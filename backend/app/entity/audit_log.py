# app/entity/audit_log.py
"""
工具调用审计表：记录每一次"有副作用的工具调用"（写文件、执行命令、删除、导入知识库……）。

为什么它比对话记录更可靠：
    对话记录是"模型说自己做了什么"，审计记录是"框架确认它做了什么"——
    两者不总是一致（模型可能漏说或多说）。排查问题时以本表为准。

只记有副作用的调用：只读工具（list_dir / read_file / glob / rag_search）量极大且无风险，
记下来只会让表迅速膨胀、把真正重要的记录淹没。哪一类算"有副作用"由 policy.Kind 决定。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：记录创建时间
from datetime import datetime

# SQLAlchemy：列类型与 ORM 基类
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

# 项目内：ORM 基类（与 chat_record 共用同一套 Base）
from app.entity.models import Base


class AuditLog(Base):
    """一条工具调用审计记录。"""

    # 表名：所有审计记录存这里
    __tablename__ = "audit_logs"

    # 主键（自增）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 所属会话 id（对应 chat_controller 的 session_id），用于把一次对话里的操作串起来
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    # 工具名，如 file_ops / run_command / write_file
    tool: Mapped[str] = mapped_column(String(64), index=True)
    # 操作类型：read / write / exec / net（取自 policy.Kind）
    kind: Mapped[str] = mapped_column(String(16))
    # 目标的人类可读描述（文件路径、命令行、URL）
    target: Mapped[str] = mapped_column(Text)
    # 面向用户的动作说明（进确认弹窗的那段话，也是审计里最有用的一列）
    detail: Mapped[str] = mapped_column(Text, default="")
    # 裁决等级：allow / ask / deny
    level: Mapped[str] = mapped_column(String(8))
    # 用户的选择：approved=同意 / rejected=拒绝 / none=无需确认
    decision: Mapped[str] = mapped_column(String(12), default="none")
    # 执行结果：ok / fail / skipped（skipped=被拒绝或裁决为 deny，没真正执行）
    outcome: Mapped[str] = mapped_column(String(12), default="skipped")
    # 工具返回文本的摘要（截断保存，避免单条记录过大）
    output_digest: Mapped[str] = mapped_column(Text, default="")
    # 记录创建时间（本地时间，仅用于展示与排序）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)