# app/entity/approval.py
"""
工作区级授权记录（UX-7 权限三档里的 `workspace` 模式）。

为什么需要一张表：
    `permission.mode=workspace` 的语义是「同一工作区里，某类操作第一次批准后就记住」。
    这个「记住」必须落库 —— 否则重启一次、或者换个页面再回来，用户又得重新点一遍确认，
    等于这个模式没生效。存内存也不行：确认发生在工具层（可能是线程池），
    生命周期跟会话绑定，后端重启就没了。

粒度为什么是 `(workspace_id, tool)` 而不是 `(workspace_id, kind)`：
    批准 `write_file` 不应该顺带放行 `delete_index`。按工具记，误放行的面最小；
    代价是用户可能要为多个写工具各点一次，这个取舍是有意的（安全优先）。
    更细的 `(workspace_id, tool, 路径前缀)` 留作后续增强，首版不做。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 时间列类型：created_at 用 DateTime
from datetime import datetime

# SQLAlchemy 构件：列类型、索引与唯一约束、SQL 函数 CURRENT_TIMESTAMP
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
# ORM 映射构件：Mapped 标注列类型、mapped_column 声明列
from sqlalchemy.orm import Mapped, mapped_column

# 项目内：业务表共用的声明式基类（与 app_settings / chat_* 同一个 Base，迁移里一起比对）
from app.db.db_config import Base


class Approval(Base):
    """一条「某工作区已授权某工具」的记录。"""

    # 物理表名：工作区级授权
    __tablename__ = "approvals"
    # 表级约束：同一工作区 + 同一工具只能有一条（upsert 靠它去重）
    __table_args__ = (
        UniqueConstraint("workspace_id", "tool", name="uq_approval_workspace_tool"),
        Index("idx_approvals_workspace", "workspace_id"),
    )

    # 自增主键，仅用于行定位
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 工作区 id（ARCH-3 的 workspace.id）；空串表示"还没有工作区"，此时不会写授权
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 被授权的工具名，如 write_file；匹配只看这个字段
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    # 操作类型（read/write/exec/net）：冗余存，仅用于展示与排查，不参与匹配
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # 首次授权时的目标描述（如文件路径、命令）：只做审计展示，**不参与匹配**
    target: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 授权时间（UTC，数据库默认值）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    def __repr__(self) -> str:
        """调试用的一行表示：工作区 + 工具。"""
        return f"<Approval ws={self.workspace_id} tool={self.tool}>"
