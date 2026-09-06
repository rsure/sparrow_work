# backend/tests/test_subagent_dispatch.py
"""
ARCH-7 调用方的测试：dispatch_subagent 工具本身的行为。

为什么需要这一组测试：
    ARCH-7 在 M6 早先只做了"能力"（SUB 作用域、只读工具集、写操作红线），
    但没有任何调用方——等于一条没人走的路，写得再对也验证不了。
    这里补的是**调用方**：主对话通过 `dispatch_subagent` 派活、
    子 agent 在 SUB 作用域里跑、把结论交回来。

测试用假的图（不进真实模型、不发网络请求），只验证：
    - 开关关闭时拒绝执行，并给出可操作的提示；
    - 开关打开时真的以 SUB 作用域、独立会话 id 去跑；
    - 任务为空/超长、并发超限、步数超限、超时、异常，六种失败各自给出不同文案；
    - 工具只在开关打开时挂进主对话，且**永远不会**挂进子 agent 自己（否则会自我复制）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：asyncio 跑"卡住的子 agent"来验证超时分支
import asyncio

# 第三方：pytest 的断言与 fixture
import pytest

# 项目内：设置注册表（开关与并发上限都从设置里读）
from app.services import settings_registry
# 项目内：子 agent 派发工具本体
from app.tools import subagent_tool
# 项目内：策略表（确认它登记成只读）
from app.tools.policy import POLICIES, Kind
# 项目内：ContextVar 读入口（验证子 agent 确实跑在 SUB 作用域）
from app.tools.session import current_scope, current_session_id
# 项目内：会话 id 的初始值（工具要靠它派生子会话 id）
from app.tools.session import set_session_id


class _FakeMessage:
    """假的消息对象：只需要 content 一个属性，够 _collect_answer 用。"""

    def __init__(self, content: object) -> None:
        # 消息正文：字符串或片段列表，两种形态都要能被 _collect_answer 处理
        self.content = content


class _FakeGraph:
    """假的 Agent 图：记录被调用时的上下文，并按需返回结论或抛错。

    为什么不用真实的 create_agent 图：真实图要模型、要网络、要几秒钟，
    而本组测试要验证的是"工具怎么使用这张图"，不是模型会不会说话。
    """

    def __init__(
        self,
        content: object = "子任务结论：共 3 处 TODO",
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        # 要返回给工具的结论文本（或片段列表）
        self.content = content
        # 要抛出的异常（模拟步数超限等）
        self.error = error
        # 故意拖多久（验证超时分支）
        self.delay = delay
        # 被调用时记录的现场：作用域、会话 id、thread_id、配置里的步数上限
        self.captured: dict[str, object] = {}

    async def ainvoke(self, payload: dict, config: dict | None = None) -> dict:
        """模拟 graph.ainvoke：记录现场 → 可选延时/抛错 → 返回最后一条消息。"""
        self.captured["scope"] = current_scope()
        self.captured["session_id"] = current_session_id()
        self.captured["config"] = config or {}
        self.captured["payload"] = payload
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {"messages": [_FakeMessage(self.content)]}


@pytest.fixture
def enabled_subagent():
    """打开子 agent 开关，用例结束后把设置恢复原样并把并发计数归零。

    为什么要恢复：这些开关落在真实 app.db 里，不恢复会污染后续用例
    （例如"默认关闭"的断言会莫名其妙失败）。
    """
    settings_registry.register_defs(settings_registry.BUILTIN_DEFS)
    old_enabled = bool(settings_registry.get_setting("agent.subagent_enabled"))
    old_parallel = int(settings_registry.get_setting("agent.subagent_max_parallel"))
    settings_registry.put_settings(
        {"agent.subagent_enabled": True, "agent.subagent_max_parallel": 2}
    )
    subagent_tool.reset_for_test()
    try:
        yield
    finally:
        settings_registry.put_settings(
            {"agent.subagent_enabled": old_enabled, "agent.subagent_max_parallel": old_parallel}
        )
        subagent_tool.reset_for_test()


@pytest.fixture
def fake_graph(monkeypatch):
    """把 llm.state.get_agent 换成返回假图的桩，并默认把会话 id 设成 s1。

    :return: 一个函数：`install(**kwargs)` 建好假图并装进去，返回该假图
    """
    # 延迟导入：避免测试模块导入期就把 llm 层拉起来
    from app.llm import state as llm_state

    set_session_id("s1")

    def install(**kwargs: object) -> _FakeGraph:
        """装上假图，返回它，方便用例随后检查 captured。"""
        graph = _FakeGraph(**kwargs)  # type: ignore[arg-type]
        monkeypatch.setattr(llm_state, "get_agent", lambda *a, **k: graph)
        return graph

    return install


def _call(task: str, context: str = "") -> str:
    """按模型的方式调用工具（走 @tool 的包装层，与真实调用路径一致）。

    为什么不直接 `dispatch_subagent(task)`：它是 LangChain 的 StructuredTool，
    位置参数调用会抛 TypeError；而 `.func(...)` 会绕过策略与输出契约那一层。
    `.invoke({...})` 才是模型真正走的路。
    """
    return str(subagent_tool.dispatch_subagent.invoke({"task": task, "context": context}))


def test_disabled_reports_where_to_enable(monkeypatch):
    """开关关闭时拒绝执行，并告诉用户去哪儿打开（而不是含糊地说"不可用"）。"""
    monkeypatch.setattr(subagent_tool, "enabled", lambda: False)

    result = _call("帮我汇总这个目录的 TODO")

    assert result.startswith("FAIL:")
    assert "启用子 agent" in result


def test_returns_conclusion_and_runs_in_sub_scope(enabled_subagent, fake_graph):
    """开关打开、图正常返回时：给出 OK + 结论，且子 agent 跑在 SUB 作用域/独立会话下。"""
    graph = fake_graph(content="结论：这 3 处 TODO 都在 a.py 里")

    result = _call("汇总 a.py 里的 TODO")

    assert result.startswith("OK:")
    assert "这 3 处 TODO" in result
    # 作用域必须是 sub：否则子 agent 内部的写盘/执行不会有红线保护
    assert graph.captured["scope"] == "sub"
    # 会话 id 必须是"主会话 + #sub-*"，否则子 agent 的工具会去抽主对话的插话队列
    assert str(graph.captured["session_id"]).startswith("s1#sub-")
    # thread_id 与 configurable 要对上，让子 agent 用独立检查点
    config = graph.captured["config"]
    assert config["configurable"]["thread_id"] == graph.captured["session_id"]


def test_context_is_appended_to_the_prompt(enabled_subagent, fake_graph):
    """context 作为背景拼进提示词（子 agent 看不到主对话历史，只能靠它）。"""
    graph = fake_graph()

    _call("汇总 TODO", context="用户只关心 backend 目录")

    payload = graph.captured["payload"]
    text = payload["messages"][0][1]
    assert "用户只关心 backend 目录" in text
    assert "汇总 TODO" in text


def test_empty_task_is_rejected(enabled_subagent, fake_graph):
    """空任务直接拒：派一个空活给子 agent 只会白烧一轮 token。"""
    fake_graph()

    result = _call("   ")

    assert result.startswith("FAIL:")
    assert "不能为空" in result


def test_too_long_task_is_rejected(enabled_subagent, fake_graph):
    """任务超长直接拒（提示拆小，而不是悄悄截断）。"""
    fake_graph()

    result = _call("读" * (subagent_tool._MAX_TASK_CHARS + 1))

    assert result.startswith("FAIL:")
    assert "太长" in result


def test_parallel_cap_rejects_the_extra_dispatch(enabled_subagent, fake_graph, monkeypatch):
    """并发已满时拒绝派发，并给出"自己串行做"的替代方案。"""
    monkeypatch.setattr(subagent_tool, "max_parallel", lambda: 1)
    # 手动占满槽位：不需要真的跑一个慢子 agent
    subagent_tool._ACTIVE = 1
    fake_graph()

    result = _call("汇总 TODO")

    assert result.startswith("FAIL:")
    assert "上限" in result
    # 失败路径不能漏还槽位（否则一次失败就把并发永久占死）
    assert subagent_tool.active_count() == 1


def test_slot_is_released_after_a_successful_run(enabled_subagent, fake_graph):
    """成功跑完后槽位要还回来。"""
    fake_graph()

    _call("汇总 TODO")

    assert subagent_tool.active_count() == 0


def test_step_limit_is_reported_with_split_advice(enabled_subagent, fake_graph):
    """步数超限（GraphRecursionError）单独识别：让模型"拆小"，而不是原样抛错。"""
    # 延迟导入：只在需要造这个异常时才引它
    from langgraph.errors import GraphRecursionError

    fake_graph(error=GraphRecursionError("Recursion limit of 10 reached"))

    result = _call("把整个仓库的 TODO 汇总")

    assert result.startswith("FAIL:")
    assert "步数" in result
    assert "拆" in result


def test_timeout_is_reported(enabled_subagent, fake_graph, monkeypatch):
    """超时单独识别：文案里要给出时限，用户才知道该等多久是"不正常"。"""
    monkeypatch.setattr(subagent_tool, "_SUB_TIMEOUT_SECONDS", 0.05)
    fake_graph(delay=0.5)

    result = _call("慢慢读整个仓库")

    assert result.startswith("FAIL:")
    assert "秒" in result
    assert "拆" in result
    # 超时也必须还槽位
    assert subagent_tool.active_count() == 0


def test_unexpected_error_is_wrapped(enabled_subagent, fake_graph):
    """其它异常兜住成 FAIL 文案：子 agent 崩了不能让主对话整轮报错。"""
    fake_graph(error=RuntimeError("模型供应商返回 500"))

    result = _call("汇总 TODO")

    assert result.startswith("FAIL:")
    assert "模型供应商返回 500" in result


def test_list_content_blocks_are_collected(enabled_subagent, fake_graph):
    """结论可能是片段列表（多模态模型常见），要拼成纯文本交给主对话。"""
    fake_graph(content=[{"type": "text", "text": "结论 A"}, {"type": "text", "text": "；结论 B"}])

    result = _call("汇总 TODO")

    assert "结论 A；结论 B" in result


def test_empty_answer_is_reported(enabled_subagent, fake_graph):
    """子 agent 没写出结论时明确失败，免得主对话以为"它说完了"。"""
    fake_graph(content="")

    result = _call("汇总 TODO")

    assert result.startswith("FAIL:")
    assert "没有写出任何结论" in result


def test_policy_registered_as_read_only():
    """策略必须是 READ：派发本身不动磁盘，真正的风险在子 agent 内部工具上。"""
    policy = POLICIES["dispatch_subagent"]

    assert policy.kind is Kind.READ
    # 不设 path_args：它没有路径参数，路径校验发生在子 agent 自己的工具里
    assert policy.path_args == ()


def test_tool_is_mounted_only_when_enabled(enabled_subagent):
    """开关决定主对话工具集里有没有它；关掉后必须消失（否则等于开关是装饰）。"""
    # 延迟导入：rag_agent 会拉起全部工具模块，放在顶部会拖慢整个测试收集
    from app.agents import rag_agent
    from app.llm import state as llm_state

    def main_tool_names() -> set[str]:
        """取主对话工具集里的工具名（build_tools 返回的是工具对象，不能直接比字符串）。"""
        return {getattr(item, "name", "") for item in rag_agent.build_tools("main")}

    llm_state.invalidate()
    assert "dispatch_subagent" in main_tool_names()

    settings_registry.put_settings({"agent.subagent_enabled": False})
    llm_state.invalidate()
    assert "dispatch_subagent" not in main_tool_names()


def test_sub_scope_never_gets_the_dispatch_tool(enabled_subagent):
    """子 agent 自己拿不到派发工具：否则会无限套娃，一次派活变成一场爆炸。"""
    from app.agents import rag_agent

    names = {getattr(tool, "name", "") for tool in rag_agent.build_tools("sub")}

    assert "dispatch_subagent" not in names
    # 顺带守住"子作用域只读"这条不变量：写/执行类工具一个都不该出现
    for name in ("write_file", "edit_file", "run_command", "file_ops", "web_search"):
        assert name not in names
