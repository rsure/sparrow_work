"""SQLAlchemy 2.0 + dataclass 实体：documents / chunks / index_meta。"""
# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 计算切片正文的 SHA-256，落库为 chunks.content_hash（判断内容是否变化）
import hashlib
# dataclass 自动生成 __init__/__repr__；field 本文件当前未使用（保留导入不影响运行）
from dataclasses import dataclass, field
# 时间列类型：created_at / updated_at / embedded_at 都用它
from datetime import datetime
# Optional[...] 标注"可为空"的列；配合上面的 __future__ 也可直接写 str | None
from typing import Optional

# numpy：与 embedding BLOB 互转（np.frombuffer 还原、ndarray.tobytes 存储）
import numpy as np
# SQLAlchemy 构件：列类型（Boolean/DateTime/Integer/LargeBinary/String/Text）、
# 外键 ForeignKey、索引与唯一约束 Index/UniqueConstraint、SQL 函数 func（CURRENT_TIMESTAMP）
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary,
    String, Text, UniqueConstraint, func,
)
# ORM：DeclarativeBase 声明式基类、Mapped 标注列类型、mapped_column 声明列、relationship 声明关联
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# float32 小端，跨平台一致
VEC_DTYPE = np.dtype("<f4")


class Base(DeclarativeBase):
    """所有 ORM 实体的公共基类：接入 SQLAlchemy 2.0 声明式映射（表名由子类的 __tablename__ 决定）。"""

    pass


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
@dataclass
class Document(Base):
    """一篇入库文档（一行 = 一个 source）；与 chunks 是一对多，删除文档时级联删除其切片。"""

    # 物理表名：存放文档级元数据（来源、标题、内容 hash）
    __tablename__ = "documents"

    # 文档主键，自增；chunks.doc_id 外键指向它
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 文档唯一来源标识（最长 1024 字符）：文件绝对路径 / URL / 业务主键；同 source 再次入库视为"更新"
    source: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    # 文档标题（最长 512 字符，可为空）；仅用于展示
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # 整篇文档内容的 SHA-256（64 位十六进制）：与上次相同即可整篇跳过，不必重新解析与切分
    doc_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 入库时间，由数据库默认值 CURRENT_TIMESTAMP 填写
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    # 最近更新时间：插入时同 created_at，之后每次 UPDATE 由 onupdate 自动刷新
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # 一对多关联：Document.chunks 取到该文档的全部切片并按 chunk_index 升序；
    # cascade="all, delete-orphan" 表示删除文档时自动删掉它的切片
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )

    def __repr__(self) -> str:
        """调试/日志用的一行表示：只带主键与来源，避免把全文打出来。"""
        return f"<Document id={self.id} source={self.source!r}>"


# --------------------------------------------------------------------------- #
# chunks
# --------------------------------------------------------------------------- #
@dataclass
class Chunk(Base):
    """一个文本切片（一行 = 文档里的一段）：原文 + 清洗文本 + 向量 BLOB + 溯源信息。"""

    # 物理表名：存放切片本体与向量
    __tablename__ = "chunks"
    # 表级约束与索引：同文档内 chunk_index 唯一；按 doc_id / content_hash / embedded_at / model 建索引加速查询
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_chunk_doc_index"),
        Index("idx_chunks_doc", "doc_id"),
        Index("idx_chunks_hash", "content_hash"),
        Index("idx_chunks_embedded", "embedded_at"),
        Index("idx_chunks_model", "model"),
    )

    # 切片主键，自增；同时被当作 FAISS 里的向量 id（字符串形式）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 所属文档 id，外键指向 documents.id；文档被删时数据库层 CASCADE 一并删除切片
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # 切片在文档内的顺序号（从 0 开始），同一文档内唯一
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)         # 原文切片
    text_clean: Mapped[str] = mapped_column(Text, nullable=False)   # _clean() 之后
    # 清洗后文本的字符数，用于统计与排查超长切片
    char_len: Mapped[int] = mapped_column(Integer, nullable=False)
    # 是否因超过 char_limit 被截断：True 表示向量只覆盖了切片的前半段内容
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 清洗后文本的 SHA-256：增量索引的 key，内容没变就直接复用旧向量
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # ★ 向量以 BLOB 形式存，float32 小端，长度 = dim * 4
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    # 向量维度（= 字节数 / 4）：用于过滤换模型前写入、维度不匹配的旧向量
    dim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 生成该向量的模型名（例 BAAI/bge-m3）：换模型必须整库重建
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 向量生成时间（UTC）；为空表示该切片尚未向量化
    embedded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 切片行入库时间，由数据库默认值填写
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # 多对一关联：反向指回所属文档（与 Document.chunks 通过 back_populates 配对）
    document: Mapped["Document"] = relationship(back_populates="chunks")

    # ---------------- 便捷方法：numpy <-> BLOB ---------------- #
    def set_embedding(self, vec: np.ndarray | list[float]) -> None:
        """存入一个向量：统一成 float32 小端一维数组 → bytes 写入 embedding，同时更新 dim 与 embedded_at。

        :param vec: 任意维度的向量（list 或 ndarray），内部会被 ravel() 拉平
        """
        arr = np.asarray(vec, dtype=VEC_DTYPE).ravel()
        self.embedding = arr.tobytes()
        self.dim = int(arr.shape[0])
        self.embedded_at = datetime.utcnow()

    def to_np(self) -> Optional[np.ndarray]:
        """把 embedding BLOB 还原成 numpy 向量（float32 一维）；尚未向量化时返回 None。"""
        if self.embedding is None:
            return None
        return np.frombuffer(self.embedding, dtype=VEC_DTYPE)

    def __repr__(self) -> str:
        """调试用的一行表示：主键、所属文档、序号、字符数与向量维度（None 表示未向量化）。"""
        n = "None" if self.embedding is None else f"{len(self.embedding)//4}d"
        return (
            f"<Chunk id={self.id} doc={self.doc_id} idx={self.chunk_index} "
            f"len={self.char_len} vec={n}>"
        )

    # 让 dataclass 的 repr 不被 numpy 干扰；字段默认值均由 DB / 显式赋值提供
    @staticmethod
    def make_hash(text_clean: str) -> str:
        """计算清洗后文本的 SHA-256，作为 content_hash；须与入库时的算法一致才能命中向量复用。

        :param text_clean: 清洗（去空白 + 截断）之后的文本
        :return: 64 位十六进制摘要
        """
        return hashlib.sha256(text_clean.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# index_meta：记录当前索引用哪个模型 / 维度
# --------------------------------------------------------------------------- #
@dataclass
class IndexMeta(Base):
    """键值表：记录当前索引的向量化模型名与维度；不一致时报错，防止新旧不兼容向量混用。"""

    # 物理表名：索引元信息（当前是 model / dim 两项）
    __tablename__ = "index_meta"

    # 配置项名：目前只有 "model"（模型名）与 "dim"（向量维度）
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 配置项取值（统一按文本存，dim 的数字也先转成字符串再写入）
    value: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        """调试用的一行表示：键=值。"""
        return f"<IndexMeta {self.key}={self.value!r}>"
