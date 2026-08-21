"""FAISS 向量索引（LangChain 封装）：SQLite 是唯一真相源，FAISS 只是可随时重建的检索加速层。

- 向量 id = chunks.id（字符串形式），元数据里带 doc_id / source，用于范围过滤
- 内积 + L2 归一化 = 余弦相似度，score 越大越相似
- 持久化到 app.db 同目录的 faiss_index/；启动时与 SQLite 对账，不一致直接从 BLOB 重建（不重新向量化）
"""
# 让类型注解延迟求值（PEP 563），便于用 `FAISS | None` 这种新语法
from __future__ import annotations

# logging：按 logger 名（rag.faiss）输出加载/重建/异常日志
import logging
# threading：RLock 串行化读写索引，Lock 保护"按维度缓存索引"的字典
import threading
# 类型标注：Callable 描述元数据过滤函数签名，Sequence 描述只读序列
from collections.abc import Callable, Sequence
# dataclass：描述"待写入 FAISS 的一条向量"这类搬运结构
from dataclasses import dataclass
# pathlib.Path：表示索引目录，做存在性判断与创建
from pathlib import Path

# faiss：底层向量索引实现（IndexFlatIP = 内积平面索引，暴力精确检索）
import faiss
# numpy：从 BLOB 还原向量、拼查询数组
import numpy as np
# LangChain 的内存文档仓库：FAISS 里每条向量对应一条 Document
from langchain_community.docstore.in_memory import InMemoryDocstore
# LangChain 的 FAISS 向量库封装：负责 add/delete/similarity_search 与本地持久化
from langchain_community.vectorstores import FAISS
# 距离策略枚举：MAX_INNER_PRODUCT 配合 normalize_L2 实现余弦相似度
from langchain_community.vectorstores.utils import DistanceStrategy
# LangChain 的向量化接口：本模块只依赖这个抽象，不关心具体用哪个模型
from langchain_core.embeddings import Embeddings
# SQLAlchemy 查询构造：从 chunks 表取 id / BLOB 与索引对账
from sqlalchemy import select

# 项目内：数据库引擎（用来定位同目录的 faiss_index/）与数据库会话工厂
from app.db.db_config import engine, get_session
# 项目内：向量 dtype 常量；Chunk 提供向量 BLOB，Document 提供 source
from app.entity.models import VEC_DTYPE, Chunk, Document

# 本模块专用 logger：日志里出现 "rag.faiss" 就来自这里
log = logging.getLogger("rag.faiss")

# 索引持久化目录：与 SQLite 数据库文件同级；engine.url.database 为空（内存库）时退回当前目录
INDEX_DIR = Path(engine.url.database or ".").resolve().parent / "faiss_index"


@dataclass
class VectorItem:
    """一条向量及其元数据，是"SQLite → FAISS"的搬运单元。"""

    # chunks.id，同时也是 FAISS 里的向量 id（写作字符串）
    chunk_id: int
    # 所属文档 id，写入 FAISS 元数据，用于按文档过滤检索
    doc_id: int
    # 所属文档来源（路径 / URL），写入元数据，用于按来源过滤检索
    source: str
    # 切片在文档内的顺序号（从 0 开始）
    chunk_index: int
    # 切片原文，作为 FAISS docstore 中 Document 的内容
    text: str
    # 向量本身（float32 一维数组，长度必须等于索引维度 dim）
    vector: np.ndarray


