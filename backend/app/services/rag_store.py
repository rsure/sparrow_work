"""业务侧：把 Embedder 的输出写进 SQLite，并提供检索。"""
# 让类型注解延迟求值（PEP 563），便于用 `str | None` 这种新语法
from __future__ import annotations

# hashlib：算文档级 / 切片级的 SHA-256，作为增量索引的"内容是否变化"依据
import hashlib
# datetime：本文件当前未用到（保留导入不影响运行）
from datetime import datetime
# Iterable：本文件当前未用到（保留导入不影响运行）
from typing import Iterable

# numpy：把查询向量归一化，并逐行算余弦相似度（search）
import numpy as np
# SQLAlchemy：select 构造查询
from sqlalchemy import select
# Session：函数签名里的会话类型标注
from sqlalchemy.orm import Session

# ⚠ 可疑点（本任务只加注释、未改动）：这里用的是顶层 `embedder` 而不是 `app.services.embedder`，
#   只有当 sys.path 恰好包含 services/ 目录时才能导入成功；从项目根启动通常应写
#   `from app.services.embedder import Embedder, _clean`，否则运行到本模块就 ImportError。
from embedder import Embedder, _clean          # 复用你的清洗
# 项目内实体：Chunk（切片 + 向量 BLOB）、Document（文档）、IndexMeta（模型/维度记账）
from app.entity.models import Chunk, Document, IndexMeta


def _sha(text: str) -> str:
    """算文本的 SHA-256 十六进制串，作为文档级 doc_hash 与切片级 content_hash。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------- index_meta ---------------- #
def ensure_meta(s: Session, model: str, dim: int) -> None:
    """校验/初始化 index_meta 里的模型名与维度。

    首次入库时把当前 model / dim 写进去；之后每次入库都比对，不一致说明换了向量化方式，
    新旧向量不可比较（维度不同甚至无法放进同一个索引），所以直接报错。

    :param s: 已打开的数据库会话
    :param model: 当前使用的向量化模型名
    :param dim: 当前向量维度
    :raises RuntimeError: 与库中已记录的值不一致
    """
    for k, v in (("model", model), ("dim", str(dim))):
        row = s.get(IndexMeta, k)
        if row is None:
            s.add(IndexMeta(key=k, value=v))
        elif row.value != v:
            raise RuntimeError(
                f"index_meta.{k} 已存在且不一致：{row.value!r} vs {v!r}。"
                "换模型/维度必须重建整库。"
            )


# ---------------- 增量索引 ----------------
async def index_document(
    s: Session,
    embedder: Embedder,
    source: str,
    full_text: str,
    chunks: list[str],
    title: str | None = None,
) -> Document:
    """把一篇文档写入 documents + chunks。已存在且 hash 未变的 chunk 不再调模型。

    :param s: 已打开的数据库会话（由调用方负责 commit / rollback）
    :param embedder: 向量化客户端，只有新增/变化的切片才会用到它
    :param source: 文档唯一标识（文件路径 / URL / 业务主键）
    :param full_text: 文档全文，用于算文档级 doc_hash
    :param chunks: 已切好的切片文本列表
    :param title: 文档标题，可为空
    :return: 落库后的 Document 对象（已 flush，带 id）
    """
    cfg = embedder._cfg
    ensure_meta(s, cfg.model, cfg.dim)

    doc_hash = _sha(full_text)
    doc = s.scalar(select(Document).where(Document.source == source))
    if doc is None:
        doc = Document(source=source, title=title, doc_hash=doc_hash)
        s.add(doc)
        s.flush()                                 # 拿到 doc.id
    else:
        doc.doc_hash = doc_hash
        doc.title = title
        s.flush()

    # 已有 chunk 的 hash → 便于复用
    old_hashes = set(
        s.scalars(select(Chunk.content_hash).where(Chunk.doc_id == doc.id))
    )

    # 组装每行的清洗结果
    rows: list[dict] = []
    for i, raw in enumerate(chunks):
        clean = _clean(raw, cfg.char_limit)
        h = _sha(clean)
        rows.append(dict(
            chunk_index=i,
            text=raw,
            text_clean=clean,
            char_len=len(clean),
            truncated=int(len(clean) >= cfg.char_limit) == 1,
            content_hash=h,
        ))

    # 只对"库里没有相同 hash"的切片调模型
    to_embed = [r for r in rows if r["content_hash"] not in old_hashes]
    hash2vec: dict[str, np.ndarray] = {}
    if to_embed:
        texts = [r["text_clean"] for r in to_embed]
        vecs = await embedder.embed_all(texts)
        for r, v in zip(to_embed, vecs):
            hash2vec[r["content_hash"]] = v
        # 记录一个便于验收的日志
        print(f"[index] {source}: 新增/变化 {len(to_embed)}/{len(rows)} 条 -> "
              f"calls={embedder.calls}")

    # 全删全插（cascade 已保证按 doc 级联）。量大时可改成 diff。
    s.query(Chunk).filter(Chunk.doc_id == doc.id).delete(synchronize_session=False)
    s.flush()

    for r in rows:
        c = Chunk(
            doc_id=doc.id,
            chunk_index=r["chunk_index"],
            text=r["text"],
            text_clean=r["text_clean"],
            char_len=r["char_len"],
            truncated=r["truncated"],
            content_hash=r["content_hash"],
            model=cfg.model,
        )
        v = hash2vec.get(r["content_hash"])
        if v is not None:
            c.set_embedding(v)
        s.add(c)

    s.flush()
    return doc


# ---------------- 检索 ----------------
def search(
    s: Session,
    query_vec: np.ndarray,
    top_k: int = 10,
) -> list[tuple[Chunk, float]]:
    """全表扫 + numpy 余弦相似度。数据量 < 10 万时够用；再大再上 ANN。

    :param s: 数据库会话
    :param query_vec: 查询向量（内部会做 L2 归一化，与切片向量的点积即余弦相似度）
    :param top_k: 返回条数
    :return: [(Chunk, 余弦相似度)]，按相似度降序；维度不匹配的切片会被跳过
    """
    q = np.asarray(query_vec, dtype=np.float32).ravel()
    qn = np.linalg.norm(q) or 1.0
    q = q / qn

    rows = s.scalars(
        select(Chunk).where(Chunk.embedding.is_not(None))
    ).all()

    scored: list[tuple[Chunk, float]] = []
    for c in rows:
        v = c.to_np()
        if v is None or v.shape[0] != q.shape[0]:
            continue
        vn = np.linalg.norm(v) or 1.0
        scored.append((c, float(np.dot(q, v) / vn)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
