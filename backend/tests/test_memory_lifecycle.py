# tests/test_memory_lifecycle.py
"""MEM 增强（记忆合并 / 真 embedding / 过期淘汰）的单元测试。

测的都是"坏了会静默出错"的地方：
    1. **合并**：近似重复会改写已有那一行——正文、分类、重要度、哈希与向量必须一起更新，
       否则"同文去重"和"相似度检索"会拿着过期数据做判断；
    2. **使用记录**：检索命中要写 `last_used_at` / `use_count`，这是淘汰排序的依据；
    3. **淘汰**：只删低重要度且长期没用的；条数上限按"重要度低、最久没用、最早创建"删；
    4. **向量重建**：换后端后维度不一致的旧向量必须能被一次性重算，且默认不重复算已经对齐的行；
    5. **远端 embedding**：成功时用远端维度并归一化，失败时整批降级回本地哈希。

与 `test_memory.py` 一样会写真实的 app.db，每个用例用随机工作区 id，结束即清空。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：uuid 造隔离工作区、datetime/timedelta 造"很久以前"的时间戳
import uuid
from datetime import datetime, timedelta

# numpy：构造远端返回的假向量
import numpy as np
# 测试框架
import pytest
# SQLAlchemy：查询与批量改时间戳
from sqlalchemy import select, update

# 项目内：数据库会话、记忆实体、被测服务与设置注册
from app.db.db_config import get_session
from app.entity.memory import Memory
from app.services import memory_embedding, memory_service, settings_registry
from app.services.memory_settings_defs import register_memory_defs


@pytest.fixture(autouse=True)
def _ensure_memory_defs():
    """确保 memory.* 设置声明已注册，并清掉向量缓存（缓存会跨用例串后端）。"""
    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    register_memory_defs()
    memory_embedding.clear_cache()
    yield
    memory_embedding.clear_cache()


@pytest.fixture()
def workspace() -> str:
    """一个随机的工作区 id（= 作用域），用例结束后清掉它的全部记忆。"""
    wid = f"mem-life-{uuid.uuid4().hex[:8]}"
    yield wid
    memory_service.clear_workspace(wid)


def _rows(workspace: str) -> list[Memory]:
    """读出该工作区的全部记忆实体（按 id 升序，便于断言顺序）。"""
    with get_session() as s:
        return list(
            s.scalars(
                select(Memory).where(Memory.workspace_id == workspace).order_by(Memory.id.asc())
            ).all()
        )


def _backdate(workspace: str, days: int, *, importance: int | None = None) -> None:
    """把该工作区（或其中某个重要度的）记忆的创建/使用时间改成 days 天前。

    直接改时间戳而不是 sleep：过期淘汰的规则与"现在几点"无关，
    只与"距今天数"有关，改库是最快也最确定的造数方式。

    :param workspace: 工作区 id
    :param days: 往前推多少天
    :param importance: 只改这个重要度的行；None 表示全改
    """
    old = datetime.now() - timedelta(days=days)
    with get_session() as s:
        stmt = update(Memory).where(Memory.workspace_id == workspace)
        if importance is not None:
            stmt = stmt.where(Memory.importance == importance)
        s.execute(stmt.values(created_at=old, updated_at=old, last_used_at=old))


# --------------------------------------------------------------------------- #
# 1. 合并
# --------------------------------------------------------------------------- #
def test_merge_prefers_more_specific_category(workspace: str) -> None:
    """合并时：正文取更长的那版、分类从 fact 升级为更具体的、重要度取最大。"""
    # 这一对是 doc/25 §13.2 实测校准用的样本，相似度 0.896（稳过 0.85 阈值）
    first = memory_service.add_memory(
        workspace, "用户偏好中文注释，不要英文注释", category="fact", importance=2
    )
    assert first is not None

    merged = memory_service.add_memory(
        workspace, "用户偏好中文注释，不要写英文注释。", category="preference", importance=5
    )

    assert merged is not None
    assert merged["merged"] is True
    assert merged["category"] == "preference"
    assert merged["importance"] == 5
    assert merged["content"] == "用户偏好中文注释，不要写英文注释。"
    assert merged["merged_count"] == 1


def test_merge_recomputes_hash_and_embedding(workspace: str) -> None:
    """合并改了正文，就必须重算哈希与向量，否则后续去重/检索会用到过期数据。"""
    first = memory_service.add_memory(workspace, "前端用 Vue3 + TypeScript", importance=3)
    assert first is not None
    # 相似度 0.87，属于"同一件事多了个限定条件"，应当合并而不是丢弃
    merged = memory_service.add_memory(workspace, "前端用 Vue3 + TypeScript，不用 JavaScript")
    assert merged is not None and merged["merged"] is True

    row = _rows(workspace)[0]
    assert row.content_hash == memory_service._content_hash(row.content)
    assert row.dim == 512 and row.embedding is not None

    # 同文再次写入 → 命中哈希去重，返回 None（说明哈希确实按新正文算过）
    assert memory_service.add_memory(workspace, row.content) is None


# --------------------------------------------------------------------------- #
# 2. 使用记录
# --------------------------------------------------------------------------- #
def test_search_records_usage(workspace: str) -> None:
    """检索命中后要记 use_count 与 last_used_at（淘汰排序依赖它）。"""
    memory_service.add_memory(workspace, "会话持久化用 SqliteSaver 存进 app.db", importance=4)

    hits = memory_service.search(workspace, "会话持久化怎么做")
    assert hits

    row = _rows(workspace)[0]
    assert row.use_count == 1
    assert row.last_used_at is not None
    assert hits[0]["use_count"] == 1


# --------------------------------------------------------------------------- #
# 3. 过期淘汰与条数上限
# --------------------------------------------------------------------------- #
def test_prune_removes_only_expired_low_value(workspace: str) -> None:
    """过期淘汰只删「重要度 ≤2 且很久没用」的；高重要度的老记忆必须留着。"""
    memory_service.add_memory(workspace, "低价值的临时观察", importance=1)
    memory_service.add_memory(workspace, "用户定下的长期方案", importance=5)
    _backdate(workspace, days=400)

    result = memory_service.prune(workspace)

    assert result["removed_expired"] == 1
    assert result["removed_overflow"] == 0
    assert [row.content for row in _rows(workspace)] == ["用户定下的长期方案"]


def test_prune_noop_when_ttl_disabled(workspace: str) -> None:
    """ttl_days=0 且不设上限时，再老的记忆也不删。"""
    settings_registry.put_settings({"memory.ttl_days": 0, "memory.max_per_workspace": 0})
    try:
        memory_service.add_memory(workspace, "很久以前的一条备忘", importance=1)
        _backdate(workspace, days=3000)

        result = memory_service.prune(workspace)

        assert result["removed"] == 0
        assert result["total"] == 1
    finally:
        settings_registry.put_settings({"memory.ttl_days": 180, "memory.max_per_workspace": 500})


def test_prune_enforces_cap_by_importance(workspace: str) -> None:
    """超过条数上限时，优先删重要度最低的。"""
    settings_registry.put_settings({"memory.ttl_days": 0, "memory.max_per_workspace": 2})
    try:
        memory_service.add_memory(workspace, "前端用 Vue3", importance=2)
        memory_service.add_memory(workspace, "后端用 FastAPI", importance=1)
        memory_service.add_memory(workspace, "数据库用 SQLite", importance=5)
        memory_service.add_memory(workspace, "界面用 nord 配色", importance=4)

        result = memory_service.prune(workspace)

        assert result["removed_overflow"] == 2
        assert result["total"] == 2
        assert sorted(row.importance for row in _rows(workspace)) == [4, 5]
    finally:
        settings_registry.put_settings({"memory.ttl_days": 180, "memory.max_per_workspace": 500})


def test_prune_keeps_the_used_one_when_tied(workspace: str) -> None:
    """重要度相同时，保留"被检索用过"的那条，删"从没用过"的。"""
    settings_registry.put_settings({"memory.ttl_days": 0, "memory.max_per_workspace": 1})
    try:
        used = memory_service.add_memory(workspace, "常用的那条约定", importance=3)
        memory_service.add_memory(workspace, "没人用过的那条观察", importance=3)
        assert used is not None
        # 手工制造"用过一次"的痕迹，避免依赖检索命中的排序细节
        with get_session() as s:
            s.execute(
                update(Memory)
                .where(Memory.id == used["id"])
                .values(use_count=3, last_used_at=datetime.now())
            )

        memory_service.prune(workspace)

        remaining = _rows(workspace)
        assert len(remaining) == 1
        assert remaining[0].id == used["id"]
    finally:
        settings_registry.put_settings({"memory.ttl_days": 180, "memory.max_per_workspace": 500})


# --------------------------------------------------------------------------- #
# 4. 向量重建
# --------------------------------------------------------------------------- #
def test_reindex_rebuilds_missing_vectors(workspace: str) -> None:
    """没有向量的行会被重算出来（换后端后老数据的常态）。"""
    saved = memory_service.add_memory(workspace, "向量要能重建", importance=3)
    assert saved is not None
    with get_session() as s:
        s.execute(
            update(Memory).where(Memory.id == saved["id"]).values(embedding=None, dim=None)
        )

    result = memory_service.reindex(workspace)

    assert result["updated"] == 1
    assert result["dim"] == 512
    row = _rows(workspace)[0]
    assert row.embedding is not None and row.dim == 512


def test_reindex_skips_aligned_rows_unless_forced(workspace: str) -> None:
    """维度已经对齐的行默认跳过；force=True 时全部重算。"""
    memory_service.add_memory(workspace, "已经对齐的向量", importance=3)

    assert memory_service.reindex(workspace)["updated"] == 0
    assert memory_service.reindex(workspace, force=True)["updated"] == 1


# --------------------------------------------------------------------------- #
# 5. 远端 embedding（用假端点，不联网）
# --------------------------------------------------------------------------- #
def test_remote_backend_normalizes_vectors(workspace: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """远端返回的向量没有单位长度保证，必须归一化后再落库。"""
    monkeypatch.setattr(memory_embedding, "is_remote_available", lambda: True)
    monkeypatch.setattr(
        memory_embedding, "_embed_remote", lambda texts: [np.array([3.0, 4.0]) for _ in texts]
    )

    vec = memory_embedding.embed_one("任意文本")
    assert vec.shape == (2,)
    assert pytest.approx(float(np.linalg.norm(vec)), rel=1e-6) == 1.0
    assert [round(float(x), 3) for x in vec] == [0.6, 0.8]

    saved = memory_service.add_memory(workspace, "远端向量化的记忆", importance=3)
    assert saved is not None
    assert _rows(workspace)[0].dim == 2


def test_remote_failure_falls_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """远端抛错时整批降级回本地哈希（512 维），不能让写入失败。"""
    monkeypatch.setattr(memory_embedding, "is_remote_available", lambda: True)

    def _boom(_texts: list[str]) -> list[np.ndarray]:
        """模拟端点 500。"""
        raise RuntimeError("embedding 端点返回 HTTP 500")

    monkeypatch.setattr(memory_embedding, "_embed_remote", _boom)

    vec = memory_embedding.embed_one("任意文本")
    assert vec.shape == (512,)


# --------------------------------------------------------------------------- #
# 6. 接口与统计
# --------------------------------------------------------------------------- #
def test_stats_reports_embedding_backend(workspace: str) -> None:
    """统计里要带上当前生效的向量化后端（设置页据此提示"已降级"）。"""
    stats = memory_service.stats(workspace)
    assert stats["embedding"] == "local"


def test_http_prune_and_reindex(workspace: str) -> None:
    """两个维护端点都能走通（真实路由）。"""
    # 项目内：FastAPI 测试客户端
    from fastapi.testclient import TestClient

    # 项目内：应用实例（提供 /api/memory/* 路由）
    from app.main import app

    client = TestClient(app)
    memory_service.add_memory(workspace, "待维护的一条记忆", importance=3)

    pruned = client.post("/api/memory/prune", json={"workspace_id": workspace}).json()
    assert set(pruned) == {
        "workspace_id", "removed", "removed_expired", "removed_overflow", "total",
    }

    reindexed = client.post("/api/memory/reindex", json={"workspace_id": workspace}).json()
    assert reindexed["workspace_id"] == workspace
    assert reindexed["dim"] == 512
    assert reindexed["embedding"] == "local"
