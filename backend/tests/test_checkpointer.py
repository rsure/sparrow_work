"""ARCH-4 会话持久化的回归测试（"重启后还能接着聊"）。

背景：`agents/rag_agent.py` 用的是 `AsyncSqliteSaver(aiosqlite.connect(...))`，
对话状态按 thread_id 落在 app.db 里。这个行为之前**没有任何测试**，
一旦有人把 checkpointer 换成 InMemorySaver、或者换回同步实现/连接方式，
重启丢对话（以及"异步接口直接报 NotImplementedError"）的问题只会在用户那里才被发现。

这里用临时库复现"进程重启"：写入状态 → 关闭连接 → 用**新的** AsyncSqliteSaver 实例读回。
新实例能读到，就等价于"后端重启后还能恢复现场"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：在同步用例里跑协程（本项目没装 pytest-asyncio）
import asyncio
# 标准库：临时目录，避免污染开发库
from pathlib import Path

# 第三方：aiosqlite 提供异步 SQLite 连接（AsyncSqliteSaver 必须用它）
import aiosqlite
# LangGraph：最小状态图 + **异步** SQLite 检查点（与生产代码保持一致）
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import MessagesState, StateGraph

# LangChain：消息类型
from langchain_core.messages import AIMessage, HumanMessage


def _build_graph(saver: AsyncSqliteSaver):
    """构造一个最小可用图：收到什么就回一句 "pong"，用于产生可恢复的状态。

    :param saver: 检查点实现
    :return: 编译后的图
    """
    def echo(_state: MessagesState) -> dict:
        """固定回一句 pong（不依赖任何外部服务，测试才稳定）。"""
        return {"messages": [AIMessage(content="pong")]}

    graph = StateGraph(MessagesState)
    graph.add_node("echo", echo)
    graph.set_entry_point("echo")
    return graph.compile(checkpointer=saver)


async def _write_turn(db_path: Path, config: dict) -> None:
    """模拟第一次"进程"：用一条新连接写入一轮对话，然后关闭连接。

    :param db_path: 临时数据库文件
    :param config: 含 thread_id 的 LangGraph 配置
    """
    async with aiosqlite.connect(str(db_path)) as conn:
        saver = AsyncSqliteSaver(conn)
        await _build_graph(saver).ainvoke(
            {"messages": [HumanMessage(content="ping")]},
            config,
        )


async def _read_messages(db_path: Path, config: dict) -> list:
    """模拟第二次"进程"：用另一条新连接读回该 thread 的消息列表。

    :param db_path: 临时数据库文件
    :param config: 含 thread_id 的 LangGraph 配置
    :return: 恢复出来的消息列表
    """
    async with aiosqlite.connect(str(db_path)) as conn:
        saver = AsyncSqliteSaver(conn)
        state = await _build_graph(saver).aget_state(config)
    return state.values.get("messages", [])


def test_state_survives_new_saver_instance(tmp_path: Path) -> None:
    """写入后换一个 checkpointer 实例（等价于进程重启）仍能读回完整状态。"""
    db_path = tmp_path / "checkpoints.db"
    config = {"configurable": {"thread_id": "thread-restart"}}

    # ---- 第一次"进程"：写一轮对话 ----
    asyncio.run(_write_turn(db_path, config))

    # ---- 第二次"进程"：同一条 thread 应能读到上一轮的两条消息 ----
    messages = asyncio.run(_read_messages(db_path, config))

    assert len(messages) == 2, f"重启后应保留提问与回答两条消息，实际 {len(messages)} 条"
    assert messages[0].content == "ping"
    assert messages[1].content == "pong"


def test_unknown_thread_starts_empty(tmp_path: Path) -> None:
    """没写过的 thread_id 读到空状态（不能因为"库里有别的会话"就串味）。"""
    db_path = tmp_path / "checkpoints.db"
    messages = asyncio.run(_read_messages(
        db_path, {"configurable": {"thread_id": "never-used"}},
    ))
    assert messages == []
