# tests/test_memory.py
"""MEM 工作空间记忆的单元测试。

测四类东西，都是"坏了会静默出错"的地方：
    1. **作用域隔离**：记忆按工作区隔离，串了就等于把 A 项目的约定喂给 B 项目；
    2. **去重**：同一句话被反复抽出来，会让注入块被同一件事占满；
    3. **降级**：抽取失败 / 未启用 / 没有工作区时，必须安静地什么都不做；
    4. **检索排序**：相关度优先，重要度只做微调（不能翻盘）。

本文件会往真实的 app.db 写 memories，所以每个工作区 id 都是随机生成的，
用完删掉（与 conftest 清理对话记录、test_trace 清理轨迹是同一个思路）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：asyncio 直跑协程、uuid 造隔离的工作区 id
import asyncio
import uuid

# 测试框架
import pytest
# SQLAlchemy：删除
from sqlalchemy import delete

# 项目内：数据库会话、记忆实体、被测服务与设置注册
from app.db.db_config import get_session
from app.entity.memory import Memory
from app.services import memory_service, settings_registry
from app.services.memory_settings_defs import register_memory_defs


@pytest.fixture(autouse=True)
def _ensure_memory_defs():
    """确保 memory.* 设置声明已注册。

    其它用例会 `reset_for_test()` 清空注册表，这里每条用例前补一次，
    避免本文件的结果依赖"测试执行顺序"。
    """
    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    register_memory_defs()
    yield


@pytest.fixture()
def workspace() -> str:
    """一个随机的工作区 id（= 作用域），用例结束后清掉它的全部记忆。"""
    wid = f"mem-test-{uuid.uuid4().hex[:8]}"
    yield wid
    memory_service.clear_workspace(wid)


# --------------------------------------------------------------------------- #
# 1. 写入与去重
# --------------------------------------------------------------------------- #
def test_add_memory_persists_and_vectorizes(workspace: str) -> None:
    """新增后能读回来，且向量已写入（否则检索永远命中不到）。"""
    saved = memory_service.add_memory(
        workspace, "项目统一用 pnpm 管理前端依赖", category="decision", importance=4,
    )

    assert saved is not None
    assert saved["content"] == "项目统一用 pnpm 管理前端依赖"
    assert saved["category"] == "decision"
    assert saved["importance"] == 4
    assert saved["created_at"] is not None

    with get_session() as s:
        row = s.get(Memory, saved["id"])
        assert row is not None
        assert row.embedding is not None
        assert row.dim == 512


def test_duplicate_content_is_skipped(workspace: str) -> None:
    """完全相同的正文只存一次。"""
    first = memory_service.add_memory(workspace, "后端统一用 uv 管理依赖")
    second = memory_service.add_memory(workspace, "后端统一用 uv 管理依赖")

    assert first is not None
    assert second is None
    assert len(memory_service.list_memories(workspace)) == 1


def test_similar_content_is_merged(workspace: str) -> None:
    """近似重复（只差几个字）不再丢弃，而是合并进已有那条（MEM 增强）。"""
    first = memory_service.add_memory(workspace, "用户偏好中文注释，不要英文注释", importance=2)
    assert first is not None
    # 只改了标点与语气词，2-gram 重合度极高
    merged = memory_service.add_memory(workspace, "用户偏好中文注释，不要写英文注释。", importance=4)

    assert merged is not None
    assert merged["merged"] is True
    assert merged["id"] == first["id"], "合并应该落在同一条记忆上，不能新建"
    # 更长的那一版胜出，重要度取两者最大值
    assert merged["content"] == "用户偏好中文注释，不要写英文注释。"
    assert merged["importance"] == 4
    assert merged["merged_count"] == 1
    assert len(memory_service.list_memories(workspace)) == 1


def test_merge_can_be_disabled(workspace: str) -> None:
    """关掉 memory.merge_enabled 后退回老行为：近似重复直接返回 None。"""
    settings_registry.put_settings({"memory.merge_enabled": False})
    try:
        assert memory_service.add_memory(workspace, "用户偏好中文注释，不要英文注释") is not None
        assert memory_service.add_memory(workspace, "用户偏好中文注释，不要写英文注释。") is None
        assert len(memory_service.list_memories(workspace)) == 1
    finally:
        # 把设置恢复成默认值，别污染后续用例
        settings_registry.put_settings({"memory.merge_enabled": True})


def test_different_content_is_kept(workspace: str) -> None:
    """两件不同的事必须都能存下来（去重不能过度）。"""
    assert memory_service.add_memory(workspace, "前端用 Vue 3 + TypeScript") is not None
    assert memory_service.add_memory(workspace, "数据库用 SQLite，不做远程部署") is not None
    assert len(memory_service.list_memories(workspace)) == 2


def test_blank_content_is_rejected(workspace: str) -> None:
    """空白正文直接忽略（模型偶尔会输出空字符串）。"""
    assert memory_service.add_memory(workspace, "   \n  ") is None
    assert memory_service.list_memories(workspace) == []


# --------------------------------------------------------------------------- #
# 2. 检索与作用域隔离
# --------------------------------------------------------------------------- #
def test_search_finds_related_memory(workspace: str) -> None:
    """检索能按字面相关度找到对应记忆，无关的排在后面或不出现。"""
    memory_service.add_memory(workspace, "会话持久化用 SqliteSaver 存进 app.db", importance=4)
    memory_service.add_memory(workspace, "界面配色使用 nord 预设", importance=2)

    hits = memory_service.search(workspace, "会话持久化是怎么做的")

    assert hits, "应当至少命中一条"
    assert "SqliteSaver" in hits[0]["content"]
    assert hits[0]["score"] > 0


def test_search_is_isolated_by_workspace(workspace: str) -> None:
    """A 工作区的记忆不能被 B 工作区检索到（串了就是隐私问题）。"""
    other = f"mem-test-{uuid.uuid4().hex[:8]}"
    try:
        memory_service.add_memory(other, "另一个项目用 PostgreSQL 做持久化")
        # 同一个问题在 workspace 里没有记忆可命中
        assert memory_service.search(workspace, "持久化用什么数据库") == []
    finally:
        memory_service.clear_workspace(other)


def test_search_respects_min_importance(workspace: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """重要度门槛生效：低于门槛的记忆不参与检索。"""
    memory_service.add_memory(workspace, "低价值的临时观察记录", importance=1)
    monkeypatch.setattr(memory_service, "min_importance", lambda: 4)

    assert memory_service.search(workspace, "临时观察记录") == []


def test_search_ranks_relevance_over_importance(workspace: str) -> None:
    """相关度高的必须排在重要度高但不太相关的前面。"""
    memory_service.add_memory(workspace, "配色用 nord 预设，界面偏冷色", importance=5)
    memory_service.add_memory(workspace, "会话持久化用 SqliteSaver，thread_id 就是会话 id", importance=2)

    hits = memory_service.search(workspace, "会话持久化 thread_id")

    assert hits
    assert "SqliteSaver" in hits[0]["content"]


def test_search_returns_empty_without_workspace(workspace: str) -> None:
    """没有工作区（空串）时不检索——不知道该给谁看，就不该给。"""
    memory_service.add_memory(workspace, "随便一条记忆")
    assert memory_service.search("", "记忆") == []


# --------------------------------------------------------------------------- #
# 3. 注入块
# --------------------------------------------------------------------------- #
def test_format_block_warns_not_to_repeat() -> None:
    """注入块必须写明"不要向用户复述"，否则模型会把记忆当用户的话说出来。"""
    block = memory_service.format_block([
        {"category": "decision", "content": "会话持久化用 SqliteSaver"},
    ])

    assert "不要向用户复述" in block
    assert "[decision] 会话持久化用 SqliteSaver" in block


def test_build_injection_returns_empty_when_disabled(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注入开关关闭时返回空串（对话行为与没有这个功能时一致）。"""
    memory_service.add_memory(workspace, "会话持久化用 SqliteSaver")
    monkeypatch.setattr(memory_service, "inject_enabled", lambda: False)

    assert memory_service.build_injection(workspace, "持久化怎么做的") == ""


