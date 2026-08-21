"""RAG 存储服务：LangChain 解析/切分 + FAISS 检索 + SQLite 持久化。

- 解析：LangChain DocumentLoader（pdf / docx / 文本）
- 切分：RecursiveCharacterTextSplitter（中文标点感知）
- 存储：SQLite documents / chunks（原文 + 向量 BLOB，唯一真相源；幂等 + 增量）
- 检索：LangChain FAISS 向量库（见 faiss_store.py，可随时从 SQLite 重建）

整体数据流：
    文件/文本 → 文档级 hash 判断是否跳过 → 解析为纯文本 → 切分为 chunks
    → 切片级 hash 判断能否复用旧向量 → 只对新增/变化切片向量化
    → 写 SQLite（提交）→ 同步 FAISS（删旧 id、加新 id）
"""
# 让类型注解延迟求值（PEP 563），便于用 `str | None`、`list[str]` 这种新语法
from __future__ import annotations

# hashlib：算文档级 / 切片级 SHA-256（增量判断依据），也是本地哈希向量化用的摘要算法
import hashlib
# logging：按 logger 名（rag.store）输出入库 / 跳过日志
import logging
# os：os.PathLike 用于路径类型标注，os.path.getsize 读源文件字节数
import os
# dataclass：描述"入库结果 IndexResult"与"检索命中 SearchHit"两个返回结构
from dataclasses import dataclass
# datetime：记录向量生成时间 embedded_at（UTC）
from datetime import datetime
# pathlib.Path：路径对象，用于取文件名、判扩展名、算相对路径
from pathlib import Path
# Sequence：只读序列的类型标注（切片列表、id 列表）
from typing import Sequence

# numpy：本地哈希向量化（分桶计数 + 归一化）的计算载体
import numpy as np
# 项目内：文档解析注册表（EXT-4）——pdf/docx/文本的解析都收口到这里，
# 新增格式只改注册表，本文件不再维护 if/elif 后缀链
from app.services.document_parser import is_degraded, parse_document
# LangChain 向量化接口：LocalHashEmbeddings 继承它才能被 FAISS 向量库使用
from langchain_core.embeddings import Embeddings
# LangChain 递归切分器：按分隔符优先级把长文切成不超过 chunk_size 的块
from langchain_text_splitters import RecursiveCharacterTextSplitter
# SQLAlchemy：delete 批量删切片、func.count 统计条数、select 构造查询
from sqlalchemy import delete, func, select
# Session：内部方法的数据库会话类型标注
from sqlalchemy.orm import Session

# 项目内：数据库会话工厂（with 块正常退出时自动提交）
from app.db.db_config import get_session
# 项目内实体：向量 dtype 常量、切片、文档、索引元信息
from app.entity.models import VEC_DTYPE, Chunk, Document, IndexMeta
# 项目内：FAISS 层搬运结构 VectorItem 与"按维度共享索引"的获取函数
from app.services.faiss_store import VectorItem, get_faiss_store

# 本模块专用 logger：日志里出现 "rag.store" 就来自这里（入库/跳过的 INFO 日志都走它）
log = logging.getLogger("rag.store")

# 向量维度（哈希桶个数）。与 MODEL_NAME 一起写入 index_meta，变更后必须重建整个索引
VECTOR_DIM = 512
# 向量化"模型"标识，写入 chunks.model / index_meta.model，用于区分不同向量化方式产生的向量
MODEL_NAME = "local-hash-v1"
# 单个切片参与向量化的最大字符数，超出部分截断
CHAR_LIMIT = 20000


def _clean(text: str, limit: int = CHAR_LIMIT) -> str:
    """向量化前必须清洗：空串换成空格，超长截断（避免哈希一个巨大字符串）。

    :param text: 原始文本
    :param limit: 截断上限（字符数）
    :return: 去除首尾空白、截断后的文本；空文本返回单个空格，保证下游总有输入
    """
    text = text.strip()
    return text[:limit] if text else " "