class FaissStore:
    """进程内 FAISS 索引的读写门面：懒加载 + 与 SQLite 对账重建 + 增删查。"""

    def __init__(self, embeddings: Embeddings, dim: int, folder: Path = INDEX_DIR) -> None:
        """记录向量化器、维度与持久化目录；索引本身延迟到首次使用时才加载。

        :param embeddings: LangChain Embeddings，FAISS 内部用它把查询文本转向量
        :param dim: 向量维度，必须与写入的向量长度一致
        :param folder: 索引持久化目录，默认 INDEX_DIR
        """
        # 向量化器（FAISS 需要它把查询文本转成向量）
        self.embeddings = embeddings
        # 向量维度
        self.dim = dim
        # 索引文件所在目录
        self.folder = folder
        # 已加载的内存索引；None 表示尚未加载（首次访问时由 _ensure_loaded 处理）
        self._vs: FAISS | None = None
        self._lock = threading.RLock()   # FastAPI 同步接口跑在线程池里，读写都要串行

    # ------------------------------------------------------------------ #
    # 加载 / 重建
    # ------------------------------------------------------------------ #
    def _empty(self) -> FAISS:
        """建一个空的 FAISS 向量库：内积平面索引 + L2 归一化（等价余弦相似度）+ 对应距离策略。"""
        return FAISS(
            embedding_function=self.embeddings,
            index=faiss.IndexFlatIP(self.dim),
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
            normalize_L2=True,
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )

    def _ensure_loaded(self) -> FAISS:
        """返回一个可用索引：内存里已有就复用；否则加载本地文件，并与 SQLite 对账。

        对账规则：索引维度不符、或索引里的 id 集合与库里"有向量"的 chunk id 不一致，
        就直接从 BLOB 重建（只搬运字节，不重新调 embedding 模型）。
        """
        if self._vs is not None:
            return self._vs
        db_ids = self._db_chunk_ids()
        vs: FAISS | None = None
        if (self.folder / "index.faiss").is_file():
            try:
                vs = FAISS.load_local(
                    str(self.folder), self.embeddings,
                    allow_dangerous_deserialization=True,   # 本地自己写的 pkl
                    normalize_L2=True,
                    distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
                )
            except Exception:
                log.exception("加载 FAISS 索引失败，改为从 SQLite 重建")
        if vs is None or vs.index.d != self.dim or self._ids_of(vs) != db_ids:
            vs = self._rebuild()
        self._vs = vs
        return vs

    def _rebuild(self) -> FAISS:
        """用 chunks.embedding 里的 BLOB 重建，不调用 embedding 模型。"""
        vs = self._empty()
        with get_session() as s:
            rows = s.execute(
                select(Chunk, Document.source)
                .join(Document, Chunk.doc_id == Document.id)
                .where(Chunk.embedding.is_not(None), Chunk.dim == self.dim)
            ).all()
            items = [
                VectorItem(c.id, c.doc_id, src, c.chunk_index, c.text,
                           np.frombuffer(c.embedding, dtype=VEC_DTYPE))
                for c, src in rows
            ]
        self._add(vs, items)
        self._save(vs)
        log.info("FAISS 索引已从 SQLite 重建：%d 条向量", len(items))
        return vs

    def rebuild(self) -> int:
        """加锁强制全量重建并落盘，返回重建后的向量条数（供管理接口手动修复索引）。"""
        with self._lock:
            self._vs = self._rebuild()
            return self._vs.index.ntotal

    def _db_chunk_ids(self) -> set[str]:
        """取 SQLite 中"已有向量且维度匹配"的 chunk id 集合（字符串形式），用于与索引对账。"""
        with get_session() as s:
            ids = s.scalars(
                select(Chunk.id).where(Chunk.embedding.is_not(None), Chunk.dim == self.dim)
            ).all()
        return {str(i) for i in ids}

    @staticmethod
    def _ids_of(vs: FAISS) -> set[str]:
        """取索引里全部向量 id 的集合（docstore 的 id 就是 chunk_id 的字符串形式）。"""
        return set(vs.index_to_docstore_id.values())

    def _save(self, vs: FAISS) -> None:
        """把索引落盘到 folder（目录不存在就先创建），下次启动可直接加载。"""
        self.folder.mkdir(parents=True, exist_ok=True)
        vs.save_local(str(self.folder))

    @staticmethod
    def _add(vs: FAISS, items: Sequence[VectorItem]) -> None:
        """把若干 VectorItem 批量塞进索引：文本+向量、元数据（chunk_id/doc_id/source/chunk_index）、id。

        空序列直接返回，不做任何事。
        """
        if not items:
            return
        vs.add_embeddings(
            text_embeddings=[(it.text, it.vector) for it in items],
            metadatas=[
                {"chunk_id": it.chunk_id, "doc_id": it.doc_id,
                 "source": it.source, "chunk_index": it.chunk_index}
                for it in items
            ],
            ids=[str(it.chunk_id) for it in items],
        )

    # ------------------------------------------------------------------ #
    # 增删：在 SQLite 提交成功之后调用
    # ------------------------------------------------------------------ #
    def replace(self, remove_ids: Sequence[int], add_items: Sequence[VectorItem]) -> None:
        """索引的增量同步入口：先删旧 id，再补新向量，最后落盘。

        :param remove_ids: 需要从索引移除的 chunk id（只删索引里确实存在的）
        :param add_items: 需要写入索引的向量（已在索引里的 id 会跳过，避免重复）
        """
        if not remove_ids and not add_items:
            return
        with self._lock:
            vs = self._ensure_loaded()
            present = self._ids_of(vs)
            stale = [str(i) for i in remove_ids if str(i) in present]
            if stale:
                vs.delete(stale)
            # 首次加载时若刚从 SQLite 重建，新切片已在索引里；chunk id 自增不复用，跳过即可
            present.difference_update(stale)
            self._add(vs, [it for it in add_items if str(it.chunk_id) not in present])
            self._save(vs)

    def remove(self, chunk_ids: Sequence[int]) -> None:
        """批量删除向量：不新增任何向量，等价于 replace(chunk_ids, [])。"""
        self.replace(chunk_ids, [])

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #
    def search(
        self,
        query_vec: Sequence[float],
        *,
        top_k: int,
        score_threshold: float | None = None,
        doc_ids: Sequence[int] | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[tuple[int, float]]:
        """返回 [(chunk_id, 余弦相似度)]，按相似度降序。

        :param query_vec: 查询向量（应当已归一化；重复归一化无害）
        :param top_k: 最多返回多少条（内部会与索引总量取小）
        :param score_threshold: 相似度下限，低于它的命中被丢弃；None 表示不过滤
        :param doc_ids: 只在这些文档 id 范围内检索；None 表示不限
        :param sources: 只在这些来源范围内检索；None 表示不限
        :return: (chunk_id, score) 列表，score 越大越相似
        """
        with self._lock:
            vs = self._ensure_loaded()
            total = vs.index.ntotal
            if total == 0:
                return []

            filt: Callable[[dict], bool] | None = None
            if doc_ids or sources:
                id_set = set(doc_ids or [])
                src_set = set(sources or [])
                filt = lambda md: (  # noqa: E731
                    (not id_set or md.get("doc_id") in id_set)
                    and (not src_set or md.get("source") in src_set)
                )

            kwargs = {} if score_threshold is None else {"score_threshold": score_threshold}
            hits = vs.similarity_search_with_score_by_vector(
                list(query_vec),
                k=min(top_k, total),
                filter=filt,
                fetch_k=total,        # 平面索引：带过滤时全量取回再筛，保证范围内不漏
                **kwargs,
            )
        return [(int(d.metadata["chunk_id"]), float(score)) for d, score in hits]


# 按维度缓存的索引实例（key = 向量维度），保证同一维度只有一个 FaissStore
_stores: dict[int, FaissStore] = {}
# 保护 _stores 的创建与读取
_stores_lock = threading.Lock()


def get_faiss_store(embeddings: Embeddings, dim: int) -> FaissStore:
    """进程内共享同一个索引：多个 RagStoreService 实例（rag / chat 控制器）必须看到同一份数据。"""
    with _stores_lock:
        store = _stores.get(dim)
        if store is None:
            store = _stores[dim] = FaissStore(embeddings, dim)
        return store
