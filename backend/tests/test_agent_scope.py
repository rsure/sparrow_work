"""ARCH-7 的回归测试：Agent 作用域隔离（MAIN / SUB）。

本文件只验证"作用域真的改变了什么"，共四件事：
    1. SUB 的工具集是只读子集（且排除了名字像读、实际会写知识库的两个工具）；
    2. MAIN 的工具集与改造前一致（零回归：写盘、执行、联网都还在）；
    3. 裁决层：SUB 的写盘/执行**无论权限模式是什么**都必须逐次确认（红线不可配置）；
    4. 步数上限：SUB 独立且不超过主对话上限。

为什么这些断言值得写：
    作用域隔离是"给模型自主权"与"不给它破坏力"的分界线。这条线一旦被后来的人
    顺手放开（比如"子 agent 也让它写文件吧"），不会有任何报错，只会安静地变危险。
    所以这里断言的是**不存在**（写工具不在 SUB 集合里），而不是"存在"。
"""

# 第三方：pytest 的 monkeypatch 用来替换"弹窗询问用户"的实现（测试里不能真弹窗）
import pytest

# 项目内：工具清单的装配入口（按作用域裁剪）与子 agent 提示词
from app.agents import rag_agent
# 项目内：状态层——作用域枚举与步数上限
from app.llm.state import SUB_MAX_ITERATIONS, AgentScope, scope_max_iterations
# 项目内：安全裁决——策略登记表、裁决函数、作用域常量与等级/类型枚举
from app.tools import policy as policy_mod
from app.tools.policy import (
    SCOPE_MAIN,
    SCOPE_SUB,
    Action,
    Kind,
    Level,
    Policy,
    SessionContext,
    decide,
)

# 子 agent 绝对不该拿到的工具名（写盘 / 执行 / 文件管理 / 联网 / 知识库写入）
FORBIDDEN_IN_SUB = frozenset({
    "write_file", "edit_file", "file_ops", "index_path", "delete_index",
    "run_command", "web_search", "web_fetch", "http_request",
})


def test_sub_scope_tools_are_a_read_only_subset() -> None:
    """SUB 作用域拿到的工具必须全部是只读的，且不含"名字像读、实际写库"的两个工具。"""
    sub_names = {tool.name for tool in rag_agent.build_tools(SCOPE_SUB)}

    # 一个都不许出现：这是红线，不是"尽量"
    assert sub_names & FORBIDDEN_IN_SUB == set()
    # 必须有基本的读能力，否则子 agent 什么也做不了
    assert {"read_file", "list_dir", "rag_search"} <= sub_names
    # index_path / delete_index 在 READ_TOOLS 里，但会写知识库，必须被排除
    assert "index_path" not in sub_names
    assert "delete_index" not in sub_names


def test_main_scope_keeps_every_tool_the_project_had() -> None:
    """MAIN 作用域零回归：改造前能用的写盘 / 执行 / 联网工具必须原样还在。"""
    main_names = {tool.name for tool in rag_agent.build_tools(SCOPE_MAIN)}

    assert FORBIDDEN_IN_SUB <= main_names
    # 默认参数就是 MAIN，调用方不传 scope 时行为不变
    assert main_names == {tool.name for tool in rag_agent.build_tools()}


def test_sub_scope_upgrades_allow_to_ask_for_write_actions() -> None:
    """裁决层：SUB 遇到"本可免确认"的写操作时，等级必须被抬到 ASK。

    这里用一个临时登记的探针策略（kind=WRITE 且 default_level=ALLOW）——
    现有内置写工具都已经是 ASK 了，只有这种组合才能验证"升级"这一步真的存在。
    """
    probe = Policy(tool="__scope_probe__", kind=Kind.WRITE, default_level=Level.ALLOW)
    policy_mod.register(probe)
    action = Action(tool=probe.tool, kind=Kind.WRITE, target="probe.txt")
    try:
        # MAIN：显式 ALLOW 就是 ALLOW（说明升级只对 SUB 生效）
        assert decide(probe.tool, action, SessionContext(scope=SCOPE_MAIN)).level is Level.ALLOW
        # SUB：同样一条策略必须变成 ASK
        assert decide(probe.tool, action, SessionContext(scope=SCOPE_SUB)).level is Level.ASK
    finally:
        # 探针策略不能留在全局注册表里（否则会影响"全部工具都已登记"这类自检的语义）
        policy_mod.POLICIES.pop(probe.tool, None)


def test_sub_scope_never_skips_the_dialog_even_in_allow_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUB 的写操作在 permission_mode="allow" 下也必须弹窗；MAIN 同模式则直接放行。

    这是"红线不可配置"的唯一可执行证据：把弹窗替换成"总是拒绝"，
    再看 _resolve_ask 的返回值——SUB 返回 False（走了弹窗），MAIN 返回 True（没走弹窗）。
    """
    # 记录弹窗被调用的次数；返回"拒绝"，这样返回值就能区分"弹过窗"与"被放行"
    calls: list[str] = []

    def fake_ask(tool: str, title: str, reason: str, preview: object, allow_remember: bool = True) -> tuple[bool, bool]:
        """替身弹窗：只记次数并拒绝，不碰任何真实 UI。"""
        calls.append(tool)
        return False, False

    # 项目内：_resolve_ask 在函数内部导入这个名字，所以要替换模块属性而不是 policy 里的名字
    from app.tools import tool_utils

    monkeypatch.setattr(tool_utils, "ask_user_decide", fake_ask)

    action = Action(tool="write_file", kind=Kind.WRITE, target="a.txt")
    decision = decide("write_file", action, SessionContext(scope=SCOPE_SUB))

    sub_session = SessionContext(scope=SCOPE_SUB, permission_mode="allow")
    assert policy_mod._resolve_ask("write_file", action, decision, sub_session) is False
    assert calls == ["write_file"]

    # MAIN 在 allow 模式下不弹窗：这是既有行为，不能被 ARCH-7 改掉
    main_session = SessionContext(scope=SCOPE_MAIN, permission_mode="allow")
    assert policy_mod._resolve_ask("write_file", action, decision, main_session) is True
    assert calls == ["write_file"]


def test_sub_scope_has_its_own_iteration_limit() -> None:
    """步数上限：SUB 独立于主对话，且永远不会超过主对话的上限。"""
    main_limit = scope_max_iterations()
    sub_limit = scope_max_iterations(AgentScope.SUB)

    assert main_limit >= 1
    assert SUB_MAX_ITERATIONS >= 1
    assert sub_limit == min(main_limit, SUB_MAX_ITERATIONS)
    # MAIN 不受 SUB 的常量影响（否则调大 SUB_MAX_ITERATIONS 会顺带改主对话行为）
    assert scope_max_iterations(AgentScope.MAIN) == main_limit


def test_sub_scope_prompt_tells_the_model_to_deliver_conclusions() -> None:
    """SUB 的系统提示词多一段约束；MAIN 的提示词里没有这段。"""
    sub_prompt = rag_agent.build_system_prompt(SCOPE_SUB)
    main_prompt = rag_agent.build_system_prompt(SCOPE_MAIN)

    assert rag_agent.SUB_SCOPE_PROMPT in sub_prompt
    assert rag_agent.SUB_SCOPE_PROMPT not in main_prompt
    # 约束里必须明确"只读"和"交回结论"两件事，否则模型会尝试写盘再卡在确认上
    assert "只读" in rag_agent.SUB_SCOPE_PROMPT
    assert "结论" in rag_agent.SUB_SCOPE_PROMPT