def _char_ngrams(text: str, n: int = 2) -> list[str]:
    """把文本切成字符级 n-gram（默认 2-gram，适合中文这类无空格分词的语言）。

    例："你好吗" → ["你好", "好吗"]

    :param text: 输入文本（内部统一转小写，使英文大小写不敏感）
    :param n: gram 长度
    :return: n-gram 列表；文本长度不足 n 时整体作为一个 gram，空文本返回空列表
    """
    text = text.lower()
    if len(text) < n:
        return [text] if text else []
    return [text[i : i + n] for i in range(len(text) - n + 1)]


def _hash_index(token: str, dim: int) -> int:
    """把 token 稳定地映射到 [0, dim) 的某个桶（"哈希技巧" feature hashing）。

    用 md5 而不是内置 hash()：内置 hash 对字符串每次进程启动都会加盐随机化，
    导致同一文本在不同进程得到不同向量，持久化的向量就失效了。
    取前 4 字节转整数再取模即可，不同 token 落到同一桶（哈希冲突）是可接受的近似。
    """
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dim


def vectorize(text: str, dim: int = VECTOR_DIM) -> np.ndarray:
    """本地哈希向量化：字符 2-gram 计数到固定维度的哈希桶，再做 L2 归一化。

    不依赖任何外部模型/网络，纯 CPU 计算；代价是只能做"字面近似"匹配，
    没有真正 embedding 模型的语义理解能力。

    :param text: 待向量化文本（调用方应先 _clean）
    :param dim: 向量维度
    :return: shape=(dim,) 的 float32 单位向量；文本无 gram 时返回全零向量
    """
    vec = np.zeros(dim, dtype=np.float32)
    for gram in _char_ngrams(text):
        vec[_hash_index(gram, dim)] += 1.0
    # 归一化后两个向量的内积就等于余弦相似度，FAISS 用内积索引即可做余弦检索
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def vectorize_batch(texts: Sequence[str], dim: int = VECTOR_DIM) -> np.ndarray:
    """批量向量化。

    :param texts: 文本序列
    :param dim: 向量维度
    :return: shape=(len(texts), dim) 的矩阵；空输入返回 (0, dim) 的空矩阵而不是报错
    """
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
    return np.stack([vectorize(t, dim) for t in texts])


class LocalHashEmbeddings(Embeddings):
    """把本地哈希向量化包装成 LangChain Embeddings，供 FAISS 向量库使用。

    换成真正的 embedding 模型时，替换这里并修改 MODEL_NAME / VECTOR_DIM（需重建索引）。
    """

    def __init__(self, dim: int = VECTOR_DIM) -> None:
        """记下输出向量维度。

        :param dim: 向量维度，必须与 FAISS 索引维度一致（换维度需重建索引）
        """
        # 输出向量维度，必须与 FAISS 索引维度一致
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """入库时调用：批量把切片文本转成向量。"""
        return vectorize_batch([_clean(t) for t in texts], self.dim).tolist()

    def embed_query(self, text: str) -> list[float]:
        """检索时调用：把用户问题转成向量（与入库使用同一套清洗 + 向量化逻辑）。"""
        return vectorize(_clean(text), self.dim).tolist()


def _file_size(source: str) -> int:
    """源文件的字节数；文件已被删除时返回 0。"""
    try:
        return os.path.getsize(source)
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# 返回结构
# --------------------------------------------------------------------------- #
@dataclass
class IndexResult:
    """一次入库操作的结果。"""

    doc_id: int            # 文档主键 documents.id
    source: str            # 文档来源标识（默认是文件绝对路径，也可以是 URL / 业务主键）
    action: str            # "created" | "updated" | "skipped"
    total_chunks: int      # 该文档当前的切片总数
    new_chunks: int        # 真正重新向量化的数量（增量验收关键指标）


