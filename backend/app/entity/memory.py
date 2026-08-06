# app/entity/memory.py
"""工作空间记忆表（MEM）：把「跨会话值得记住的信息」按工作区隔离地存下来。

和另外两张"像记忆"的表分工：
    chat_message   原样保存每一句对话 —— 是**流水**，检索靠关键词，越用越长；
    chunks         用户手动导入的文档切片 —— 是**资料**，属于 RAG；
    memories       从对话里提炼出来的一句话陈述 —— 是**结论**，条数少、可检索、可删除。

为什么向量存在本表而不是另建 FAISS 索引：
    `FaissStore` 是围绕 chunks 写的（对账逻辑硬编码在 chunks 表上），复用它要么改造成本高、
    要么复制一份索引管理代码。而记忆的量级完全不同——单工作区通常是几十到几百条，
    直接在本表按 workspace 取出来做一次 numpy 余弦相似度就够了（毫秒级），
    还省掉了"索引与真相源不一致要重建"的整类问题。
    约定与 RAG 一致：**SQLite 是唯一真相源**，向量只是可重算的派生字段（换向量化方式时清空重建即可）。
"""

# 让类型注解延迟求值（PEP 563），便于用 `str | None` 这种新语法
from __future__ import annotations

# 标准库：时间戳
from datetime import datetime

# numpy：向量与 BLOB 互转
import numpy as np
# SQLAlchemy：列类型、索引
from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text, func
# ORM 映射构件
from sqlalchemy.orm import Mapped, mapped_column

# 项目内：业务表共用的声明式基类（与 chat_* / approvals / trace_events 同一个 Base）
from app.db.db_config import Base
# 项目内：向量 dtype 常量（float32 小端，与 chunks 表保持一致，便于共用工具函数）
from app.entity.models import VEC_DTYPE

# 记忆分类的合法取值。改这里要同步改 memory_service 的抽取 prompt 与前端标签。
MEMORY_CATEGORIES: tuple[str, ...] = ("preference", "decision", "fact", "todo")
# 记忆来源：auto=每轮自动抽取 / manual=用户在设置页手填
MEMORY_SOURCES: tuple[str, ...] = ("auto", "manual")


class Memory(Base):
    """一条工作区记忆。"""

    __tablename__ = "memories"

    # 主键（自增）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 所属工作区 id（ARCH-3）。空串表示"还没有工作区"，此时记忆不参与注入
    workspace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 来源会话 id（溯源用：用户能在记忆列表里看到"这条是哪次聊出来的"）
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 记忆正文：一句话陈述事实，不带"用户说/助手说"前缀
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 分类：preference / decision / fact / todo
    category: Mapped[str] = mapped_column(String(16), default="fact", nullable=False)
    # 重要度 1~5：检索排序时作为权重，也用于过滤噪声
    importance: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    # 来源：auto / manual
    source: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    # 正文的 SHA-256：完全相同的内容直接跳过，不必再算相似度
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 向量（float32 小端 BLOB，长度 = dim * 4）；为空表示尚未向量化（此刻仍可列出，只是检索不到）
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # 向量维度：过滤"换过向量化方式"的旧向量（维度不符就不参与相似度计算）
    dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 创建时间（UTC）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    # 最近一次修改时间（用户手改正文时不刷新 created_at）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=datetime.utcnow
    )
    # 最近一次被检索命中的时间（MEM 增强：过期淘汰时"用过的不轻易删"）。从未命中为 NULL
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 被检索命中的累计次数（MEM 增强：与 last_used_at 一起构成"有用程度"的证据）
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 被合并进来的次数（MEM 增强：近似重复的内容不再丢弃，而是合并到这一条上）
    merged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 按工作区取记忆是最高频查询；带上 id 让"取最近 N 条"不必额外排序
    __table_args__ = (
        Index("idx_memories_workspace", "workspace_id", "id"),
        Index("ix_memories_content_hash", "content_hash"),
    )

    def set_embedding(self, vec: np.ndarray | list[float]) -> None:
        """写入向量：统一成 float32 一维数组后转 BLOB，同时更新 dim。

        :param vec: 任意形式的向量（list 或 ndarray），内部会被 ravel() 拉平
        """
        arr = np.asarray(vec, dtype=VEC_DTYPE).ravel()
        self.embedding = arr.tobytes()
        self.dim = int(arr.shape[0])

    def to_np(self) -> np.ndarray | None:
        """把向量 BLOB 还原成 numpy 数组；未向量化时返回 None。"""
        if self.embedding is None:
            return None
        return np.frombuffer(self.embedding, dtype=VEC_DTYPE)

    def __repr__(self) -> str:
        """调试用的一行表示：主键、工作区、分类、重要度与正文前 20 字。"""
        preview = (self.content or "")[:20]
        return (
            f"Memory(id={self.id}, workspace={self.workspace_id!r}, "
            f"category={self.category}, importance={self.importance}, content={preview!r})"
        )
