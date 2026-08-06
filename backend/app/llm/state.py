# app/llm/state.py
"""
运行时模型/Agent 状态：按当前设置构建并缓存实例，设置一变就自动失效重建。

为什么要缓存（对应 doc/21 ARCH-1 §1.4 的取舍）：
    create_agent() 编译出的 LangGraph 图有构建开销，每轮请求都重建会把首字时间拖长；
    但也不能做成模块级永久单例——那样用户在设置页换了模型也不生效。

折中：缓存「当前 provider+model+参数」对应的实例，并在设置变更事件到达时失效。
事件驱动而非轮询（见 doc/27 §2 的订阅机制），因此设置页保存后下一次对话即用新模型。

AgentScope（ARCH-7）：
    MAIN＝主对话，全量工具 + 完整权限模式，与改造前行为完全一致（零回归）。
    SUB＝子 agent，只拿只读工具（见 `agents/rag_agent.SUB_TOOLS`）、
    SUB＝子 agent，只拿只读工具（见 `agents/rag_agent.SUB_TOOLS`）、
    走"写操作强制逐次确认"的红线（见 `tools/policy.SCOPE_SUB`）；
    调用方是 `tools/subagent_tool.dispatch_subagent`（ARCH-7 收尾时接上），
    由设置 `agent.subagent_enabled` 控制是否挂进主对话工具集，默认关闭。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：枚举区分主对话 agent 与子 agent
from enum import Enum
# 标准库：线程锁，保证并发请求下缓存重建不会重复构建出多份实例
from threading import Lock
# 标准库：Any 标注 LangChain 的模型/图对象（刻意不写死具体类型，它们来自多个包）
from typing import Any


class AgentScope(str, Enum):
    """Agent 作用域：决定装配哪一套工具与参数（ARCH-7）。"""

    # 主对话 agent：全量工具 + 共享 thread（当前唯一实际使用的取值）
    MAIN = "main"
    # 子 agent：独立 thread_id + 受限工具集（默认只读）+ 独立迭代上限；
    # 本版仅预留接口，行为与 MAIN 完全一致（默认关闭，不引入回归）
    SUB = "sub"


# --------------------------------------------------------------------------- #
# 缓存容器
# --------------------------------------------------------------------------- #
# 线程锁：SSE 是并发的，两个请求同时命中"缓存为空"时只应构建一份实例
_cache_lock = Lock()
# 缓存的聊天模型实例（不带工具）
_cached_model: Any | None = None
# 缓存该模型时的标识（provider:model:温度…）；与当前设置不一致就重建
_cached_model_key: str | None = None
# 缓存的 Agent 实例（带工具的编译图）。
# 从"单个槽位"改成"按指纹分槽"是因为 ARCH-7 接上调用方之后，同一个进程里会同时用到
# MAIN 与 SUB 两种图：单槽位会让它们互相顶掉，每派一次子任务就重建一次主对话图（几十毫秒 + 丢缓存）。
# 键里已经带了 scope（见 _settings_fingerprint），因此两种作用域天然分成两槽。
_cached_agents: dict[str, Any] = {}
# 是否已经订阅过设置变更（避免重复订阅导致失效被触发多次）
_subscribed = False


def _settings_fingerprint(scope: AgentScope = AgentScope.MAIN) -> str:
    """算出「当前配置」的指纹，用于判断缓存是否还有效。

    把所有影响装配结果的设置都纳入指纹：换供应商、换模型、改温度、改迭代上限都要重建。

    :param scope: Agent 作用域（SUB 的指纹里带上 scope，避免两种 scope 共用一份缓存）
    :return: 形如 "main:deepseek:deepseek-chat:0.0:25" 的指纹字符串
    """
    # 延迟导入：避免包初始化顺序问题
    from app.llm import registry
    from app.services.settings_registry import get_setting

    provider_id, model_name = registry.current_provider_and_model()
    try:
        temperature = float(get_setting("llm.temperature"))
    except Exception:
        temperature = 0.0
    try:
        max_iterations = int(get_setting("agent.max_iterations"))
    except Exception:
        max_iterations = 25
    # 技能清单也影响装配结果（系统提示词里会列出技能），所以必须进指纹：
    # 否则"装了新技能"不会触发重建，模型看不到它们。
    try:
        # 项目内：延迟导入，避免 llm 层在启动早期依赖技能目录
        from app.skills import registry as skill_registry

        names = ",".join(spec.name for spec in skill_registry.list_specs(include_disabled=False))
    except Exception:
        names = ""
    # MCP 工具同样是"运行时才知道"的装配输入（EXT-2）：换了 server / 工具变了必须重建，
    # 否则模型手里还是上一批工具。get_tools() 内部有配置指纹缓存，配置不变时开销很小。
    try:
        # 项目内：延迟导入，避免 llm 层在启动早期拉起 MCP 依赖
        from app.mcp import client as mcp_client

        mcp_names = ",".join(mcp_client.tool_names())
    except Exception:
        mcp_names = ""
    # 子 agent 开关也影响装配结果（MAIN 工具集里要不要挂 dispatch_subagent、提示词里要不要写用法），
    # 所以必须进指纹：否则用户刚在设置里开启，这一轮的工具清单还是旧的，他看着"开了却没反应"。
    return (
        f"{scope.value}:{provider_id}:{model_name}:{temperature}:{max_iterations}:"
        f"{names}:{mcp_names}:{subagent_enabled()}"
    )


def invalidate() -> None:
    """清空缓存，让下一次访问时按新设置重建模型与 Agent。

    设置变更事件（见 subscribe 处的订阅）与测试都会调它。
    """
    global _cached_model, _cached_model_key
    with _cache_lock:
        _cached_model = None
        _cached_model_key = None
        # 所有作用域的图一起清：设置变了，MAIN 与 SUB 都得重建
        _cached_agents.clear()


def get_model() -> Any:
    r"""取当前生效的**裸模型**（不带工具）。

    `\doc` 检索问答拿到片段后用它做一次性总结回答——刻意不挂工具，
    避免它跑去调工具把检索结果带偏（见 chat_controller._rag_messages 的说明）。

    :return: LangChain 聊天模型实例
    :raises factory.ModelConfigError: 供应商/模型配置不合法或缺密钥
    """
    ensure_subscribed()
    fingerprint = _settings_fingerprint()
    global _cached_model, _cached_model_key
    with _cache_lock:
        # 指纹一致说明设置没变，直接复用，避免每轮都重新构建
        if _cached_model is not None and _cached_model_key == fingerprint:
            return _cached_model

    # 构建要放在锁外：build_chat_model 可能触发依赖探测，耗时较长，锁内做会拖慢并发请求
    from app.llm.factory import build_chat_model
    from app.llm import registry

    provider_id, model_name = registry.current_provider_and_model()
    model = build_chat_model(provider_id, model_name or None)

    with _cache_lock:
        # 双检：构建期间可能已有别的协程填好了缓存，此时以先填的为准
        if _cached_model is not None and _cached_model_key == fingerprint:
            return _cached_model
        _cached_model = model
        _cached_model_key = fingerprint
        return _cached_model


def get_agent(scope: AgentScope = AgentScope.MAIN, checkpointer: Any | None = None) -> Any:
    """取当前生效的 Agent（带全部工具的编译图）。

    :param scope: Agent 作用域。MAIN＝全量工具（现状，零回归）；
                  SUB＝只读工具集 + 子 agent 提示词（ARCH-7，调用方是 `dispatch_subagent` 工具）
    :param checkpointer: LangGraph 检查点；由调用方（agents/rag_agent.py）注入，
                         因为检查点归agent 层管、模型归 llm 层管，分层更清晰
    :return: create_agent() 返回的编译图
    :raises factory.ModelConfigError: 供应商/模型配置不合法或缺密钥
    """
    ensure_subscribed()
    fingerprint = _settings_fingerprint(scope)
    with _cache_lock:
        cached = _cached_agents.get(fingerprint)
        if cached is not None:
            return cached

    # 延迟导入：agent 层依赖工具层，而工具层又可能反过来读设置，早导入容易成环
    from app.agents.rag_agent import build_system_prompt, build_tools, create_agent_graph

    # build_tools 而不是直接用 TOOLS：EXT-2 的 MCP 工具是运行时发现的，
    # 不能固定写进模块级常量（否则改了 mcp.servers 必须重启后端）
    # ARCH-7：按 scope 裁剪工具集与提示词——SUB 只拿只读工具，且不装配 MCP
    graph = create_agent_graph(
        get_model(),
        build_tools(scope.value),
        build_system_prompt(scope.value),
        checkpointer,
    )

    with _cache_lock:
        # 双检：构建期间可能已有别的线程填好了同一个指纹，以先填的为准
        existing = _cached_agents.get(fingerprint)
        if existing is not None:
            return existing
        _cached_agents[fingerprint] = graph
        return graph


def ensure_subscribed() -> None:
    """确保已订阅设置变更事件（幂等，只生效一次）。

    订阅 "llm." 前缀：用户在设置页改了模型/温度/端点，就让缓存失效，
    下一次对话自动用新配置——这是 doc/27§2「事件驱动、不轮询」的直接落点。
    """
    global _subscribed
    if _subscribed:
        return
    with _cache_lock:
        if _subscribed:
            return
        # 延迟导入：settings_registry 不应被本模块在包初始化期拉进来
        from app.services.settings_registry import subscribe

        subscribe("llm.", _on_llm_setting_changed)
        # agent.max_iterations 变了也要重建（递归上限是建图参数）
        subscribe("agent.", _on_llm_setting_changed)
        _subscribed = True


def _on_llm_setting_changed(event: Any) -> None:
    """设置变更事件的回调：清缓存，让下一次访问重建。

    :param event: SettingsChangeEvent（这里只需要它的存在，值本身不关心）
    """
    invalidate()


def reset_for_test() -> None:
    """清空缓存并复位订阅标记，供测试隔离用。"""
    global _subscribed
    invalidate()
    with _cache_lock:
        _subscribed = False


# 子 agent 的步数上限（ARCH-7）：独立于主对话的 agent.max_iterations。
# 为什么固定 10 而不是再加一个设置键：设置项每加一个就要在设置页解释一次，
# 而"子任务最多跑 10 步"远没有到需要用户调的粒度；真嫌少时把任务拆小更有效。
SUB_MAX_ITERATIONS = 10


def scope_max_iterations(scope: AgentScope = AgentScope.MAIN) -> int:
    """按 Agent 作用域给出这一轮的执行步数上限（ARCH-7）。

    主对话沿用设置键 `agent.max_iterations`（默认 25，用户可调）；
    子 agent 取"主对话上限"与 `SUB_MAX_ITERATIONS` 的较小值——
    即用户可以把它调得更小，但不能让子 agent 比主对话还能跑。

    :param scope: Agent 作用域
    :return: 步数上限（>=1）
    """
    try:
        # 延迟导入：避免模块导入期就把设置库拉进来
        from app.services.settings_registry import get_setting

        main_limit = int(get_setting("agent.max_iterations"))
    except Exception:
        main_limit = 25
    if main_limit < 1:
        main_limit = 1
    if scope is AgentScope.SUB:
        return min(main_limit, SUB_MAX_ITERATIONS)
    return main_limit


def subagent_enabled() -> bool:
    """读设置 `agent.subagent_enabled`：主对话是否获得派发子任务的能力（ARCH-7 的调用方开关）。

    为什么读失败按 False：这是个"额外能力"，不是"保底能力"。
    设置库读不到时退回关闭，最坏结果是"用户想用但用不了"，而不是"悄悄跑出额外行为"。

    :return: True 表示允许在主对话工具集里挂 `dispatch_subagent`
    """
    try:
        # 延迟导入：避免模块导入期就把设置库拉进来
        from app.services.settings_registry import get_setting

        return bool(get_setting("agent.subagent_enabled"))
    except Exception:
        return False