@dataclass
class SearchHit:
    """一条检索命中结果（一个切片）。"""

    chunk_id: int          # 切片主键 chunks.id（同时也是 FAISS 中的向量 id）
    doc_id: int            # 所属文档 id
    source: str            # 所属文档来源
    title: str | None      # 所属文档标题
    chunk_index: int       # 切片在文档内的顺序号（从 0 开始）
    text: str              # 切片原文（未截断）
    score: float           # 余弦相似度，越大越相似



# --------------------------------------------------------------------------- #
# 解析：LangChain DocumentLoader
# --------------------------------------------------------------------------- #
def load_file_text(path: Path, encoding: str = "utf-8") -> str:
    """把整份文件解析成纯文本（多页/多段用空行拼接）。

    实现已迁到 `services/document_parser.py` 的注册表（EXT-4）：
    本函数保留只是为了兼容既有调用方，行为完全一致。

    :param path: 文件路径
    :param encoding: 纯文本文件的首选编码（pdf / docx 不使用）
    :return: 文件全文
    """
    return parse_document(path, encoding)


# --------------------------------------------------------------------------- #
# 切分：LangChain RecursiveCharacterTextSplitter
# --------------------------------------------------------------------------- #
# 从"最像语义边界"到"最不像"，最后两项是兜底，保证一定切得动
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def default_splitter(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """递归按段落 → 行 → 中文标点 → 空格切分，带 overlap。

    递归策略：先用第一个分隔符切，某段仍超过 chunk_size 时再用下一个分隔符继续切，
    直到每段都不超过 chunk_size；最后的 "" 表示按单个字符硬切。

    :param text: 全文
    :param chunk_size: 每个切片的最大字符数
    :param overlap: 相邻切片的重叠字符数，避免一句话被切断后上下文丢失
    :return: 切片文本列表；空文本返回空列表
    """
    text = text.strip()
    if not text:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=SEPARATORS,
        keep_separator="end",      # 标点留在句尾，不跑到下一块开头
    )
    return splitter.split_text(text)


