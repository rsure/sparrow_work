"""UX 收尾（UX-4 / UX-8 / ARCH-7）的自测：置顶归档、导出、斜杠命令、`@` 文件搜索、轨迹回放入口。

这些用例都走"真实服务 + 真实 HTTP 端点"，不替换模型：
    它们测的不是 Agent 怎么跑，而是"用户在界面上点一下，后端给不给得出正确的数据"。

会落到真实 ./app.db（与 conftest.py 的说明一致），并且每个用例自己清理：
    新建的会话在用例结束前删掉，避免污染开发者本地的「最近会话」。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# JSON 序列化：导出接口返回的是 JSON 文本，需要解析回来断言
import json
# 两次建会话之间要留一点时间间隔，用来区分 updated_at（见 test_pinned_sorts_first_... 的说明）
import time
# 每个用例用独立会话 id，互不干扰
import uuid

# 测试框架：monkeypatch 替换依赖、tmp_path 提供临时目录
import pytest
# 测试客户端：进程内调用 FastAPI 应用
from fastapi.testclient import TestClient

# 被测对象：项目根应用实例
from app.main import app
# 被测对象：对话记录服务（置顶/归档/导出都在这里）
from app.services import chat_history_service
# 被测对象：工作区服务（`@` 文件搜索要按当前工作区根目录搜）
from app.services import workspace_service
# 被测对象：轨迹服务（回放页要先能列出有轨迹的会话与轮次）
from app.services import trace_service

# 复用同一个测试客户端
client = TestClient(app)

# 本文件写过的轨迹会话 id（用例结束后按它删除 trace_events 行）
_TRACE_SESSIONS: list[str] = []


def _new_session() -> str:
    """建一个只属于本用例的会话（带两条消息，标题由第一条消息生成）。

    :return: 会话 id
    """
    sid = uuid.uuid4().hex
    chat_history_service.append_user_message(sid, "帮我总结一下这个项目里 UX 相关的待办")
    chat_history_service.append_assistant_turn(
        sid, "UX-4 会话管理、UX-8 命令面板。", finish_reason="done", model="deepseek-chat",
    )
    return sid


def test_pinned_sorts_first_and_archived_is_filtered() -> None:
    """置顶的会话必须排在更晚活跃的普通会话前面；归档后默认列表里查不到。"""
    old = _new_session()
    # 间隔 20ms 再建第二个：updated_at 取自系统时钟，而 Windows 上 datetime.now() 的粒度
    # 可能粗到毫秒级，两次连续建会话会拿到**同一个**时间戳。那时列表只能按 session_id 兜底排序，
    # 先后就变成随机的，这条"后建的在前"的断言会假失败（生产里也没人同一跳建两个会话）
    time.sleep(0.02)
    new = _new_session()
    try:
        # 先确认基线：后建的会话排前面（按 updated_at 倒序）
        listed = chat_history_service.list_sessions(limit=50)
        ids = [row["session_id"] for row in listed]
        assert ids.index(new) < ids.index(old)

        # 置顶"较旧"的那个，它就该跳到最前
        flags = chat_history_service.set_session_flags(old, pinned=True)
        assert flags == {"pinned": True, "archived": False}
        ids = [row["session_id"] for row in chat_history_service.list_sessions(limit=50)]
        assert ids.index(old) < ids.index(new)

        # 归档它：默认列表里消失，档案箱里出现（数据一条没删）
        chat_history_service.set_session_flags(old, archived=True)
        assert old not in [row["session_id"] for row in chat_history_service.list_sessions(limit=50)]
        archived_ids = [
            row["session_id"] for row in chat_history_service.list_sessions(limit=50, archived=True)
        ]
        assert old in archived_ids
        assert chat_history_service.has_messages(old) is True
    finally:
        chat_history_service.delete_session(old)
        chat_history_service.delete_session(new)


def test_set_session_flags_unknown_session_returns_none() -> None:
    """给不存在的会话设标记时返回 None，而不是悄悄建出一条空会话。"""
    assert chat_history_service.set_session_flags("nope-" + uuid.uuid4().hex, pinned=True) is None


def test_patch_endpoint_toggles_pinned_and_archived() -> None:
    """PATCH /chat/history/sessions/{id} 一次能表达改名 + 置顶 + 归档。"""
    sid = _new_session()
    try:
        resp = client.patch(f"/api/chat/history/sessions/{sid}", json={"pinned": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["pinned"] is True and body["archived"] is False

        resp = client.patch(f"/api/chat/history/sessions/{sid}",
                            json={"title": "改过的标题", "archived": True})
        body = resp.json()
        assert body["title"] == "改过的标题"
        assert body["archived"] is True
        # 归档不该把置顶状态清掉（两个开关互相独立）
        assert body["pinned"] is True

        # 列表里的 archived=true 才能看到它
        listed = client.get("/api/chat/sessions", params={"archived": True}).json()["sessions"]
        row = next(item for item in listed if item["session_id"] == sid)
        assert row["title"] == "改过的标题"
    finally:
        chat_history_service.delete_session(sid)


def test_export_markdown_and_json() -> None:
    """导出接口：md 便于阅读（带标题/工具段），json 结构化且能被解析回来。"""
    sid = _new_session()
    try:
        md = client.get(f"/api/chat/history/sessions/{sid}/export").json()
        assert md["format"] == "md"
        assert md["filename"].endswith(".md")
        assert "UX-4 会话管理" in md["content"]
        assert md["message_count"] == 2

        js = client.get(f"/api/chat/history/sessions/{sid}/export", params={"format": "json"}).json()
        payload = json.loads(js["content"])
        assert payload["session"]["session_id"] == sid
        assert len(payload["messages"]) == 2
    finally:
        chat_history_service.delete_session(sid)


def test_export_unknown_session_is_404() -> None:
    """导出不存在的会话返回 404（而不是一份空文档）。"""
    resp = client.get(f"/api/chat/history/sessions/nope-{uuid.uuid4().hex}/export")
    assert resp.status_code == 404


def test_export_rejects_unknown_format() -> None:
    """format 只接受 md / json，其它值由 Query 的 pattern 拦成 422。"""
    sid = _new_session()
    try:
        resp = client.get(f"/api/chat/history/sessions/{sid}/export", params={"format": "pdf"})
        assert resp.status_code == 422
    finally:
        chat_history_service.delete_session(sid)


def test_commands_endpoint_lists_builtin_commands() -> None:
    """GET /api/commands 至少包含 5 条内置命令，且 source/action 契约齐全。"""
    body = client.get("/api/commands").json()
    commands = body["commands"]
    names = [item["name"] for item in commands]
    for expected in ("doc", "model", "clear", "export", "help"):
        assert expected in names
    # 内置命令必须排在技能前面：前端按顺序渲染，同名时内置优先
    builtin_indexes = [i for i, item in enumerate(commands) if item["source"] == "builtin"]
    assert builtin_indexes == list(range(len(builtin_indexes)))
    doc = next(item for item in commands if item["name"] == "doc")
    assert doc["action"] == "doc"
    # 契约字段恒定存在（前端可直接读，不用判 undefined）
    for item in commands:
        assert set(item) == {"name", "description", "args_hint", "source", "action"}


def test_file_search_finds_files_under_workspace(tmp_path, monkeypatch) -> None:
    """`@` 文件搜索只在当前工作区里找，且"文件名开头命中"排在"路径里命中"前面。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "需求方案.md").write_text("x", encoding="utf-8")
    (tmp_path / "other.md").write_text("y", encoding="utf-8")
    # 目标文件叫 AB 开头，命中的另一份只在目录名里含 ab
    (tmp_path / "ab报告.md").write_text("z", encoding="utf-8")
    monkeypatch.setattr(workspace_service, "get_active_roots", lambda: [tmp_path])

    data = client.get("/api/file/search", params={"q": "ab"}).json()["data"]
    names = [item["name"] for item in data["items"]]
    assert "ab报告.md" in names
    assert names[0] == "ab报告.md"
    assert data["roots"] == [str(tmp_path)]
    # 没命中的不该出现
    assert "other.md" not in names

    # 空查询也要给得出东西（刚敲下 `@` 时不能是一片空白）
    everything = client.get("/api/file/search").json()["data"]
    assert len(everything["items"]) == 3
    assert all(item["path"] for item in everything["items"])


