"""人工确认（human-in-the-loop）端到端自测：/chat/stream → confirm_required → /chat/resume → done。

不调用真实 DeepSeek：用一个"按剧本回复"的假模型替换 chat_controller.agent，
剧本是「第一次回复：调用 write_file 覆盖文件；第二次回复：一句总结」。
工具、checkpointer、interrupt、控制器、SSE 编码全部是真实代码，验证的是整条链路。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 这类新语法
from __future__ import annotations

# 解析 SSE 帧里的 data JSON
import json
# 构造测试文件的路径对象
from pathlib import Path

# 测试框架：fixture 声明 + monkeypatch 替换模块里的 agent / 随机等待
import pytest
# 测试客户端：在进程内直接调用 FastAPI 应用，不占用真实端口
from fastapi.testclient import TestClient
# LangChain 1.x 的 Agent 构造器：用假模型 + 真实工具组装一个测试用 Agent
from langchain.agents import create_agent
# LangChain 内置假模型：按 responses 列表依次返回预设消息，不发网络请求
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
# AIMessage：构造"模型发起工具调用""模型给出最终回答"两条剧本消息
from langchain_core.messages import AIMessage
# LangGraph 内存检查点：测试 Agent 也要有它，interrupt 才能暂停与恢复
from langgraph.checkpoint.memory import InMemorySaver

# 被测对象：控制器模块（替换其中的 agent / checkpointer / random）
from app.controllers import chat_controller
# 被测对象：项目根应用实例
from app.main import app
# 真实的全部工具列表（与线上 Agent 完全一致）
from app.agents.rag_agent import TOOLS

# 复用同一个测试客户端
client = TestClient(app)

# 剧本最后一步模型的回答文本，用来断言 done 事件
FINAL_ANSWER = "处理完毕"


class _ScriptedModel(FakeMessagesListChatModel):
    """按剧本回复的假模型。create_agent 会调用 bind_tools 绑定工具，假模型不需要，直接返回自身。"""

    def bind_tools(self, tools, **kwargs):
        """忽略工具绑定，返回自身，保证 create_agent 能正常组装。"""
        return self


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


@pytest.fixture()
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """准备一个已存在的文件，并把控制器里的 Agent 换成"覆盖这个文件"的剧本 Agent。"""
    f = tmp_path / "note.md"
    f.write_text("旧内容", encoding="utf-8")

    script = _ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "write_file",
            "args": {"path": str(f), "content": "新内容", "overwrite": True},
            "id": "call_1",
            "type": "tool_call",
        }]),
        AIMessage(content=FINAL_ANSWER),
    ])
    saver = InMemorySaver()
    monkeypatch.setattr(chat_controller, "agent", create_agent(script, tools=TOOLS, checkpointer=saver))
    monkeypatch.setattr(chat_controller, "checkpointer", saver)
    # 去掉"模拟思考"的 1~3 秒随机等待，让测试秒级跑完
    monkeypatch.setattr(chat_controller.random, "uniform", lambda a, b: 0.0)
    return f


def _start(message: str = "把 note.md 覆盖成新内容") -> dict:
    """发起一轮提问，断言停在 confirm_required，返回该事件数据。"""
    events = _parse_sse(client.post("/api/chat/stream", json={"message": message}).text)
    confirm = _first(events, "confirm_required")
    assert confirm is not None, events
    assert _first(events, "done") is None              # 暂停时不应该发 done
    return confirm


def test_confirm_then_approve(target: Path) -> None:
    """用户同意：恢复后文件被覆盖、留下备份，done 里带完整回答与确认记录。"""
    confirm = _start()
    assert confirm["tool"] == "write_file" and confirm["args"]["path"] == str(target.resolve())
    assert target.read_text(encoding="utf-8") == "旧内容"   # 确认前绝不落盘

    events = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": confirm["session_id"], "interrupt_id": confirm["interrupt_id"], "approved": True,
    }).text)
    done = _first(events, "done")
    assert done is not None, events
    assert target.read_text(encoding="utf-8") == "新内容"
    assert len(list(target.parent.glob("note.md.*.bak"))) == 1
    assert done["answer"] == FINAL_ANSWER
    assert {"name": "write_file", "confirm": "approved"}.items() <= done["tool_calls"][0].items()
    assert done["tool_calls"][1]["output"].startswith("OK:")


def test_confirm_then_reject(target: Path) -> None:
    """用户拒绝：文件不变、无备份，工具结果是 FAIL，模型照常收尾。"""
    confirm = _start()
    events = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": confirm["session_id"], "interrupt_id": confirm["interrupt_id"], "approved": False,
    }).text)
    done = _first(events, "done")
    assert done is not None, events
    assert target.read_text(encoding="utf-8") == "旧内容"
    assert not list(target.parent.glob("*.bak"))
    assert "拒绝" in done["tool_calls"][1]["output"]


def test_resume_invalid_requests(target: Path) -> None:
    """错误的中断 id、过期会话都返回 error；待确认期间发新问题也被拦下。"""
    confirm = _start()
    sid = confirm["session_id"]

    wrong = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": sid, "interrupt_id": "not-this-one", "approved": True,
    }).text)
    assert "已失效" in _first(wrong, "error")["message"]

    gone = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": "no-such-session", "interrupt_id": confirm["interrupt_id"], "approved": True,
    }).text)
    assert "过期" in _first(gone, "error")["message"]

    busy = _parse_sse(client.post("/api/chat/stream", json={"message": "再问一句", "session_id": sid}).text)
    assert "等待你确认" in _first(busy, "error")["message"]

    # 清空会话后，checkpointer 里的暂停现场也一起清掉，这个确认再也不能恢复
    client.delete(f"/api/chat/sessions/{sid}")
    stale = _parse_sse(client.post("/api/chat/resume", json={
        "session_id": sid, "interrupt_id": confirm["interrupt_id"], "approved": True,
    }).text)
    assert _first(stale, "error") is not None
    assert target.read_text(encoding="utf-8") == "旧内容"


def test_recursion_limit_is_reported_and_thread_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """步数耗尽时返回可读的 error，并清掉残缺的图现场。

    剧本让模型每次都调用 list_dir、永远不收敛，用很小的 recursion_limit 快速触发。
    这类残缺现场如果留着，下一轮模型接口会因为"有 tool_calls 却没有 ToolMessage"而报错。
    """
    # 每次给一个不同的 tool_call id：如果循环复用同一个 id，工具结果已经存在，
    # create_agent 会认为"没有待执行的工具调用"而走别的分支，就触发不到 recursion_limit 了
    script = _ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "list_dir",
            "args": {"path": str(tmp_path)},
            "id": f"call_loop_{i}",
            "type": "tool_call",
        }])
        for i in range(6)
    ])
    saver = InMemorySaver()
    monkeypatch.setattr(chat_controller, "agent", create_agent(script, tools=TOOLS, checkpointer=saver))
    monkeypatch.setattr(chat_controller, "checkpointer", saver)
    # 去掉"模拟思考"的 1~3 秒随机等待
    monkeypatch.setattr(chat_controller.random, "uniform", lambda a, b: 0.0)

    # 每次测试用独立会话 id，避免和前面用例的内存会话互相影响
    sid = f"test-recursion-limit-{tmp_path.name}"
    events = _parse_sse(client.post("/api/chat/stream", json={
        "message": "一直循环", "session_id": sid, "max_iterations": 5,
    }).text)

    error = _first(events, "error")
    assert error is not None, events
    # 前端看到的是中文说明，而不是 "Recursion limit of 5 reached..." 这类原始异常文案
    assert "超过上限" in error["message"]
    # 图现场已清理（thread 不存在），下一轮可以靠 SQLite 历史重新补种上下文
    assert saver.get_tuple({"configurable": {"thread_id": sid}}) is None
