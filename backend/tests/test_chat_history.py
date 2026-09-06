"""对话记录落库 / 终止 / `\\doc` 知识库指令 的自测。

不调用真实 DeepSeek，也不碰真实 FAISS 索引：
- 对话链路用一个"按剧本回复"的假模型替换 chat_controller.agent（与 test_chat_confirm.py 同款做法）；
- `\\doc` 指令链路把控制器里的文档库读取入口、文档库服务、裸模型都换成假对象，
  这样测试只验证"控制器怎么编排"，不依赖网络与向量库。

真实验证的是：SQLite 落库（app/entity/chat_record.py）、终止信号（_iter_until_stop）、
`\\doc` 指令的解析与分派、以及 HTTP 端点的行为。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 这类新语法
from __future__ import annotations

# 解析 SSE 帧里的 data JSON
import json
# 构造测试文件的路径对象
from pathlib import Path
# 让"终止一条正在跑的流"能在后台线程里跑，主线程同时去调 /chat/stop
import threading
# 轮询等待后台流真正开始跑
import time
# 每个用例用独立的会话 id，互不干扰
import uuid
# 简单的假对象：SummonedHit 用它冒充一条检索命中结果
from types import SimpleNamespace

# 测试框架：fixture 声明 + monkeypatch 替换模块里的 agent / 模型 / 文档库服务
import pytest
# 测试客户端：在进程内直接调用 FastAPI 应用，不占用真实端口
from fastapi.testclient import TestClient
# LangChain 1.x 的 Agent 构造器：用假模型 + 真实工具组装测试用 Agent
from langchain.agents import create_agent
# LangChain 内置假模型：按 responses 列表依次返回预设消息，不发网络请求
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
# AIMessage：构造"模型发起工具调用""模型给出最终回答"两条剧本消息
from langchain_core.messages import AIMessage
# LangGraph 内存检查点：测试 Agent 也要有它，interrupt 才能暂停与恢复
from langgraph.checkpoint.memory import InMemorySaver

# 被测对象：控制器模块（替换其中的 agent / model / _rag_svc）
from app.controllers import chat_controller
# 被测对象：项目根应用实例
from app.main import app
# 真实的全部工具列表（与线上 Agent 完全一致）
from app.agents.rag_agent import TOOLS

# 复用同一个测试客户端
client = TestClient(app)


class _ScriptedModel(FakeMessagesListChatModel):
    """按剧本回复的假模型。create_agent 会调用 bind_tools 绑定工具，假模型不需要，直接返回自身。"""

    def bind_tools(self, tools, **kwargs):
        """忽略工具绑定，返回自身，保证 create_agent 能正常组装。"""
        return self


class _EchoModel:
    """`\\doc` 链路用的假裸模型：把回答拆成几片"流"出来，每片之间停一下方便被终止。"""

    def __init__(self, pieces: list[str], delay: float = 0.15) -> None:
        """记住要吐出的文字片段与每片之间的间隔。

        :param pieces: 依次产出的文本片段（拼起来就是完整回答）
        :param delay: 每片之间的等待秒数（模拟模型逐字生成）
        """
        self.pieces = pieces
        self.delay = delay
        self.emitted = 0        # 已产出的片段数，供测试断言"确实被打断了"

    async def astream(self, messages):
        """模拟模型的流式输出：逐片产出带 content 字段的假 chunk。

        :param messages: 控制器拼好的 messages（本假模型不关心内容）
        :return: 异步生成器，产出形如 {"content": "..."} 的对象
        """
        import asyncio
        for piece in self.pieces:
            await asyncio.sleep(self.delay)
            self.emitted += 1
            yield SimpleNamespace(content=piece)


class _StubRagService:
    """`\\doc` 链路用的假文档库服务：只实现控制器会调用的 search / delete_by_ids。"""

    def __init__(self, hits: list) -> None:
        """记住要返回的命中列表。

        :param hits: 每次 search 都返回这批命中（空列表表示"没检索到"）
        """
        self.hits = hits
        self.calls: list[dict] = []         # search 收到的参数，供测试断言 scope 有没有传对
        self.deleted: list[list[int]] = []  # delete_by_ids 收到的 id 列表，供删除用例断言

    def search(self, query: str, *, top_k: int = 10, sources=None):
        """假的向量检索：记下参数并返回预置的命中列表。"""
        self.calls.append({"query": query, "top_k": top_k, "sources": sources})
        return self.hits

    def delete_by_ids(self, doc_ids: list[int]) -> int:
        """假的删除：记下要删的 id 并假装都删掉了。"""
        self.deleted.append(list(doc_ids))
        return len(doc_ids)


class _StubTool:
    """冒充 LangChain 工具对象：只实现控制器会用到的 invoke。"""

    def __init__(self, output: str) -> None:
        """记住要返回的工具输出文本。

        :param output: 形如 "OK: ..." 的工具返回值
        """
        self.output = output
        self.calls: list[dict] = []     # invoke 收到的入参，供测试断言

    def invoke(self, args: dict) -> str:
        """假的工具执行：记下入参并返回预置输出。"""
        self.calls.append(args)
        return self.output


def _hit(source: str, text: str = "示例正文", index: int = 0) -> SimpleNamespace:
    """造一条假的检索命中（字段与 rag_store_service.SearchHit 对齐）。

    :param source: 所属文档来源（绝对路径或文件名）
    :param text: 片段原文
    :param index: 片段在文档内的序号
    :return: 带 chunk_index / source / title / text / score 的假对象
    """
    return SimpleNamespace(
        chunk_id=index, doc_id=1, source=source, title=None,
        chunk_index=index, text=text, score=0.9,
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """把 SSE 响应体拆成 [(事件名, data 字典)]，方便按事件断言。

    :param text: 完整响应文本
    :return: 事件列表，顺序与推送顺序一致
    """
    events = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _first(events: list[tuple[str, dict]], name: str) -> dict | None:
    """取第一条指定名字的事件数据；没有则返回 None。"""
    return next((d for e, d in events if e == name), None)


def _plan_doc(doc_id: int = 1, name: str = "plan.md") -> dict:
    """造一条假的"已导入文档"记录（字段与 rag_store_service.list_documents 对齐）。

    :param doc_id: 文档 id（删除时会把它传给 delete_by_ids）
    :param name: 文件名（`\\doc 文件名` 就是按它匹配的）
    :return: 含 id / name / source / chunks / file_size 的字典
    """
    return {
        "id": doc_id,
        "name": name,
        "source": f"D:\\docs\\{name}",
        "chunks": 3,
        "file_size": 2048,
    }


def _stub_library(monkeypatch: pytest.MonkeyPatch, docs: list[dict]) -> None:
    """把控制器读取知识库的三个入口整体换成给定的一批假文档。

    真实实现要读 SQLite 里已导入的文档，测试环境没导入过任何东西，任何文件名都匹配不上。
    这里一次性换掉：
      - all_indexed_docs   → 解析 `\\doc` 指令时用（判断第一个词是不是文档名）
      - match_indexed_docs → `\\doc -d` 用（按名找到要删的记录）
      - resolve_scope      → `\\doc 文件名 问题` 用（把文件名换成检索范围 source）

    :param monkeypatch: pytest 的替换工具
    :param docs: 假的已导入文档列表
    """
    def _all() -> list[dict]:
        """返回这批假文档。"""
        return list(docs)

    def _by_name(items: list[str]) -> list[dict]:
        """按文件名匹配（大小写不敏感），返回命中的文档记录。"""
        out: list[dict] = []
        for item in items:
            text = (item or "").strip()
            hit = next((d for d in docs if d["name"].lower() == text.lower()), None)
            if hit and hit not in out:
                out.append(hit)
        return out

    def _match(scope: list[str]) -> tuple[list[dict], list[str]]:
        """假的 match_indexed_docs：命中的记录 + 没匹配上的条目。"""
        matched = _by_name(scope)
        missing = [s for s in scope if not any(d["name"].lower() == s.strip().lower() for d in matched)]
        return sorted(matched, key=lambda d: d["source"]), missing

    def _resolve(scope: list[str]) -> tuple[list[str], list[str]]:
        """假的 resolve_scope：把命中的文件名换成 source 列表。"""
        matched, missing = _match(scope)
        return [d["source"] for d in matched], missing

    monkeypatch.setattr(chat_controller, "all_indexed_docs", _all)
    monkeypatch.setattr(chat_controller, "match_indexed_docs", _match)
    monkeypatch.setattr(chat_controller, "resolve_scope", _resolve)


@pytest.fixture()
def session_id() -> str:
    """给每个用例一个独立的会话 id，避免用例之间互相看到对方的对话记录。

    用例结束后落下的数据库记录由 tests/conftest.py 的 _purge_new_chat_records 统一清理。
    """
    return "t" + uuid.uuid4().hex[:12]


def _use_scripted_agent(monkeypatch: pytest.MonkeyPatch, replies: list[AIMessage]) -> InMemorySaver:
    """把控制器里的 Agent 换成"按剧本回复"的假 Agent，并去掉模拟思考的随机等待。

    :param monkeypatch: pytest 的替换工具
    :param replies: 假模型依次给出的回复
    :return: 这次替换用的 checkpointer（用例里可直接操作它）
    """
    saver = InMemorySaver()
    script = _ScriptedModel(responses=replies)
    monkeypatch.setattr(chat_controller, "agent", create_agent(script, tools=TOOLS, checkpointer=saver))
    monkeypatch.setattr(chat_controller, "checkpointer", saver)
    monkeypatch.setattr(chat_controller.random, "uniform", lambda a, b: 0.0)
    return saver


# =========================================================================== #
# 1. 对话记录落库
# =========================================================================== #
def test_turn_is_persisted(monkeypatch: pytest.MonkeyPatch, session_id: str) -> None:
    """一轮普通对话结束后：会话出现在「最近会话」里，提问与回答各落一条，结束原因为 done。"""
    _use_scripted_agent(monkeypatch, [AIMessage(content="这是回答")])

    events = _parse_sse(client.post(
        "/api/chat/stream", json={"message": "帮我看看这份文档", "session_id": session_id},
    ).text)
    assert _first(events, "done")["answer"] == "这是回答"

    sessions = client.get("/api/chat/sessions", params={"limit": 50}).json()["sessions"]
    mine = next((s for s in sessions if s["session_id"] == session_id), None)
    assert mine is not None, sessions
    # 标题取用户第一句提问，条数 = 提问 + 回答
    assert mine["title"] == "帮我看看这份文档" and mine["message_count"] == 2

    messages = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "帮我看看这份文档"
    assert messages[1]["content"] == "这是回答"
    assert messages[1]["finish_reason"] == "done" and messages[1]["mode"] == "agent"


def test_pending_confirm_record_is_completed_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session_id: str,
) -> None:
    """停在「等确认」的那一轮，确认跑完后仍然只留一条助手消息（不会变成两条气泡）。"""
    f = tmp_path / "note.md"
    f.write_text("旧内容", encoding="utf-8")
    _use_scripted_agent(monkeypatch, [
        AIMessage(content="", tool_calls=[{
            "name": "write_file",
            "args": {"path": str(f), "content": "新内容", "overwrite": True},
            "id": "call_1",
            "type": "tool_call",
        }]),
        AIMessage(content="已经改好了"),
    ])

    events = _parse_sse(client.post(
        "/api/chat/stream", json={"message": "覆盖 note.md", "session_id": session_id},
    ).text)
    confirm = _first(events, "confirm_required")
    assert confirm is not None, events

    # 停在确认时就已经落了一条 pending_confirm 记录（用户不点确认也不至于整轮消失）
    pending = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert [m["role"] for m in pending] == ["user", "assistant"]
    assert pending[1]["finish_reason"] == "pending_confirm"

    _parse_sse(client.post("/api/chat/resume", json={
        "session_id": session_id, "interrupt_id": confirm["interrupt_id"], "approved": True,
    }).text)

    after = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert [m["role"] for m in after] == ["user", "assistant"]      # 原地补全，没有多出第三条
    assert after[1]["finish_reason"] == "done" and after[1]["content"] == "已经改好了"


def test_running_state_visible_and_history_deletable(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """新建对话只清上下文、不删记录；「删除」接口才真的把会话从列表里去掉了。"""
    _use_scripted_agent(monkeypatch, [AIMessage(content="好的")])
    client.post("/api/chat/stream", json={"message": "第一句", "session_id": session_id})

    # 前端「新建对话」调的是 DELETE /chat/sessions/{id}
    assert client.delete(f"/api/chat/sessions/{session_id}").json()["deleted"] is True
    still_there = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert len(still_there) == 2        # 记录还在

    # 会话列表里的「删除」才是永久删除
    assert client.delete(f"/api/chat/history/sessions/{session_id}").json()["deleted"] is True
    assert client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"] == []


# =========================================================================== #
# 2. 终止
# =========================================================================== #
def test_iter_until_stop_returns_promptly(tmp_path: Path) -> None:
    """终止信号一被 set，包装过的生成器立刻结束，不会等原生成器自然跑完。"""
    import asyncio

    async def _slow_gen():
        """慢慢产出的假事件源：每次产出前等 30ms，一共 100 个。"""
        for i in range(100):
            await asyncio.sleep(0.03)
            yield i

    async def _drain() -> list[int]:
        """消费可终止流，拿到第 3 个事件后下达终止，返回实际拿到的事件。"""
        stop = asyncio.Event()
        got: list[int] = []
        async for value in chat_controller._iter_until_stop(_slow_gen(), stop):
            got.append(value)
            if len(got) == 3:
                stop.set()
        return got

    assert asyncio.run(_drain()) == [0, 1, 2]


def test_stop_endpoint_marks_running_stream() -> None:
    """POST /chat/stop 会把该会话的终止信号 set 掉；没有在跑的流时返回 stopped=False。"""
    sid = "t" + uuid.uuid4().hex[:12]
    assert client.post("/api/chat/stop", json={"session_id": sid}).json()["stopped"] is False

    stop_event = chat_controller._register_run(sid)
    try:
        assert client.post("/api/chat/stop", json={"session_id": sid}).json()["stopped"] is True
        assert stop_event.is_set()
        # 会话状态里也能看到"正在跑"
        assert client.get(f"/api/chat/sessions/{sid}").json()["running"] is True
    finally:
        chat_controller._unregister_run(sid, stop_event)


def test_stop_aborts_running_doc_stream(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """端到端：`\\doc` 正在生成回答时点终止，后台真的停下来，并以 stopped 事件收尾。"""
    fake_model = _EchoModel([f"片段{i} " for i in range(20)])
    monkeypatch.setattr(chat_controller, "_rag_svc", _StubRagService([_hit("D:\\docs\\a.md")]))
    monkeypatch.setattr(chat_controller, "model", fake_model)
    _stub_library(monkeypatch, [_plan_doc(name="a.md")])

    result: dict[str, str] = {}

    def _run_stream() -> None:
        """在后台线程里发起一次 `\\doc` 检索问答（会一直流到被终止为止）。"""
        with TestClient(app) as stream_client:
            result["text"] = stream_client.post("/api/chat/stream", json={
                "message": "\\doc a.md 这个文档讲了什么", "mode": "doc",
                "session_id": session_id,
            }).text

    thread = threading.Thread(target=_run_stream)
    thread.start()
    # 等这条流真正登记进来（_ACTIVE_RUNS 里出现它），再等它吐出几片
    for _ in range(100):
        if chat_controller._ACTIVE_RUNS.get(session_id) is not None:
            break
        time.sleep(0.05)
    time.sleep(0.4)
    assert client.post("/api/chat/stop", json={"session_id": session_id}).json()["stopped"] is True
    thread.join(timeout=15)
    assert not thread.is_alive(), "终止后流没有结束"

    events = _parse_sse(result["text"])
    stopped = _first(events, "stopped")
    assert stopped is not None, events
    assert stopped["reason"] == "user_stop"
    # 关键断言：模型没有把 20 片全吐完，说明是真的被打断了
    assert fake_model.emitted < 20, fake_model.emitted

    messages = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert messages[-1]["finish_reason"] == "stopped"


# =========================================================================== #
# 3. `\doc` 知识库指令
# =========================================================================== #
def test_doc_command_parsing() -> None:
    """指令解析：子命令、带参数、以及"第一个词像文件名但库里没有"的兜底分支。

    这一步只考解析本身，不查库也不发请求；拿全部文档名做匹配的分支在
    test_doc_search_* 与 test_doc_delete_* 里用假文档覆盖。
    """
    parse = chat_controller._parse_doc_command

    assert parse("\\doc").action == "help"
    assert parse("\\doc -h").action == "help"
    assert parse("\\doc -l 需求").action == "list"
    assert parse("\\doc -d plan.md") == chat_controller.DocCommand(action="delete", target="plan.md")
    assert parse("\\doc -i D:\\docs\\a.md").action == "import"
    # 不认识的子命令不能被当成检索问题
    assert parse("\\doc -x 什么鬼").action == "unknown"


def test_doc_help_and_empty_command(monkeypatch: pytest.MonkeyPatch, session_id: str) -> None:
    """`\\doc` 与 `\\doc -h` 直接回用法说明：不调模型、不调工具。"""
    _stub_library(monkeypatch, [])
    fake_model = _EchoModel(["不该被调用"])
    monkeypatch.setattr(chat_controller, "model", fake_model)

    events = _parse_sse(client.post(
        "/api/chat/stream", json={"message": "\\doc", "mode": "doc", "session_id": session_id},
    ).text)
    answer = _first(events, "done")["answer"]
    assert "-l" in answer and "-d" in answer and "-i" in answer
    assert _first(events, "tool_start") is None
    assert fake_model.emitted == 0


def test_doc_list_uses_index_tool(monkeypatch: pytest.MonkeyPatch, session_id: str) -> None:
    """`\\doc -l 关键词`：调 list_indexed_docs 工具，并把它的输出当成回答。"""
    _stub_library(monkeypatch, [_plan_doc()])
    stub_tool = _StubTool("OK: 知识库里共有 1 篇已导入文档：\n[1] plan.md")
    monkeypatch.setattr(chat_controller, "list_indexed_docs", stub_tool)

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc -l 需求", "mode": "doc", "session_id": session_id},
    ).text)

    assert stub_tool.calls == [{"keyword": "需求", "limit": chat_controller._DOC_LIST_LIMIT}]
    assert _first(events, "tool_start")["name"] == "list_indexed_docs"
    # 工具返回的 "OK: " 前缀会被去掉，正文直接当回答
    assert _first(events, "done")["answer"].startswith("知识库里共有 1 篇")


def test_doc_import_uses_index_path_tool(monkeypatch: pytest.MonkeyPatch, session_id: str) -> None:
    """`\\doc -i 路径`：调 index_path 工具（不在控制器里重写导入逻辑）。"""
    _stub_library(monkeypatch, [])
    stub_tool = _StubTool("OK: 成功 1/1 个文件（新建 1）")
    monkeypatch.setattr(chat_controller, "index_path", stub_tool)

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc -i D:\\docs\\a.md", "mode": "doc", "session_id": session_id},
    ).text)

    assert stub_tool.calls == [{"path": "D:\\docs\\a.md"}]
    assert _first(events, "tool_start")["name"] == "index_path"
    assert "新建 1" in _first(events, "done")["answer"]


def test_doc_search_answers_from_hits(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """`\\doc 文件名 问题`：按文件名解析出检索范围，把命中片段交给模型并流式回答。"""
    stub = _StubRagService([_hit("D:\\docs\\plan.md", "风险点一：预算不足")])
    monkeypatch.setattr(chat_controller, "_rag_svc", stub)
    monkeypatch.setattr(chat_controller, "model", _EchoModel(["预算", "不足"], delay=0.0))
    _stub_library(monkeypatch, [_plan_doc()])

    events = _parse_sse(client.post("/api/chat/stream", json={
        "message": "\\doc plan.md 有哪些风险", "mode": "doc", "session_id": session_id,
    }).text)

    # 文件名被识别成检索范围，问题只剩后半句
    assert stub.calls[0]["query"] == "有哪些风险"
    assert stub.calls[0]["sources"] == ["D:\\docs\\plan.md"]
    # 检索过程按一次工具调用展示，回答由 token 拼出，最后 done
    assert _first(events, "tool_start")["name"] == "rag_search"
    assert _first(events, "tool_end")["output"].startswith("OK:")
    assert _first(events, "done")["answer"] == "预算不足"

    messages = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert messages[1]["mode"] == "doc" and messages[1]["finish_reason"] == "done"


def test_doc_search_with_only_filename(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """只写了文件名、没写问题：用默认问题去检索，而不是报错。"""
    stub = _StubRagService([_hit("D:\\docs\\plan.md")])
    monkeypatch.setattr(chat_controller, "_rag_svc", stub)
    monkeypatch.setattr(chat_controller, "model", _EchoModel(["概要"], delay=0.0))
    _stub_library(monkeypatch, [_plan_doc()])

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc plan.md", "mode": "doc", "session_id": session_id},
    ).text)

    assert stub.calls[0]["query"] == chat_controller._DOC_DEFAULT_QUERY
    assert _first(events, "done")["answer"] == "概要"


def test_doc_search_reports_unknown_filename(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """文件名写错（库里没有）时给出明确提示，而不是拿整句话去全库硬搜。"""
    stub = _StubRagService([])
    monkeypatch.setattr(chat_controller, "_rag_svc", stub)
    monkeypatch.setattr(chat_controller, "model", _EchoModel(["不该被调用"]))
    _stub_library(monkeypatch, [_plan_doc()])

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc 不存在的文件.md 有哪些风险", "mode": "doc", "session_id": session_id},
    ).text)

    answer = _first(events, "done")["answer"]
    assert "没有找到" in answer and "plan.md" in answer
    assert stub.calls == []          # 压根没去检索


def test_doc_search_reports_empty_result(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """全库检索没命中时如实告知，并且不再花一次模型调用。"""
    fake_model = _EchoModel(["不该被调用"])
    monkeypatch.setattr(chat_controller, "_rag_svc", _StubRagService([]))
    monkeypatch.setattr(chat_controller, "model", fake_model)
    _stub_library(monkeypatch, [])

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc 查一个不存在的话题", "mode": "doc", "session_id": session_id},
    ).text)
    assert "未检索到" in _first(events, "done")["answer"]
    assert fake_model.emitted == 0


def test_doc_delete_needs_confirm_then_approve(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """`\\doc -d 文件名`：先弹确认（此时一篇都没删），同意后才真正删除并落库为 done。"""
    svc = _StubRagService([])
    monkeypatch.setattr(chat_controller, "_rag_svc", svc)
    _stub_library(monkeypatch, [_plan_doc(), _plan_doc(doc_id=2, name="other.md")])

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc -d plan.md", "mode": "doc", "session_id": session_id},
    ).text)
    confirm = _first(events, "confirm_required")
    assert confirm is not None, events
    assert confirm["tool"] == "delete_index" and "plan.md" in confirm["message"]
    assert _first(events, "done") is None      # 等人确认时不该发 done
    assert svc.deleted == []                   # 确认前绝不删

    messages = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert messages[1]["finish_reason"] == "pending_confirm"

    resumed = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": session_id, "interrupt_id": confirm["interrupt_id"], "approved": True,
    }).text)
    assert svc.deleted == [[1]]
    assert _first(resumed, "tool_end")["output"].startswith("OK:")
    assert "已从知识库删除 1 篇" in _first(resumed, "done")["answer"]

    # 就地补全那条 pending_confirm，不会变成两条助手消息
    after = client.get(f"/api/chat/history/sessions/{session_id}").json()["messages"]
    assert [m["role"] for m in after] == ["user", "assistant"]
    assert after[1]["finish_reason"] == "done"


def test_doc_delete_rejected_keeps_documents(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """用户在确认弹窗里点拒绝：一篇都不删，回答里说明保持不变。"""
    svc = _StubRagService([])
    monkeypatch.setattr(chat_controller, "_rag_svc", svc)
    _stub_library(monkeypatch, [_plan_doc()])

    confirm = _first(_parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc -d plan.md", "mode": "doc", "session_id": session_id},
    ).text), "confirm_required")

    resumed = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": session_id, "interrupt_id": confirm["interrupt_id"], "approved": False,
    }).text)
    assert svc.deleted == []
    assert "已取消删除" in _first(resumed, "done")["answer"]
    assert _first(resumed, "tool_end")["output"].startswith("FAIL:")


def test_doc_delete_unknown_filename(
    monkeypatch: pytest.MonkeyPatch, session_id: str,
) -> None:
    """要删的文件名在库里没有：直接说明并列出可用的文档名，不弹确认框。"""
    _stub_library(monkeypatch, [_plan_doc()])

    events = _parse_sse(client.post(
        "/api/chat/stream",
        json={"message": "\\doc -d nope.md", "mode": "doc", "session_id": session_id},
    ).text)
    assert _first(events, "confirm_required") is None
    answer = _first(events, "done")["answer"]
    assert "没有与" in answer and "plan.md" in answer
