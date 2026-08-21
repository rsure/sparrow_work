# app/services/memory_service.py
"""工作空间记忆（MEM）：抽取、去重、存储、检索、注入。

一句话概括数据流：
    一轮对话结束 ──► 裸模型抽「值得记住的一句话」──► 去重 ──► 落 memories 表（含向量）
    新对话开场  ──► 用本地向量检索本工作区记忆 ──► 拼成一段提示附给模型（只给模型看）

三条刻意的设计选择（改动前请先读）：

1. **向量存表、不建 FAISS 索引**。记忆的量级是"单工作区几十到几百条"，
   每次检索全取出来做一次 numpy 内积就是毫秒级；换来的是彻底没有"索引与真相源不一致"的问题。
   `FaissStore` 的对账逻辑硬编码在 chunks 表上，复用它反而要改一处不该改的地方。

2. **抽取失败绝不影响对话**。它在 `asyncio.create_task` 里跑，任何异常只写日志。
   记忆是锦上添花，不是对话的前置条件。

3. **注入只在"新对话的第一条消息"发生**。每轮都注入会让长对话的 token 一路膨胀，
   而且模型早就从上下文里知道了。首轮注入一次，收益最大、成本最低。

向量化走 `memory_embedding.embed_one()`：默认是本地哈希（字符 2-gram + L2 归一化，纯本地、无网络、可测试），
用户在设置里配了 OpenAI 兼容的 `/embeddings` 端点后自动换成真 embedding。
两条通道的向量**不可混用**（维度与语义空间都不同），所以每行都记 `dim`，维度不符的旧向量检索时直接跳过，
换后端后跑一次 `reindex()` 即可全部重算。

记忆的生命周期（MEM 增强）：
    写入 → 近似重复时**合并**（而不是丢弃） → 检索命中时记 `last_used_at`/`use_count`
    → 抽完一轮后按 `memory.ttl_days` 与 `memory.max_per_workspace` 淘汰一批。
    淘汰只删"低重要度 + 长期没用"的条目，重要度高的永不因过期被删（除非超过数量上限）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：时间戳（落库时显式写入）、时间差（过期淘汰的天数计算）、哈希（内容去重）、JSON（抽取结果解析）、日志、正则（剥代码围栏）
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
from typing import Any

# numpy：批量余弦相似度
import numpy as np
# SQLAlchemy：删除 / 查询 / 批量更新（记录命中使用情况）
from sqlalchemy import delete, select, update

# 项目内：数据库会话工厂
from app.db.db_config import get_session
# 项目内：记忆实体与合法取值
from app.entity.memory import MEMORY_CATEGORIES, Memory
# 项目内：向量化入口（本地哈希 / 远端 embedding 两套后端，dim 由所选后端决定）
from app.services import memory_embedding

# 本模块专用 logger
log = logging.getLogger("memory")

# 记忆正文长度上限。记忆的价值在"一句话"，太长的东西应该写进文档而不是记忆
MAX_CONTENT_CHARS = 500
# 抽取时喂给模型的对话长度上限（user / assistant 各自），避免把长回答整段塞进去
_MAX_INPUT_CHARS = 4000
# 检索的最低相似度：低于它的命中不注入（哈希向量下无关文本也可能有 0.05~0.1 的底噪）
MIN_SIMILARITY = 0.1
# 一次抽取最多接受多少条（模型偶尔会吐出十几条，全存下来就是噪声）
MAX_EXTRACT_PER_TURN = 5


# --------------------------------------------------------------------------- #
# 1. 设置读取（全部带兜底：读不到就走保守默认，绝不让调用方处理异常）
# --------------------------------------------------------------------------- #
def _setting(key: str, default: Any) -> Any:
    """读一个设置项，失败时返回默认值。

    :param key: 设置键
    :param default: 读不到时的兜底值
    :return: 设置值
    """
    try:
        # 项目内：延迟导入，避免本模块在导入期依赖设置库
        from app.services.settings_registry import get_setting

        value = get_setting(key)
        return default if value is None else value
    except Exception:
        return default


def is_enabled() -> bool:
    """记忆总开关。

    读设置失败时返回 False：宁可"记忆不生效"，也不要因为配置读取异常而让对话路径出问题。
    """
    try:
        return bool(_setting("memory.enabled", True))
    except Exception:
        return False


def extract_enabled() -> bool:
    """是否允许每轮自动抽取（写侧开关）。"""
    return is_enabled() and bool(_setting("memory.extract_enabled", True))


def inject_enabled() -> bool:
    """是否允许新对话注入记忆（读侧开关）。"""
    return is_enabled() and bool(_setting("memory.inject_enabled", True))


def top_k_setting() -> int:
    """注入 / 检索的默认条数（来自 memory.top_k）。

    单独起这个函数名而不是叫 `top_k`：`search()` 的形参也叫 top_k，
    同名会遮蔽模块函数，读代码时要很小心才看得出调的是哪个。
    """
    try:
        return max(1, min(int(_setting("memory.top_k", 5)), 20))
    except (TypeError, ValueError):
        return 5


def min_importance() -> int:
    """检索时的重要度门槛（1~5）。"""
    try:
        return max(1, min(int(_setting("memory.min_importance", 1)), 5))
    except (TypeError, ValueError):
        return 1


def dedup_threshold() -> float:
    """相似度去重阈值（超过就不重复保存）。

    默认 0.85 是**实测校准**出来的，不是拍脑袋：
        几乎重复（只差语气词/标点）      0.90 ~ 0.97  → 应当去重
        同一主题但信息不同（该保留）      0.50 ~ 0.60  → 绝不能去重
        完全无关                          0.02 ~ 0.38
    0.85 落在这条清晰的分界线上；0.92 会把 0.90 那类"只多一个『写』字"的重复漏掉。
    """
    try:
        return max(0.5, min(float(_setting("memory.dedup_threshold", 0.85)), 1.0))
    except (TypeError, ValueError):
        return 0.85


def merge_enabled() -> bool:
    """近似重复时是"合并进已有记忆"（True）还是"直接丢弃"（False）。

    默认 True：合并只多写一次 UPDATE，却不会让"更完整的那句话"被丢掉；
    关掉它则退回 M4.5 的老行为（相似度超阈值就 return None）。
    """
    return bool(_setting("memory.merge_enabled", True))


def ttl_days() -> int:
    """低价值记忆的保留天数；0 表示不做时间淘汰。

    只对 `importance <= 2` 的条目生效——重要度 3 以上的记忆是用户的结论与偏好，
    不该因为"半年没用过"就消失。
    """
    try:
        return max(0, min(int(_setting("memory.ttl_days", 180)), 3650))
    except (TypeError, ValueError):
        return 180


def max_per_workspace() -> int:
    """单工作区记忆条数上限；0 表示不限制。

    超限时按"重要度最低、最久没用、最早创建"的顺序删，直到回到上限以内。
    """
    try:
        return max(0, min(int(_setting("memory.max_per_workspace", 500)), 5000))
    except (TypeError, ValueError):
        return 500


def current_workspace_id() -> str:
    """当前 active 工作区 id；没有工作区时返回空串。

    空串的作用域是"未归属任何工作区"——这些记忆不会被注入（因为不知道该给谁看），
    但会被列出来，用户仍能手动清理。
    """
    try:
        # 项目内：工作区服务（内部已做旧数据迁移）
        from app.services.workspace_service import get_active

        profile = get_active() or {}
        return str(profile.get("id") or "")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# 2. 向量与相似度
# --------------------------------------------------------------------------- #
def _vectorize(text: str) -> np.ndarray:
    """把记忆正文转成单位向量（走当前配置的向量化后端）。

    远端 embedding 不可用或调用失败时，`memory_embedding.embed_one` 会自动降级为本地哈希，
    所以这里不需要 try/except——降级逻辑集中在一处，调用方只管用结果。

    :param text: 记忆正文
    :return: 单位向量；维度由后端决定（本地 512，远端由模型决定，如 1536）
    """
    return memory_embedding.embed_one(text)


def _now_naive() -> datetime:
    """当前 UTC 时间的"朴素"形式（去掉 tzinfo）。

    memories 表的时间列是朴素 DateTime，带时区写进 SQLite 会被悄悄丢掉，
    所以全模块统一走这个函数，避免写入与比较两侧出现 aware/naive 混用报错。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _content_hash(text: str) -> str:
    """正文的 SHA-256（完全相同的内容直接判定为重复，不必算相似度）。"""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _cosine_matrix(query: np.ndarray, rows: list[Memory]) -> np.ndarray:
    """算查询向量与若干记忆的余弦相似度（向量已归一化，内积即余弦）。

    维度不匹配（换过向量化方式）或没有向量的行记为 -1，排序时自然沉底。

    :param query: 查询向量（已归一化）
    :param rows: 候选记忆
    :return: 与 rows 等长的相似度数组
    """
    scores = np.full(len(rows), -1.0, dtype=np.float32)
    for index, row in enumerate(rows):
        vec = row.to_np()
        if vec is None or vec.shape[0] != query.shape[0]:
            continue
        scores[index] = float(np.dot(vec, query))
    return scores


