"""limit 参数契约的接口级自测（Python 侧）。

为什么要有这个文件：limit 以前是散的 —— 有的端点用 Query(ge=1, le=N)，有的端点原样透传给
SQL（`?limit=1000000` 会把整库拉回来），Java 侧又另有一套 service 内 clamp，两边数字还对不上。
现在统一成 app/core/limits.py 这张表 + 三条约定：

1. 默认值只表达「不传」，由 Query(default=...) 提供；
2. 显式越界（<1 或 >上限）由 FastAPI 直接报 422，不做静默截断；
3. 历史消息响应带 has_more，让前端知道「更早的还有没有」。

这里验证的是「HTTP 层真的按这套约定回话」，而不是 service 内部的实现细节。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 这类新语法
from __future__ import annotations

# JSON 解析：导出接口返回的是「文本套在 JSON 里」，要解析出来数消息条数
import json
# 每个用例用独立的会话 id，互不干扰（conftest 会在用例结束后清掉新增会话）
import uuid

# 测试客户端：在进程内直接调用 FastAPI 应用，不占用真实端口
from fastapi.testclient import TestClient

# 项目根应用实例
from app.main import app
# 契约表的默认值/上限：断言「文档上写的数字」和「接口真的按这个数字校验」一致
from app.core import limits
# 直接写消息行：一次插 200+ 条时比逐条 append 快得多
from app.db.db_config import get_session
# 消息实体：批量造的「长会话」要用它
from app.entity.chat_record import ChatMessage
# 造历史消息用：往 SQLite 里写用户提问（不需要真实模型）
from app.services.chat_history_service import append_user_message

# 复用同一个测试客户端
client = TestClient(app)


def _new_session() -> str:
    """生成一个本次用例专用的会话 id。

    :return: 32 位十六进制会话 id
    """
    return uuid.uuid4().hex


def test_history_rejects_out_of_range_limit() -> None:
    """历史消息：limit 小于 1 或超过上限都必须 422，而不是被悄悄换成默认值。"""
    sid = _new_session()
    assert client.get(f"/api/chat/history/sessions/{sid}", params={"limit": 0}).status_code == 422
    assert client.get(
        f"/api/chat/history/sessions/{sid}",
        params={"limit": limits.MAX_CHAT_HISTORY + 1},
    ).status_code == 422


def test_history_defaults_to_recent_messages() -> None:
    """不传 limit 时按默认值返回全部（这里只有 3 条），has_more 为 False。"""
    sid = _new_session()
    for text in ("第一句", "第二句", "第三句"):
        append_user_message(sid, text)

    body = client.get(f"/api/chat/history/sessions/{sid}").json()
    assert body["session_id"] == sid
    assert [m["content"] for m in body["messages"]] == ["第一句", "第二句", "第三句"]
    assert body["has_more"] is False


def test_history_reports_has_more_when_window_is_smaller() -> None:
    """同一个会话：窗口 2 条时返回最近的 2 条，并告知「更早的还有」。"""
    sid = _new_session()
    for text in ("第一句", "第二句", "第三句"):
        append_user_message(sid, text)

    body = client.get(f"/api/chat/history/sessions/{sid}", params={"limit": 2}).json()
    # 窗口取的是「最近」两条，顺序仍是时间正序
    assert [m["content"] for m in body["messages"]] == ["第二句", "第三句"]
    assert body["has_more"] is True

    # 刚好等于总条数时不留 has_more：不能多报「还有更早的」
    exact = client.get(f"/api/chat/history/sessions/{sid}", params={"limit": 3}).json()
    assert exact["has_more"] is False


def test_sessions_endpoint_rejects_out_of_range_limit() -> None:
    """会话列表：0 与超过上限都是 422（以前这里是「悄悄截到 100」）。"""
    assert client.get("/api/chat/sessions", params={"limit": 0}).status_code == 422
    assert client.get(
        "/api/chat/sessions", params={"limit": limits.MAX_CHAT_SESSIONS + 1},
    ).status_code == 422


def test_other_limit_endpoints_reject_out_of_range() -> None:
    """其余 limit 端点同样按契约表校验，不再有「没有上限」的漏网之鱼。"""
    # 文件候选：上限 50
    assert client.get("/api/file/search", params={"limit": limits.MAX_FILE_SEARCH + 1}).status_code == 422
    # 审计：上限 500
    assert client.get("/api/audit", params={"limit": limits.MAX_AUDIT + 1}).status_code == 422
    # 记忆：上限 500
    assert client.get("/api/memory", params={"limit": limits.MAX_MEMORY + 1}).status_code == 422
    # 轨迹会话：上限 200
    assert client.get(
        "/api/trace/sessions", params={"limit": limits.MAX_TRACE_SESSIONS + 1},
    ).status_code == 422
    # 轨迹轮次：上限 200
    assert client.get(
        "/api/trace/sessions/whatever/turns", params={"limit": limits.MAX_TRACE_TURNS + 1},
    ).status_code == 422
    # 轨迹事件：上限 5000
    assert client.get(
        "/api/trace/sessions/whatever", params={"limit": limits.MAX_TRACE_EVENTS + 1},
    ).status_code == 422
    # 文档列表：上限 200 —— 这是以前唯一完全没有上限的端点
    assert client.get(
        "/api/rag/documents", params={"limit": limits.MAX_RAG_DOCS + 1},
    ).status_code == 422


def test_other_limit_endpoints_reject_zero_limit() -> None:
    """其余 limit 端点：0 也是越界，不能当成「不限」或「用默认值」。"""
    # 以前有的端点把 limit<=0 解释成「用默认值」，客户端因此永远不知道自己传错了
    assert client.get("/api/file/search", params={"limit": 0}).status_code == 422
    assert client.get("/api/audit", params={"limit": 0}).status_code == 422
    assert client.get("/api/memory", params={"limit": 0}).status_code == 422
    assert client.get("/api/trace/sessions", params={"limit": 0}).status_code == 422
    assert client.get("/api/trace/sessions/whatever/turns", params={"limit": 0}).status_code == 422
    assert client.get("/api/trace/sessions/whatever", params={"limit": 0}).status_code == 422
    assert client.get("/api/rag/documents", params={"limit": 0}).status_code == 422


def test_export_keeps_messages_beyond_history_window() -> None:
    """导出是「全量」语义：消息条数超过 history 上限时也必须一条不少。

    契约表统一之后，history 的分页函数会把 limit 夹到 MAX_CHAT_HISTORY（200）以内。
    导出以前借用这个函数（`get_messages(limit=5000)`），超过 200 条的会话就会被悄悄截掉
    前半段——用户拿到一份「看起来完整」的文档，其实少了内容，这正是
    docs/adr/0001-limit-越界一律报错.md 明确拒绝的「静默截断」。
    """
    sid = _new_session()
    # 第一条走正式入口：它会顺带建出会话行（标题由内容生成）
    append_user_message(sid, "导出全量校验")
    # 再补到超过 history 上限，制造一个「一页装不下」的长会话
    total = limits.MAX_CHAT_HISTORY + 25
    with get_session() as s:
        s.add_all(
            # 只填必要字段：role/content 是唯二 non-null 且无默认值的列
            ChatMessage(session_id=sid, role="user", content=f"第 {i} 条")
            for i in range(1, total)
        )

    body = client.get(
        f"/api/chat/history/sessions/{sid}/export", params={"format": "json"},
    ).json()
    payload = json.loads(body["content"])
    # 1 条正式提问 + (total - 1) 条批量插入，少一条都算截断
    assert len(payload["messages"]) == total
    assert body["message_count"] == total