@pytest.fixture(autouse=True)
def _cleanup_trace_rows():
    """用例结束后清掉本文件写入的轨迹行（轨迹表没有级联删除，得自己收拾）。"""
    yield
    if not _TRACE_SESSIONS:
        return
    # 项目内：延迟导入，避免收集阶段就连库
    from sqlalchemy import delete

    from app.db.db_config import get_session
    from app.entity.trace import TraceEvent

    with get_session() as s:
        s.execute(delete(TraceEvent).where(TraceEvent.session_id.in_(list(_TRACE_SESSIONS))))
    _TRACE_SESSIONS.clear()


def test_trace_sessions_and_turns_endpoints() -> None:
    """回放页入口：能列出有轨迹的会话，也能列出该会话的轮次。"""
    sid = uuid.uuid4().hex
    # 记下来，用例结束后由 _cleanup_trace_rows 删掉
    _TRACE_SESSIONS.append(sid)
    turn_id = "t" + uuid.uuid4().hex[:12]
    # 直接写两条轨迹（不走 Agent），验证的是查询而不是采集
    trace_service.record(sid, turn_id, "turn_start", payload={"mode": "agent"})
    trace_service.record(sid, turn_id, "thinking", payload={"stage": "analyzing"})

    sessions = client.get("/api/trace/sessions", params={"limit": 200}).json()["sessions"]
    row = next(item for item in sessions if item["session_id"] == sid)
    assert row["event_count"] == 2
    assert row["turn_count"] == 1
    # 会话标题查不到时返回空串（前端回退显示 id 前 8 位），而不是抛错
    assert row["title"] == ""

    turns = client.get(f"/api/trace/sessions/{sid}/turns").json()
    assert turns["count"] == 1
    turn = turns["turns"][0]
    assert turn["turn_id"] == turn_id
    assert turn["mode"] == "agent"
    assert turn["event_count"] == 2

    # 再读具体事件，确认 seq 顺序（回放按这个顺序播）
    events = client.get(f"/api/trace/sessions/{sid}", params={"turn_id": turn_id}).json()["events"]
    assert [e["seq"] for e in events] == [0, 1]
    assert events[0]["kind"] == "turn_start"


@pytest.fixture(autouse=True)
def _cleanup_trace_rows():
    """用例结束后清掉本文件写入的轨迹行（轨迹表没有级联删除，得自己收拾）。"""
    yield
    if not _TRACE_SESSIONS:
        return
    # 项目内：延迟导入，避免收集阶段就连库
    from sqlalchemy import delete

    from app.db.db_config import get_session
    from app.entity.trace import TraceEvent

    with get_session() as s:
        s.execute(delete(TraceEvent).where(TraceEvent.session_id.in_(list(_TRACE_SESSIONS))))
    _TRACE_SESSIONS.clear()