def _score(similarity: float, importance: int) -> float:
    """把相似度与重要度合成排序分数。

    公式：`sim * (0.5 + importance / 5)` —— importance=5 时放大 1.5 倍、1 时 0.7 倍。
    不直接用 `sim * importance`：那会让"相似度 0.9 但重要度 1"排在"相似度 0.35 但重要度 5"后面，
    而相关性的优先级显然更高。这里的系数只做微调，不做翻盘。

    :param similarity: 余弦相似度
    :param importance: 重要度 1~5
    :return: 排序分数
    """
    return similarity * (0.5 + max(1, min(importance, 5)) / 5.0)


# --------------------------------------------------------------------------- #
# 3. 读：列表 / 检索 / 注入块
# --------------------------------------------------------------------------- #
def _to_dict(row: Memory, score: float | None = None) -> dict:
    """把实体转成接口返回的字典（不暴露向量本身：那是内部实现，且体积不小）。

    :param row: 记忆实体
    :param score: 检索分数（列表接口不传）
    :return: 字典
    """
    data = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "session_id": row.session_id,
        "content": row.content,
        "category": row.category,
        "importance": row.importance,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        # 生命周期字段（MEM 增强）：前端用它显示"用过几次/最近什么时候用过/合并过几条"
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "use_count": int(row.use_count or 0),
        "merged_count": int(row.merged_count or 0),
    }
    if score is not None:
        data["score"] = round(score, 4)
    return data