def test_build_injection_swallows_errors(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """检索抛异常时返回空串，绝不能把异常抛进对话主流程。"""

    def _boom(*_args, **_kwargs):
        """模拟检索内部的意外错误。"""
        raise RuntimeError("db is locked")

    monkeypatch.setattr(memory_service, "search", _boom)
    assert memory_service.build_injection(workspace, "任意问题") == ""


# --------------------------------------------------------------------------- #
# 4. 抽取结果解析
# --------------------------------------------------------------------------- #
def test_parse_memories_handles_code_fence() -> None:
    """模型习惯用 ```json 围栏包裹，必须能剥掉。"""
    text = '```json\n[{"content":"用 pnpm","category":"decision","importance":4}]\n```'
    items = memory_service.parse_memories(text)

    assert len(items) == 1
    assert items[0]["content"] == "用 pnpm"
    assert items[0]["importance"] == 4


def test_parse_memories_handles_wrapped_object() -> None:
    """有时会包一层 {"memories": [...]}。"""
    text = '{"memories": [{"content": "用 uv 管依赖", "category": "fact", "importance": 3}]}'
    assert memory_service.parse_memories(text)[0]["content"] == "用 uv 管依赖"


def test_parse_memories_drops_bad_items_and_clamps() -> None:
    """坏条目被丢弃，越界的 category / importance 被修正而不是整批失败。"""
    text = (
        '[{"content": ""}, {"content": "有效的一条", "category": "瞎写", "importance": 99},'
        ' {"content": "   "}, "not-an-object"]'
    )
    items = memory_service.parse_memories(text)

    assert len(items) == 1
    assert items[0]["category"] == "fact"
    assert items[0]["importance"] == 5


def test_parse_memories_on_garbage_returns_empty() -> None:
    """完全不是 JSON 时返回空列表（不抛异常）。"""
    assert memory_service.parse_memories("我不知道该怎么回答") == []


def test_parse_memories_dedupes_within_batch() -> None:
    """同一批里重复的内容只保留一条。"""
    text = '[{"content":"用 pnpm"},{"content":"用 pnpm"}]'
    assert len(memory_service.parse_memories(text)) == 1


# --------------------------------------------------------------------------- #
# 5. 抽取（异步）+ 开关
# --------------------------------------------------------------------------- #
class _FakeModel:
    """假的裸模型：返回固定的 JSON 文本，不联网。"""

    def __init__(self, payload: str) -> None:
        """记住要返回的文本。"""
        self.payload = payload

    async def ainvoke(self, _messages):  # noqa: ANN001 —— 只需与真实接口同形
        """返回一个带 content 属性的对象（真实模型也是这么用的）。"""

        class _Resp:
            """最小响应对象。"""

            content = self.payload

        return _Resp()


def test_extract_and_store_persists(workspace: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """抽取成功时把结果落库（走真实的模型适配路径，模型被替换）。"""
    payload = '[{"content": "项目统一用 pnpm", "category": "decision", "importance": 4}]'
    monkeypatch.setattr("app.llm.state.get_model", lambda: _FakeModel(payload))

    stored = asyncio.run(
        memory_service.extract_and_store(workspace, "s1", "依赖用哪个？", "用 pnpm，不要 npm。")
    )

    assert len(stored) == 1
    assert stored[0]["source"] == "auto"
    assert stored[0]["session_id"] == "s1"
    assert len(memory_service.list_memories(workspace)) == 1


def test_extract_and_store_swallows_model_error(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型报错时返回空列表，绝不向调用方抛异常。"""

    class _Broken:
        """总是抛错的模型。"""

        async def ainvoke(self, _messages):  # noqa: ANN001
            """模拟调用超时。"""
            raise RuntimeError("timeout")

    monkeypatch.setattr("app.llm.state.get_model", lambda: _Broken())

    assert asyncio.run(memory_service.extract_and_store(workspace, "s1", "问", "答")) == []


def test_extract_disabled_does_nothing(workspace: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """抽取开关关闭时一次调用都不发（省钱的开关必须真的省）。"""
    called: list[int] = []

    class _Spy:
        """记录被调用的模型。"""

        async def ainvoke(self, _messages):  # noqa: ANN001
            """被调用即记录下来。"""
            called.append(1)
            raise AssertionError("不应该被调用")

    monkeypatch.setattr("app.llm.state.get_model", lambda: _Spy())
    monkeypatch.setattr(memory_service, "extract_enabled", lambda: False)

    assert asyncio.run(memory_service.extract_and_store(workspace, "s1", "问", "答")) == []
    assert called == []


def test_extract_skips_without_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有工作区时直接跳过（不知道该归给谁）。"""
    assert asyncio.run(memory_service.extract_and_store("", "s1", "问", "答")) == []


# --------------------------------------------------------------------------- #
# 6. HTTP 接口
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client():
    """FastAPI 测试客户端（与其它控制器测试一致，走真实路由）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_http_crud_flow(client, workspace: str) -> None:
    """接口闭环：新增 → 列表 → 检索 → 删除。"""
    created = client.post("/api/memory", json={
        "workspace_id": workspace,
        "content": "后端测试用 uv run pytest",
        "category": "decision",
        "importance": 4,
    }).json()
    assert created["saved"] is True
    memory_id = created["memory"]["id"]

    listed = client.get("/api/memory", params={"workspace_id": workspace}).json()
    assert [item["content"] for item in listed["memories"]] == ["后端测试用 uv run pytest"]

    hits = client.post("/api/memory/search", json={
        "workspace_id": workspace, "query": "后端测试怎么跑",
    }).json()
    assert hits["hits"] and "uv run pytest" in hits["hits"][0]["content"]

    assert client.delete(f"/api/memory/{memory_id}").json()["deleted"] is True
    assert client.get("/api/memory", params={"workspace_id": workspace}).json()["memories"] == []


def test_http_stats(client, workspace: str) -> None:
    """统计接口返回条数与分类分布。"""
    client.post("/api/memory", json={"workspace_id": workspace, "content": "偏好中文注释", "category": "preference"})
    client.post("/api/memory", json={"workspace_id": workspace, "content": "数据库用 SQLite", "category": "fact"})

    stats = client.get("/api/memory/stats", params={"workspace_id": workspace}).json()

    assert stats["total"] == 2
    assert stats["by_category"] == {"preference": 1, "fact": 1}


# --------------------------------------------------------------------------- #
# 7. chat 侧的写 hook（哪些轮次不该抽）
# --------------------------------------------------------------------------- #
def test_schedule_skips_doc_mode_and_errors(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """doc 模式、error 收尾、太短的回答都不触发抽取。"""
    called: list[str] = []

    async def _spy(*_args, **_kwargs):
        """被调用即记录。"""
        called.append("hit")
        return []

    monkeypatch.setattr(memory_service, "extract_and_store", _spy)
    # 项目内：被测控制器
    from app.controllers import chat_controller as cc

    async def _scenario() -> None:
        """三种不该抽的情形各跑一次。"""
        long_answer = "这是一段足够长的回答，用来确保长度门槛不会把这条用例挡掉。"
        sess = cc.SessionState(session_id="mem-hook-1")
        sess.turn_user_message = "问"
        cc._schedule_memory_extract(sess, long_answer, "done", "t")

        sess_doc = cc.SessionState(session_id="mem-hook-2")
        sess_doc.turn_mode = "doc"
        cc._schedule_memory_extract(sess_doc, long_answer, "done", "t")

        sess_err = cc.SessionState(session_id="mem-hook-3")
        cc._schedule_memory_extract(sess_err, long_answer, "error", "t")

        sess_short = cc.SessionState(session_id="mem-hook-4")
        cc._schedule_memory_extract(sess_short, "好的", "done", "t")

        # 让后台任务真正跑完，再检查有没有被调用
        await asyncio.sleep(0.05)

    asyncio.run(_scenario())
    assert called == ["hit"], "只有正常结束且回答够长的那一轮才该抽取"


# --------------------------------------------------------------------------- #
# 8. chat 侧的读 hook（什么时候注入、注入的是什么）
# --------------------------------------------------------------------------- #
class _DummyRequest:
    """假的 Starlette Request：本轮不需要断连检测（`_run_with_tasks` 被替换掉了）。"""

    async def is_disconnected(self) -> bool:
        """永远不断开。"""
        return False


def _run_stream_capture(monkeypatch: pytest.MonkeyPatch, session_id: str, message: str) -> dict:
    """跑一次 `_run_agent_stream`，把送给模型的 graph_input 截下来。

    `_run_with_tasks` 是编排层的入口（内部才真正调模型），把它替换成"记一笔就走"，
    就可以在不联网的前提下断言"注入发生在哪一层、内容长什么样"。

    :param monkeypatch: pytest 的替换工具
    :param session_id: 会话 id
    :param message: 用户输入
    :return: {"user_content": 送给模型的那条用户消息, "tasks_message": 传给编排层的原始文本}
    """
    # 项目内：被测控制器
    from app.controllers import chat_controller as cc

    captured: dict = {}

    async def _fake_run(graph_input, effective_message, *_args, **_kwargs):
        """假编排：只记录收到了什么，不调模型。"""
        captured["user_content"] = graph_input["messages"][-1]["content"]
        captured["tasks_message"] = effective_message
        # 必须 yield 一次，否则 async for 里什么都不发生（但这不重要）
        if False:  # pragma: no cover —— 让函数成为异步生成器
            yield ""

    monkeypatch.setattr(cc, "_run_with_tasks", _fake_run)

    async def _drive() -> None:
        """把整条流跑干（它会被替换掉的部分不产生事件）。"""
        req = cc.ChatRequest(message=message, session_id=session_id)
        async for _frame in cc._run_agent_stream(req, "trace-mem", _DummyRequest()):
            pass

    asyncio.run(_drive())
    return captured


def test_injection_only_for_first_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """新会话的首条消息注入记忆块；同一会话的第二条消息不再注入。"""
    session_id = f"mem-inject-{uuid.uuid4().hex[:8]}"
    marker = "【本工作区相关记忆】（测试用标记）"

    # 项目内：注入函数被替换成固定标记，避免依赖真实记忆内容
    monkeypatch.setattr(memory_service, "build_injection", lambda *_a, **_k: marker)
    # 触发编排前不要真的压缩上下文（它要读 checkpointer）
    from app.controllers import chat_controller as cc

    async def _no_compress(*_args, **_kwargs) -> None:
        """跳过上下文压缩。"""
        return None

    monkeypatch.setattr(cc, "_maybe_compress", _no_compress)

    first = _run_stream_capture(monkeypatch, session_id, "第一个问题")
    assert marker in first["user_content"]
    # 展示/落库用的是 clean 文本：气泡与历史记录里不该出现注入块
    assert first["tasks_message"] == "第一个问题"

    second = _run_stream_capture(monkeypatch, session_id, "第二个问题")
    assert marker not in second["user_content"]


def test_no_injection_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入开关关闭时，首条消息也不带记忆块。"""
    session_id = f"mem-inject-off-{uuid.uuid4().hex[:8]}"
    from app.controllers import chat_controller as cc

    monkeypatch.setattr(memory_service, "inject_enabled", lambda: False)
    monkeypatch.setattr(memory_service, "search", lambda *_a, **_k: [
        {"category": "fact", "content": "不该出现的记忆", "importance": 5, "id": 1}
    ])

    async def _no_compress(*_args, **_kwargs) -> None:
        """跳过上下文压缩。"""
        return None

    monkeypatch.setattr(cc, "_maybe_compress", _no_compress)

    captured = _run_stream_capture(monkeypatch, session_id, "随便问一句")
    assert "不该出现的记忆" not in captured["user_content"]