# --------------------------------------------------------------------------- #
# 服务主体
# --------------------------------------------------------------------------- #
class RagStoreService:
    """RAG 文档存储服务：负责文档入库（增量）、删除、检索和元信息查询。

    SQLite 是唯一真相源，FAISS 只是检索加速层；所有写操作都是"先提交 SQLite，再同步 FAISS"。
    """

    def __init__(
        self,
        *,
        dim: int = VECTOR_DIM,
        chunk_size: int = 500,
        overlap: int = 80,
        splitter=default_splitter,
    ) -> None:
        """构造服务实例，把可调参数记到 self 上，并建好共用的向量化器。

        :param dim: 向量维度
        :param chunk_size: 默认切片大小（字符数）
        :param overlap: 默认切片重叠（字符数）
        :param splitter: 切分函数，签名为 (text, chunk_size, overlap) -> list[str]，可替换
        """
        self.dim = dim                                       # 向量维度
        self.chunk_size = chunk_size                         # 切片大小
        self.overlap = overlap                               # 切片重叠
        self.splitter = splitter                             # 切分函数
        self.embeddings = LocalHashEmbeddings(dim)           # 向量化器（入库与检索共用）
        # FAISS 索引按 dim 进程内单例共享，多个 Service 实例看到的是同一份索引
        self.store = get_faiss_store(self.embeddings, dim)

    # ===================================================================== #
    # 1. 入库：按文件路径
    # ===================================================================== #
    def index_file(
        self,
        path: str | os.PathLike,
        *,
        source: str | None = None,
        title: str | None = None,
        chunks: Sequence[str] | None = None,
        force: bool = False,
        encoding: str = "utf-8",
    ) -> IndexResult:
        """把本地文件解析、切分、向量化后入库（幂等 + 增量）。

        - path: 本地文件路径（用于读内容 & 默认 source）
        - source: 覆盖默认 source（比如传 URL / 业务主键）；默认取绝对路径
        - title: 文档标题，None 时更新已有文档不会覆盖原标题
        - chunks: 已切好的切片；为 None 时用 self.splitter
        - force: True 时忽略 doc_hash 相同、强制重算
        - encoding: 纯文本文件编码

        注意：跳过判断只看文件内容 hash。文件未变但修改了 chunk_size / overlap 时
        也会被跳过，此时需要传 force=True 才能按新参数重新切分。
        """
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"文件不存在: {p}")

        # 文件级 hash：只要文件内容没变，就直接跳过（除非 force）
        file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        # source 是文档的唯一标识，同一 source 再次入库视为"更新"
        src = source or str(p.resolve())

        with get_session() as s:
            if not force:
                skipped = self._skip_if_unchanged(s, src, file_hash)
                if skipped is not None:
                    return skipped

        # 未命中跳过才解析：PDF/DOCX 解析较慢，没必要每次都做
        text = load_file_text(p, encoding)
        # 引擎不可用时的文本兜底读出来是乱码：入库会污染检索，必须在这里拦住。
        # 抛异常而不是"静默跳过"，是为了让调用方在汇总里看到"这个文件没进去、原因是什么"。
        if is_degraded(text):
            raise ValueError(
                f"{p.name}：没有可用的解析器（本地 Office 引擎未启动或文件格式不支持），"
                "内容读出来是乱码，已拒绝入库；请启动 Office 引擎或另存为常见格式后重试"
            )
        pieces = list(chunks) if chunks is not None else self.splitter(
            text, self.chunk_size, self.overlap
        )
        return self._index(
            source=src, chunks=pieces, doc_hash=file_hash, title=title, force=force,
        )

    def index_text(
        self,
        source: str,
        text: str,
        *,
        title: str | None = None,
        chunks: Sequence[str] | None = None,
        force: bool = False,
    ) -> IndexResult:
        """直接给字符串入库（不经过文件系统）。

        :param source: 文档唯一标识（必填，没有文件路径可推导）
        :param text: 文档全文
        :param title: 文档标题
        :param chunks: 已切好的切片；为 None 时用 self.splitter 切分 text
        :param force: True 时忽略内容 hash 相同、强制重算
        """
        # 文本内容 hash 充当文档级 hash，作用同 index_file 的文件 hash
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with get_session() as s:
            if not force:
                skipped = self._skip_if_unchanged(s, source, file_hash)
                if skipped is not None:
                    return skipped
        pieces = list(chunks) if chunks is not None else self.splitter(
            text, self.chunk_size, self.overlap
        )
        return self._index(
            source=source, chunks=pieces, doc_hash=file_hash, title=title, force=force,
        )

    @staticmethod
    def _skip_if_unchanged(s: Session, source: str, doc_hash: str) -> IndexResult | None:
        """命中已存在文档 & hash 未变 → 返回 skipped 结果。

        :return: 可跳过时返回 action="skipped" 的结果；文档不存在或内容已变化时返回 None
        """
        doc = s.scalar(select(Document).where(Document.source == source))
        if doc is None or doc.doc_hash != doc_hash:
            return None
        total = s.scalar(select(func.count(Chunk.id)).where(Chunk.doc_id == doc.id))
        log.info("skip %s: 内容未变化 (%d chunks)", source, total)
        return IndexResult(doc.id, source, "skipped", total or 0, 0)

    def _index(
        self,
        *,
        source: str,
        chunks: list[str],
        doc_hash: str,
        title: str | None,
        force: bool,
    ) -> IndexResult:
        """先写 SQLite（提交成功）再同步 FAISS；同步失败时下次启动会自动对账重建。

        顺序很关键：若先改 FAISS 再写 SQLite，SQLite 回滚后 FAISS 里会残留脏数据；
        反过来 SQLite 已提交而 FAISS 同步失败，只是索引落后，加载时与 SQLite 对账即可修复。
        """
        # 离开 with 时 get_session 自动 commit，FAISS 同步在提交之后执行
        with get_session() as s:
            result, removed, added = self._index_texts(
                s, source=source, chunks=chunks,
                doc_hash=doc_hash, title=title, force=force,
            )
        self.store.replace(removed, added)
        return result

    # --------------------------------------------------------------------- #
    # 内部：真正做增量写入
    # --------------------------------------------------------------------- #
    def _index_texts(
        self,
        s: Session,
        *,
        source: str,
        chunks: list[str],
        doc_hash: str,
        title: str | None,
        force: bool,
    ) -> tuple[IndexResult, list[int], list[VectorItem]]:
        """返回 (结果, 需从 FAISS 移除的旧 chunk id, 需写入 FAISS 的新向量)。

        增量策略：以切片内容 hash 为键，内容没变的切片直接复用旧向量 BLOB，
        只有新增/变化的切片才调用向量化；但所有切片行都会删掉重建（chunk id 会变）。
        """
        # 校验当前模型/维度与库里已有向量一致，不一致直接报错，防止混入不兼容向量
        self._ensure_meta(s, MODEL_NAME, self.dim)

        # upsert documents：按 source 查找，不存在则新建，存在则更新 hash / 标题
        doc = s.scalar(select(Document).where(Document.source == source))
        action = "created"
        if doc is None:
            doc = Document(source=source, title=title, doc_hash=doc_hash)
            s.add(doc)
            s.flush()   # 立即 INSERT 以拿到自增 doc.id，下面写 chunks 要用
        else:
            action = "updated"
            doc.doc_hash = doc_hash
            if title is not None:
                doc.title = title
            s.flush()

        # 组装每行元信息
        rows: list[dict] = []
        for i, raw in enumerate(chunks):
            clean = _clean(raw, CHAR_LIMIT)
            # 切片级 hash 基于清洗后的文本：它决定向量结果，用它判断能否复用向量
            h = hashlib.sha256(clean.encode("utf-8")).hexdigest()
            rows.append(dict(
                chunk_index=i,
                text=raw,                               # 原文，检索结果展示用
                text_clean=clean,                       # 清洗/截断后文本，向量化用
                char_len=len(clean),
                truncated=len(clean) >= CHAR_LIMIT,     # 达到上限即视为被截断
                content_hash=h,
            ))

        # 找已存在且 hash 相同的切片，可复用其向量
        old_chunks = list(s.scalars(select(Chunk).where(Chunk.doc_id == doc.id)))
        # 旧切片下面会全部删除重建，所以它们的 id 都要从 FAISS 移除
        removed_ids = [c.id for c in old_chunks]
        # content_hash → 旧切片；同一文档内重复内容的切片向量相同，保留任一即可
        existing = {c.content_hash: c for c in old_chunks}

        to_embed: list[dict] = []          # 需要重新向量化的切片
        hash2vec: dict[str, bytes] = {}    # content_hash → 向量 BLOB（复用的 + 新算的）
        for r in rows:
            old = existing.get(r["content_hash"])
            if old is not None and old.embedding is not None and not force:
                hash2vec[r["content_hash"]] = old.embedding      # 复用，不重新向量化
            else:
                to_embed.append(r)

        # 只对新增/变化的切片重新向量化 —— 增量核心
        if to_embed:
            vecs = self.embeddings.embed_documents([r["text_clean"] for r in to_embed])
            for r, v in zip(to_embed, vecs):
                # 统一转成 VEC_DTYPE（小端 float32）的一维数组再序列化为 BLOB
                arr = np.asarray(v, dtype=VEC_DTYPE).ravel()
                hash2vec[r["content_hash"]] = arr.tobytes()

        # 清掉旧行（cascade 只删 chunks，不删 document）
        s.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
        s.flush()

        # 按新的切片顺序重新插入全部 chunks
        now = datetime.utcnow()
        new_chunks: list[Chunk] = []
        for r in rows:
            blob = hash2vec.get(r["content_hash"])
            c = Chunk(
                doc_id=doc.id,
                chunk_index=r["chunk_index"],
                text=r["text"],
                text_clean=r["text_clean"],
                char_len=r["char_len"],
                truncated=r["truncated"],
                content_hash=r["content_hash"],
                embedding=blob,
                # 向量相关字段只在确实有向量时填写，保证"有 embedding ⇔ 有 dim/model"
                dim=self.dim if blob is not None else None,
                model=MODEL_NAME if blob is not None else None,
                embedded_at=now if blob is not None else None,
            )
            s.add(c)
            new_chunks.append(c)
        s.flush()   # 拿到新 chunk id，作为 FAISS 向量 id

        # 组装要写入 FAISS 的向量（向量直接从 BLOB 还原，不重新计算）
        added = [
            VectorItem(c.id, doc.id, doc.source, c.chunk_index, c.text,
                       np.frombuffer(c.embedding, dtype=VEC_DTYPE))
            for c in new_chunks if c.embedding is not None
        ]

        result = IndexResult(
            doc_id=doc.id,
            source=doc.source,
            action=action,
            total_chunks=len(rows),
            new_chunks=len(to_embed),
        )
        log.info(
            "index %s: %s, chunks=%d, new=%d",
            source, action, len(rows), len(to_embed),
        )
        return result, removed_ids, added

    # ===================================================================== #
    # 2. 删除
    # ===================================================================== #
    def delete_by_id(self, doc_id: int) -> bool:
        """按文档 id 删除文档及其切片；返回是否真的删除了。"""
        return self.delete_by_ids([doc_id]) > 0

    def delete_by_source(self, source: str) -> bool:
        """按 source 删除文档及其切片；文档不存在时返回 False。"""
        # 先查 id 再复用 delete_by_id，保证 FAISS 同步逻辑只有一处
        with get_session() as s:
            doc_id = s.scalar(select(Document.id).where(Document.source == source))
        return doc_id is not None and self.delete_by_id(doc_id)

    def delete_by_ids(self, doc_ids: Sequence[int]) -> int:
        """按 id 批量删除，返回实际删除条数（用于批量清空导入历史）。

        不存在的 id 会被忽略，不报错。
        """
        if not doc_ids:
            return 0
        with get_session() as s:
            docs = s.scalars(
                select(Document).where(Document.id.in_(list(doc_ids)))
            ).all()
            # 删除前先记下切片 id：cascade 删除后就查不到了，而 FAISS 需要按 chunk id 移除
            chunk_ids = list(s.scalars(
                select(Chunk.id).where(Chunk.doc_id.in_([d.id for d in docs]))
            ))
            for doc in docs:
                s.delete(doc)          # cascade 会带走 chunks
            deleted = len(docs)
        # SQLite 提交后再同步 FAISS（同 _index 的顺序约定）
        self.store.remove(chunk_ids)
        return deleted

    # ===================================================================== #
    # 3. 检索
    # ===================================================================== #
    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        score_threshold: float | None = None,
        doc_ids: Sequence[int] | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        """向量检索，返回按相似度降序的切片列表。

        query: 用户问题（与入库相同的 Embeddings 向量化）
        top_k: 返回条数
        score_threshold: 余弦相似度阈值，低于此值丢弃
        doc_ids / sources: 限定检索范围（两者同时给出时取交集）
        """
        if not query.strip():
            return []

        # 第一步：FAISS 粗检，只拿到 [(chunk_id, score)]，已按分数降序
        scored = self.store.search(
            self.embeddings.embed_query(query),
            top_k=top_k,
            score_threshold=score_threshold,
            doc_ids=doc_ids,
            sources=sources,
        )
        if not scored:
            return []

        # FAISS 只给 id + 分数，正文/标题以 SQLite 为准
        with get_session() as s:
            # 一次 IN 查询批量取回切片和所属文档，避免逐条查询
            rows = s.execute(
                select(Chunk, Document)
                .join(Document, Chunk.doc_id == Document.id)
                .where(Chunk.id.in_([cid for cid, _ in scored]))
            ).all()
            by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}

            # 按 scored 的顺序组装结果，保持 FAISS 给出的相似度排序
            hits: list[SearchHit] = []
            for cid, score in scored:
                pair = by_id.get(cid)
                if pair is None:       # 索引里残留的已删除切片
                    continue
                chunk, doc = pair
                hits.append(SearchHit(
                    chunk_id=chunk.id,
                    doc_id=doc.id,
                    source=doc.source,
                    title=doc.title,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    score=score,
                ))
            return hits

    def rebuild_index(self) -> int:
        """从 SQLite 全量重建 FAISS（不重新向量化），返回向量条数。"""
        return self.store.rebuild()

    # ===================================================================== #
    # 辅助
    # ===================================================================== #
    def get_document(self, doc_id: int) -> dict | None:
        """查询单个文档详情。

        :return: 文档信息字典（含切片总数 chunks、已向量化切片数 embedded）；不存在返回 None
        """
        with get_session() as s:
            doc = s.get(Document, doc_id)
            if doc is None:
                return None
            total = s.scalar(
                select(func.count(Chunk.id)).where(Chunk.doc_id == doc.id)
            )
            # embedded < chunks 说明有切片缺向量，可用于排查入库异常
            embedded = s.scalar(
                select(func.count(Chunk.id))
                .where(Chunk.doc_id == doc.id, Chunk.embedding.is_not(None))
            )
            # 在 session 关闭前转成 dict，避免返回 ORM 对象后懒加载报错
            return {
                "id": doc.id,
                "source": doc.source,
                "title": doc.title,
                "doc_hash": doc.doc_hash,
                "chunks": total or 0,
                "embedded": embedded or 0,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at,
            }

    def list_documents(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        """分页列出文档（按 id 倒序，即最新导入的在前）。

        :param limit: 每页条数
        :param offset: 偏移量
        :return: 文档信息字典列表，含文件名 name、当前文件大小 file_size、切片数 chunks
        """
        with get_session() as s:
            rows = s.scalars(
                select(Document).order_by(Document.id.desc())
                .limit(limit).offset(offset)
            ).all()
            out = []
            for d in rows:
                # 每个文档单独 count 一次（N+1 查询），分页量小时可以接受
                total = s.scalar(
                    select(func.count(Chunk.id)).where(Chunk.doc_id == d.id)
                )
                out.append({
                    "id": d.id,
                    "name": Path(d.source).name,           # 从 source 路径中取文件名
                    "source": d.source,
                    "title": d.title,
                    "file_size": _file_size(d.source),     # 实时读磁盘，源文件已删除时为 0
                    "chunks": total or 0,
                    "created_at": d.created_at,
                    "updated_at": d.updated_at,
                })
            return out

    @staticmethod
    def _ensure_meta(s: Session, model: str, dim: int) -> None:
        """校验/初始化 index_meta 中的模型名和维度。

        首次入库时写入当前 model / dim；之后每次入库都比对，不一致说明换了向量化方式，
        新旧向量不可比较（维度不同甚至无法放进同一个 FAISS 索引），因此直接抛错。

        :raises RuntimeError: 当前 model / dim 与已记录的不一致
        """
        for k, v in (("model", model), ("dim", str(dim))):
            row = s.get(IndexMeta, k)
            if row is None:
                s.add(IndexMeta(key=k, value=v))
            elif row.value != v:
                raise RuntimeError(
                    f"index_meta.{k} 冲突：已有 {row.value!r}，当前 {v!r}。"
                    "换模型/维度必须重建整个索引。"
                )