def list_memories(
    workspace_id: str | None = None,
    *,
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """列出某个工作区的记忆（按重要度、时间倒序）。

    :param workspace_id: 工作区 id；None 表示取当前 active 工作区
    :param category: 只看某一类（preference / decision / fact / todo）；None 表示全部
    :param limit: 最多返回多少条
    :return: 记忆字典列表
    """
    wid = current_workspace_id() if workspace_id is None else workspace_id
    with get_session() as s:
        stmt = select(Memory).where(Memory.workspace_id == wid)
        if category:
            stmt = stmt.where(Memory.category == category)
        stmt = stmt.order_by(
            Memory.importance.desc(), Memory.created_at.desc(), Memory.id.desc()
        ).limit(max(1, min(limit, 500)))
        rows = s.scalars(stmt).all()
        return [_to_dict(row) for row in rows]


def search(workspace_id: str, query: str, top_k: int | None = None) -> list[dict]:
    """在本工作区的记忆里做本地检索（不调 LLM、不花 token）。

    :param workspace_id: 工作区 id（空串表示"未归属"，会返回空列表）
    :param query: 查询文本
    :param top_k: 返回条数；None 取设置里的 memory.top_k
    :return: 命中的记忆（含 score），按合成分数降序
    """
    text = (query or "").strip()
    if not text or not workspace_id:
        return []
    k = top_k or top_k_setting()
    floor = min_importance()

    with get_session() as s:
        rows = s.scalars(
            select(Memory).where(
                Memory.workspace_id == workspace_id,
                Memory.importance >= floor,
            )
        ).all()
        if not rows:
            return []

        query_vec = _vectorize(text)
        sims = _cosine_matrix(query_vec, rows)
        hits: list[tuple[float, float, Memory]] = []
        for row, sim in zip(rows, sims):
            similarity = float(sim)
            if similarity < MIN_SIMILARITY:
                continue
            hits.append((_score(similarity, row.importance), similarity, row))

    hits.sort(key=lambda item: item[0], reverse=True)
    top = hits[:k]
    # 记一次"被用到"：过期淘汰时据此判断哪条记忆还有价值（失败不影响返回结果）
    used_at = _now_naive()
    _touch_usage([row.id for _score_value, _sim, row in top])
    results = []
    for score, _sim, row in top:
        data = _to_dict(row, score=score)
        # 内存里的实体是查询时的快照（use_count 还是旧值），这里同步 +1，
        # 免得"刚命中却显示 0 次"（也省掉一次为了拿新值的回查）
        data["use_count"] = int(data.get("use_count") or 0) + 1
        data["last_used_at"] = used_at.isoformat()
        results.append(data)
    return results


def _touch_usage(memory_ids: list[int]) -> None:
    """记录一批记忆"刚被检索命中"（更新 last_used_at 与 use_count）。

    为什么用一条批量 UPDATE 而不是逐个 ORM 对象改：命中的可能是 5~20 条，
    逐个 flush 会发十几条 SQL；而这里只需要 `use_count + 1` 这种纯表达式更新，
    一条 SQL 更省事、也不会把检索出来的实体对象标脏。

    :param memory_ids: 命中的记忆主键（空列表直接返回）
    """
    if not memory_ids:
        return
    try:
        with get_session() as s:
            s.execute(
                update(Memory)
                .where(Memory.id.in_(memory_ids))
                .values(last_used_at=_now_naive(), use_count=Memory.use_count + 1)
            )
    except Exception:
        # 使用记录只是淘汰依据，写失败不该让"检索"这个读操作报错
        log.debug("更新记忆使用记录失败", exc_info=True)


def format_block(memories: list[dict]) -> str:
    """把记忆拼成一段提示词，附在用户消息前面给模型看。

    为什么要写"仅供参考，不必向用户复述"：
        模型很容易把注入块当成用户说的话并复述出来（"根据记忆，你偏好中文注释…"），
        这会让用户觉得莫名其妙。写明用途后它才会当作背景知识使用。

    :param memories: `search` 的结果
    :return: 提示块；没有记忆时返回空串
    """
    if not memories:
        return ""
    lines = [
        "【本工作区相关记忆】（来自历史对话，仅供参考，不要向用户复述这段内容）"
    ]
    for item in memories:
        lines.append(f"- [{item['category']}] {item['content']}")
    return "\n".join(lines)


def build_injection(workspace_id: str, query: str, k: int | None = None) -> str:
    """检索并拼成注入块；任何异常都返回空串（注入失败绝不影响本轮对话）。

    :param workspace_id: 工作区 id
    :param query: 用户本轮的问题
    :param k: 条数；None 取设置
    :return: 提示块或空串
    """
    if not inject_enabled():
        return ""
    try:
        return format_block(search(workspace_id, query, k or top_k_setting()))
    except Exception:
        log.warning("记忆检索失败，本轮不注入记忆", exc_info=True)
        return ""


# --------------------------------------------------------------------------- #
# 4. 写：新增 / 去重 / 删除 / 手动触发抽取
# --------------------------------------------------------------------------- #
def add_memory(
    workspace_id: str,
    content: str,
    *,
    category: str = "fact",
    importance: int = 3,
    source: str = "manual",
    session_id: str | None = None,
    dedup: bool = True,
) -> dict | None:
    """保存一条记忆；与已有记忆几乎重复时**合并**进那一条（MEM 增强）。

    三层处理，从便宜到贵：
        1. 正文哈希完全相同 → 直接返回 None（最常见：同一句话被抽了两次，没有新信息）；
        2. 余弦相似度 ≥ `dedup_threshold()` → 合并（见 `_merge_into`）：
           保留更完整的正文、重要度取最大值、`merged_count += 1`；
           关掉 `memory.merge_enabled` 则退回老行为——直接返回 None；
        3. 否则新建一行（向量走当前后端：本地哈希或远端 embedding）。

    为什么"合并"比"丢弃"好：两句话相似到 0.9 往往不是完全等价，
    第二句通常多了限定条件（"…不要英文注释"多一个"写"字之外可能多一句原因）。
    丢弃会让信息永久消失，合并至少把更长的那个版本留下来。

    :param workspace_id: 工作区 id
    :param content: 记忆正文
    :param category: 分类（不在合法集合里会退回 fact）
    :param importance: 重要度 1~5
    :param source: auto / manual
    :param session_id: 来源会话 id
    :param dedup: 是否做相似度检查（手动添加时也做，避免用户重复点保存）
    :return: 记忆字典（`merged=True` 表示合并进了已有条目、`merged=False` 表示新建）；无内容时 None
    """
    text = " ".join((content or "").split()).strip()
    if not text:
        return None
    text = text[:MAX_CONTENT_CHARS]
    cat = category if category in MEMORY_CATEGORIES else "fact"
    imp = max(1, min(int(importance or 3), 5))
    digest = _content_hash(text)

    with get_session() as s:
        # 1) 完全相同的正文：一条 SQL 就够，不必向量化
        exists = s.scalars(
            select(Memory.id).where(
                Memory.workspace_id == workspace_id, Memory.content_hash == digest
            )
        ).first()
        if exists is not None:
            return None

        # 2) 近似重复：找出最像的那一条，交给合并逻辑
        if dedup:
            rows = s.scalars(select(Memory).where(Memory.workspace_id == workspace_id)).all()
            if rows:
                vec = _vectorize(text)
                sims = _cosine_matrix(vec, rows)
                best = int(np.argmax(sims))
                if float(sims[best]) >= dedup_threshold():
                    if not merge_enabled():
                        log.debug("记忆近似重复，跳过（合并已关闭）：%s", text[:40])
                        return None
                    merged = _merge_into(rows[best], text, cat, imp)
                    s.flush()
                    merged["merged"] = True
                    log.info("记忆已合并进 #%s：%s", rows[best].id, text[:40])
                    return merged

        # 时间戳显式写：SQLite 的 server_default 在 flush 后不会回填到 ORM 对象上，
        # 不写的话接口返回的 created_at 会是 null（前端列表就没法显示时间）。
        now = _now_naive()
        row = Memory(
            workspace_id=workspace_id,
            session_id=session_id,
            content=text,
            category=cat,
            importance=imp,
            source=source if source in ("auto", "manual") else "auto",
            content_hash=digest,
            created_at=now,
            updated_at=now,
        )
        row.set_embedding(_vectorize(text))
        s.add(row)
        s.flush()
        # flush 之后才能拿到自增 id；接下来的 _to_dict 还要读 created_at
        data = _to_dict(row)
        data["merged"] = False
    log.info("记忆已保存 [%s] %s", cat, text[:40])
    return data


def _merge_into(row: Memory, text: str, category: str, importance: int) -> dict:
    """把一条"几乎重复"的新内容合并进已有记忆（就地修改，返回合并后的字典）。

    合并规则（都很保守，宁可不改也不要改错）：
        - 正文：**较长的那一版胜出**（通常信息更完整）；长度相同则保留已有正文，
          因为已有那条可能已经被用户看过、引用过；
        - 分类：已有是万能的 `fact`、而新的更具体（preference/decision/todo）时采用新分类；
          反过来不动——别用 `fact` 覆盖用户已经归好的类；
        - 重要度：取两者最大值（合并不会降低一条记忆的重要性）；
        - 只累计 `merged_count` 并刷新 `updated_at`，**不动** `created_at`/`source`/`session_id`
          （它们是"这条记忆从哪来"的溯源信息，合并时不该被改写）。

    :param row: 被合并的目标记忆（已在本会话里，flush 时会一起提交）
    :param text: 新内容（已归一化、已截断）
    :param category: 新内容的分类
    :param importance: 新内容的重要度
    :return: 合并后的记忆字典
    """
    new_content = text if len(text) > len(row.content or "") else (row.content or text)
    row.content = new_content
    if (row.category or "fact") == "fact" and category != "fact":
        row.category = category
    row.importance = max(int(row.importance or 1), importance)
    row.merged_count = int(row.merged_count or 0) + 1
    row.updated_at = _now_naive()
    # 正文可能变了，哈希与向量都要跟着重算，否则"同文去重"与"相似度检索"会用到过期数据
    row.content_hash = _content_hash(new_content)
    row.set_embedding(_vectorize(new_content))
    return _to_dict(row)


def delete_memory(memory_id: int) -> bool:
    """删除一条记忆。

    :param memory_id: 记忆 id
    :return: True=确实删掉了一条；False=不存在
    """
    with get_session() as s:
        result = s.execute(delete(Memory).where(Memory.id == memory_id))
        return bool(result.rowcount)


def clear_workspace(workspace_id: str) -> int:
    """清空某个工作区的全部记忆，返回删除条数（设置页的"清空"按钮用）。"""
    with get_session() as s:
        result = s.execute(delete(Memory).where(Memory.workspace_id == workspace_id))
        return int(result.rowcount or 0)


def stats(workspace_id: str | None = None) -> dict:
    """统计某工作区的记忆条数与分类分布（设置页顶部一行摘要用）。

    :param workspace_id: 工作区 id；None 取当前 active
    :return: {"workspace_id", "total", "by_category": {...}}
    """
    wid = current_workspace_id() if workspace_id is None else workspace_id
    rows = list_memories(wid, limit=500)
    by_category: dict[str, int] = {}
    for item in rows:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    return {
        "workspace_id": wid,
        "total": len(rows),
        "by_category": by_category,
        # 当前生效的向量化后端（MEM 增强）：设置页据此提示"远端没配好，实际在用本地哈希"
        "embedding": memory_embedding.describe(),
    }


# --------------------------------------------------------------------------- #
# 4.5 生命周期维护（MEM 增强）：过期淘汰 / 条数上限 / 向量重建
# --------------------------------------------------------------------------- #
def prune(workspace_id: str | None = None) -> dict:
    """清理低价值记忆并把条数压回上限（写侧收尾动作，抽取之后自动跑一次）。

    两步，顺序不能反：
        1. **时间淘汰**：`importance <= 2` 且（`last_used_at` 或 `created_at`）早于
           `ttl_days()` 天 → 删。只动低重要度的条目，用户的结论与偏好不会被时间删掉；
        2. **数量上限**：仍超过 `max_per_workspace()` 时，按
           （重要度升序、`last_used_at` 为空的优先、`created_at` 升序）删到上限。
           排序里把"从没用过"的排前面，是因为它和"用过很多次"的价值差得最远。

    :param workspace_id: 工作区 id；None 取当前 active
    :return: {"workspace_id", "removed", "removed_expired", "removed_overflow", "total"}
    """
    wid = current_workspace_id() if workspace_id is None else workspace_id
    days = ttl_days()
    cap = max_per_workspace()
    removed_expired = 0
    removed_overflow = 0

    with get_session() as s:
        rows = s.scalars(
            select(Memory).where(Memory.workspace_id == wid).order_by(Memory.id.asc())
        ).all()

        # 1) 时间淘汰（ttl_days=0 表示关闭这一步）
        if days > 0:
            cutoff = _now_naive() - timedelta(days=days)
            expired_ids = [
                row.id
                for row in rows
                if int(row.importance or 3) <= 2
                and (row.last_used_at or row.created_at or cutoff) < cutoff
            ]
            if expired_ids:
                result = s.execute(delete(Memory).where(Memory.id.in_(expired_ids)))
                removed_expired = int(result.rowcount or 0)
                rows = [row for row in rows if row.id not in set(expired_ids)]

        # 2) 数量上限（cap=0 表示不限制）
        if cap > 0 and len(rows) > cap:
            def _rank(row: Memory) -> tuple[int, int, datetime, int]:
                """排序键：重要度越低越该删；从没用过的排在有使用记录的之前。"""
                return (
                    int(row.importance or 1),
                    0 if row.last_used_at is None else 1,
                    row.created_at or datetime.min,
                    int(row.id or 0),
                )

            overflow = sorted(rows, key=_rank)[: len(rows) - cap]
            if overflow:
                result = s.execute(
                    delete(Memory).where(Memory.id.in_([row.id for row in overflow]))
                )
                removed_overflow = int(result.rowcount or 0)
                rows = [row for row in rows if row.id not in {item.id for item in overflow}]

    total = len(rows)
    if removed_expired or removed_overflow:
        log.info(
            "记忆整理：过期 %d 条、超限 %d 条（工作区 %s，剩余 %d 条）",
            removed_expired, removed_overflow, wid, total,
        )
    return {
        "workspace_id": wid,
        "removed": removed_expired + removed_overflow,
        "removed_expired": removed_expired,
        "removed_overflow": removed_overflow,
        "total": total,
    }


def reindex(workspace_id: str | None = None, *, force: bool = False) -> dict:
    """按当前向量化后端重算记忆的向量（换 embedding 后端后必须跑一次）。

    为什么必须显式跑：两套后端的向量维度与语义空间都不同，
    `_cosine_matrix` 会把"维度不符"的行直接跳过——也就是换了后端之后，
    老记忆会**静默地检索不到**（不是报错，是悄悄不参与）。这里提供一次批量重算。

    默认只处理"没有向量"或"维度与当前后端不一致"的行；`force=True` 时全部重算。

    :param workspace_id: 工作区 id；None 取当前 active
    :param force: 是否连维度一致的行也重算
    :return: {"workspace_id", "total", "updated", "skipped", "dim", "embedding"}
    """
    wid = current_workspace_id() if workspace_id is None else workspace_id
    # 探针：先算一次"当前后端的维度"，避免为了比较维度而把每一行都向量化一遍
    probe_dim = int(_vectorize("dimension-probe").shape[0])

    with get_session() as s:
        rows = s.scalars(select(Memory).where(Memory.workspace_id == wid)).all()
        pending = [
            row
            for row in rows
            if force or row.embedding is None or int(row.dim or 0) != probe_dim
        ]
        if pending:
            # 远端后端支持一批一次请求；本地后端逐条算也很快
            vectors = memory_embedding.embed_many([row.content or "" for row in pending])
            for row, vec in zip(pending, vectors):
                row.set_embedding(vec)
            s.flush()

    updated = len(pending)
    log.info("记忆向量重建：%d 条（工作区 %s，维度 %d）", updated, wid, probe_dim)
    return {
        "workspace_id": wid,
        "total": len(rows),
        "updated": updated,
        "skipped": len(rows) - updated,
        "dim": probe_dim,
        "embedding": memory_embedding.describe(),
    }


# --------------------------------------------------------------------------- #
# 5. 抽取（一次裸模型调用）
# --------------------------------------------------------------------------- #
_EXTRACT_PROMPT = """从下面这段对话里抽取「对未来对话有帮助、值得记住」的信息。

要求：
- 只抽**长期有效**的内容：用户的偏好、已确定的方案决策、关于项目或环境的事实、尚未完成的待办。
- 不要抽：一次性的操作细节、寒暄、模型的自我描述、可以从代码里直接看出来的东西。
- 每条写成一句陈述，不要"用户说""助手说"这种前缀，也不要 markdown。
- category 只能是 preference（偏好）/ decision（决策）/ fact（事实）/ todo（待办）之一。
- importance 是 1~5 的整数，5 表示"以后每次都要遵守"。
- 最多 {max_items} 条；没有值得记的就输出空数组。

只输出 JSON 数组，不要任何解释。格式：
[{{"content": "…", "category": "decision", "importance": 4}}]

【对话】
用户：{user}

助手：{assistant}
"""


def build_extract_prompt(user_message: str, answer: str, max_items: int = MAX_EXTRACT_PER_TURN) -> str:
    """拼出抽取用的提示词（把对话截断后塞进固定模板）。

    :param user_message: 用户这一轮说的话
    :param answer: 助手这一轮的回答
    :param max_items: 最多抽几条
    :return: 完整提示词
    """
    return _EXTRACT_PROMPT.format(
        max_items=max_items,
        user=(user_message or "").strip()[:_MAX_INPUT_CHARS],
        assistant=(answer or "").strip()[:_MAX_INPUT_CHARS],
    )


def _strip_fence(text: str) -> str:
    """去掉 ```json … ``` 围栏并截出最外层的 JSON 数组。"""
    cleaned = re.sub(r"```(?:json)?", "", text or "").replace("```", "")
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        return "[]"
    return cleaned[start : end + 1]


def parse_memories(text: str, max_items: int = MAX_EXTRACT_PER_TURN) -> list[dict]:
    """解析模型返回的 JSON 数组，逐条校验并清洗。

    脏数据是常态（多包一层对象、category 写错、importance 给字符串），
    这里的原则是"能救则救、救不了就丢"，绝不让一条坏数据把整轮抽取废掉。

    :param text: 模型原始输出
    :param max_items: 最多接受多少条
    :return: [{"content", "category", "importance"}]
    """
    raw = _strip_fence(text)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        log.info("记忆抽取结果不是合法 JSON，本轮不记")
        return []
    if isinstance(data, dict):
        # 模型有时会包一层 {"memories": [...]}
        data = data.get("memories") or data.get("items") or []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split()).strip()
        if not content:
            continue
        content = content[:MAX_CONTENT_CHARS]
        digest = _content_hash(content)
        if digest in seen:
            continue
        seen.add(digest)
        category = str(item.get("category") or "fact").strip().lower()
        try:
            importance = int(item.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        out.append({
            "content": content,
            "category": category if category in MEMORY_CATEGORIES else "fact",
            "importance": max(1, min(importance, 5)),
        })
        if len(out) >= max_items:
            break
    return out


async def extract_and_store(
    workspace_id: str,
    session_id: str | None,
    user_message: str,
    answer: str,
) -> list[dict]:
    """用裸模型抽一轮对话里的记忆并落库（写侧主入口，由 chat 控制器异步调用）。

    为什么用裸模型：抽取只需要"会总结"，挂上工具反而会让它跑去读文件、把一次轻量调用变成一串动作。

    :param workspace_id: 工作区 id（空串时直接跳过：不知道该归给谁）
    :param session_id: 来源会话 id
    :param user_message: 用户这一轮说的话
    :param answer: 助手这一轮的回答
    :return: 本次新存入的记忆列表（可能为空）
    """
    if not extract_enabled() or not workspace_id:
        return []
    if not (user_message or "").strip() or not (answer or "").strip():
        return []

    # 项目内：延迟导入（模型层会在设置变化时自动失效重建）
    from langchain_core.messages import HumanMessage

    from app.llm.state import get_model

    try:
        model = get_model()
        response = await model.ainvoke([HumanMessage(content=build_extract_prompt(user_message, answer))])
        content = getattr(response, "content", "")
        text = content if isinstance(content, str) else str(content)
    except Exception:
        # 抽取失败是纯损耗，不能影响任何用户可见的行为
        log.warning("记忆抽取调用失败，本轮不记", exc_info=True)
        return []

    stored: list[dict] = []
    for item in parse_memories(text):
        try:
            saved = add_memory(
                workspace_id,
                item["content"],
                category=item["category"],
                importance=item["importance"],
                source="auto",
                session_id=session_id,
            )
        except Exception:
            log.warning("写入记忆失败：%s", item.get("content", "")[:40], exc_info=True)
            continue
        if saved:
            stored.append(saved)
    if stored:
        log.info("本轮新增 %d 条记忆（会话 %s）", len(stored), session_id)
        # 收尾：顺手把"低价值且长期没用"的、以及超过条数上限的记忆清一批。
        # 放在抽取之后而不是单独定时任务里，是为了让维护成本跟"确实有写入"这件事绑定。
        try:
            prune(workspace_id)
        except Exception:
            log.warning("记忆整理失败，本轮跳过（不影响已保存的记忆）", exc_info=True)
    return stored


async def extract_from_session(session_id: str, workspace_id: str | None = None) -> list[dict]:
    """对一个已有会话的最后 1~2 轮做抽取（`POST /memory/extract` 的调试入口）。

    :param session_id: 会话 id
    :param workspace_id: 工作区 id；None 取当前 active
    :return: 新存入的记忆列表
    """
    # 项目内：延迟导入对话历史服务
    from app.services import chat_history_service as history

    wid = current_workspace_id() if workspace_id is None else workspace_id
    messages = history.get_messages(session_id) or []
    if len(messages) < 2:
        return []

    # 取最近一对「用户提问 + 助手回答」；找不到就返回空
    user_text, answer_text = "", ""
    for item in reversed(messages):
        role = item.get("role")
        content = item.get("content") or ""
        if not answer_text and role == "assistant" and content.strip():
            answer_text = content
            continue
        if answer_text and role == "user" and content.strip():
            user_text = content
            break
    if not user_text or not answer_text:
        return []
    return await extract_and_store(wid, session_id, user_text, answer_text)
