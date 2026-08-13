# app/tools/subagent_tool.py
"""
子 agent 派发工具：dispatch_subagent（ARCH-7 的调用方）。

它解决的问题：
    主对话跑到一半，冒出一个"只要读东西就能回答"的子任务——比如"把这个目录里
    所有 TODO 注释汇总一下""看看这几个文件的接口签名是否一致"。
    这类活儿在主线里干，会把大量原始文件内容灌进主上下文，把主线原本的推理顶掉。
    派给一个独立的子 agent 去做，主对话只收到它写的一份**结论**，上下文就干净了。

它凭什么安全（三层叠加，缺一层都不够）：
    1. 工具层：子 agent 只装配只读工具（见 `agents/rag_agent.SUB_TOOLS`），
       写盘、执行命令、文件管理、联网、MCP 一律没有；
    2. 权限层：即使将来放开了只读白名单，`tools/policy.py` 里还有一条红线——
       `SCOPE_SUB` 下凡 Kind.WRITE / Kind.EXEC 一律强制 ASK，不看 permission_mode；
    3. 生命周期层：子 agent 用**独立的内存检查点**与独立 thread_id，
       它的中间步骤不会污染主对话的检查点，也不出现在主对话的 SSE 事件流里。

它牺牲了什么（已知限制，写在这里免得后人以为是 bug）：
    - 子 agent 的 token 消耗不进 _usage 统计，界面上看不到它花了多少；
    - 子 agent 的工具调用不进主对话的 trace，排查问题时要看后端日志；
    - 子 agent 之间不共享发现，两个子任务读到同一个文件就会读两遍。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：asyncio 跑子 agent 的 async 图；子 agent 必须异步驱动（工具是同步的、执行在线程池里）
import asyncio
# 标准库：日志，记录子 agent 的失败原因（含堆栈），出问题只看界面是看不到的
import logging
# 标准库：threading.Lock 保护"当前跑了几个子 agent"这个计数器
import threading
# 标准库：uuid 给子 agent 生成独立的 thread_id，避免两次派发共用检查点
import uuid
# 标准库：Any 用于图与消息对象的宽松类型注解
from typing import Any, Callable, Coroutine

# LangChain 工具装饰器
from langchain_core.tools import tool

# 项目内：权限模型（策略查表、Action、操作类型、装饰器）
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：统一返回格式 "OK: ..." / "FAIL: ..."
from app.tools.tool_utils import fmt

# 模块日志器：子 agent 的超时、步数超限、异常都在这里留痕
log = logging.getLogger(__name__)

# 子任务描述的字符上限：超了说明用户/主模型在"一句话派活"这件事上没想清楚，直接拒比截断好
_MAX_TASK_CHARS = 2_000

# 主对话补充背景的字符上限：背景是"附加信息"，不该比任务本身还长
_MAX_CONTEXT_CHARS = 4_000

# 单个子 agent 的执行时限（单位：秒）。
# 为什么要有：子 agent 是自主跑的，模型偶发地会在只读工具之间反复横跳；
# 没有上限时它能把这一轮对话拖到用户以为程序卡死。
_SUB_TIMEOUT_SECONDS = 120.0

# 回传给主对话的结论字符上限：结论本来就是"压缩过的信息"，超过这个长度说明子 agent 没在总结
_MAX_ANSWER_CHARS = 4_000

# 当前正在跑的子 agent 个数（受 agent.subagent_max_parallel 约束）
_ACTIVE = 0

# 计数器锁：dispatch_subagent 会被不同线程（工具线程池）同时调用
_ACTIVE_LOCK = threading.Lock()


def enabled() -> bool:
    """子 agent 功能是否开启（设置 `agent.subagent_enabled`）。

    直接复用 `llm/state.subagent_enabled`，两边共用一份判定逻辑：
    那边决定"要不要把工具挂进主对话"，这边决定"真被调到时放不放行"。
    两处若各写一遍，最容易出现"界面上关掉了但工具仍然能跑"的错位。

    :return: True 表示允许执行派发
    """
    # 延迟导入：llm.state 会在模块导入期拉进模型工厂，本模块被 rag_agent 早导入时容易成环
    from app.llm.state import subagent_enabled

    return subagent_enabled()


def max_parallel() -> int:
    """读设置 `agent.subagent_max_parallel`：同时最多几个子 agent。

    :return: 1~8 之间的整数（读不到时按 2，与设置默认值一致）
    """
    try:
        # 延迟导入：避免模块导入期就把设置库拉进来
        from app.services.settings_registry import get_setting

        value = int(get_setting("agent.subagent_max_parallel"))
    except Exception:
        return 2
    return max(1, min(8, value))


def active_count() -> int:
    """当前正在跑的子 agent 个数（测试与排查用）。"""
    with _ACTIVE_LOCK:
        return _ACTIVE


def _acquire_slot() -> bool:
    """抢占一个并发槽位。

    :return: True＝抢到，可以开跑；False＝已达上限
    """
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE >= max_parallel():
            return False
        _ACTIVE += 1
        return True


def _release_slot() -> None:
    """归还并发槽位（无论成功、失败、超时都必须调用）。"""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = max(0, _ACTIVE - 1)


def reset_for_test() -> None:
    """把并发计数器归零（仅测试用：一个用例里故意造出"卡住的子 agent"时不会污染下一个）。"""
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = 0


def build_dispatch_action(task: str, context: str = "", **_kwargs: object) -> Action:
    """把一次 dispatch_subagent 调用翻译成待裁决的操作。

    :param task: 交给子 agent 的子任务描述
    :param context: 主对话补充的背景材料
    :param _kwargs: 其余参数（如 timeout），与裁决无关
    :return: 供裁决的 Action（READ：只读，不写盘、不执行）
    """
    # 目标只取前 80 字：确认弹窗与审计日志里都放不下长描述，够看就行
    target = (task or "").strip()[:80] or "(空任务)"
    return Action(
        tool="dispatch_subagent",
        kind=Kind.READ,
        target=target,
        preview={"task": (task or "")[:200], "context": (context or "")[:80]},
        detail="AI 将派出一个只读子 agent 处理这个子任务，只回收结论",
    )


def _collect_answer(result: Any) -> str:
    """从子 agent 的最终状态里取出最后一条 AI 消息的文本。

    为什么要单独抽出来：LangGraph 的返回值是 `{"messages": [...]}`，
    而消息 content 可能是 str，也可能是 Gemini/Claude 风格的
    `[{"type": "text", "text": "..."}]` 片段列表，两种都要处理。

    :param result: `graph.ainvoke` 的返回值
    :return: 结论文本（可能为空串）
    """
    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # 只收文本块；工具调用块（tool_use 等）对结论没有意义
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return str(content).strip()


async def _run_sub_agent(task: str, context: str, session_id: str) -> str:
    """真正把子 agent 跑起来，返回它写下的结论。

    三个 ContextVar 在这里被改写（作用域=sub、会话 id=带 #sub 后缀），
    子 agent 内部的工具通过 `current_context()` 读到它们，于是：
        - 拿不到写盘/执行的免确认（SCOPE_SUB 红线）；
        - 审计与插话队列落在独立的会话 id 上，不会把主对话的插话抽走。

    :param task: 子任务描述
    :param context: 主对话补充的背景
    :param session_id: 主对话的会话 id（用来派生子会话 id）
    :return: 结论文本
    """
    # 延迟导入：LangGraph 的检查点、状态模块与工具模块互相引用，模块级导入容易成环
    from langgraph.checkpoint.memory import MemorySaver

    # 项目内：取 SUB 作用域的图 + 该作用域的步数上限
    from app.llm.state import AgentScope, get_agent, scope_max_iterations
    # 项目内：子作用域常量与 ContextVar 写入口
    from app.tools.policy import SCOPE_SUB
    from app.tools.session import set_agent_scope, set_session_id

    # 检查点用全新的内存实例：子 agent 的中间步骤不写库、不复用主对话的 checkpoint
    graph = get_agent(AgentScope.SUB, checkpointer=MemorySaver())

    # 独立会话 id：`<主会话>#sub-<随机>`。带随机后缀是因为同一个主会话可能连续派两次，
    # 共用 thread_id 会让第二次接在第一次的中间状态上跑
    sub_session = f"{session_id}#sub-{uuid.uuid4().hex[:6]}"
    set_agent_scope(SCOPE_SUB)
    set_session_id(sub_session)

    prompt = task if not context else f"{task}\n\n[主对话补充的背景]\n{context}"
    # 子 agent 用自己的（更小的）步数上限：它是"做一件小事"，不该跑满主对话的预算
    limit = scope_max_iterations(AgentScope.SUB)
    result = await graph.ainvoke(
        {"messages": [("user", prompt)]},
        config={"configurable": {"thread_id": sub_session}, "recursion_limit": limit},
    )
    return _collect_answer(result)


def _run_coro_blocking(
    factory: Callable[[], Coroutine[Any, Any, str]],
) -> str:
    """把"跑一个协程"变成同步结果，同时兼容"当前线程已有事件循环"的情况。

    为什么需要兜底：理论上本工具是同步函数，由 LangGraph 丢到线程池里执行，
    线程里没有运行中的事件循环，直接 `asyncio.run` 就行。但"理论上"不该成为
    唯一防线——一旦某天它被从 async 上下文里直接调用，`asyncio.run` 会抛
    `RuntimeError: asyncio.run() cannot be called from a running event loop`，
    那是一个很难从用户报障里定位的错误。所以这里显式探测，换个线程跑独立的事件循环。

    :param factory: 返回协程的工厂函数（每次调用产出一个全新协程）
    :return: 协程的返回值
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 常见路径：工具线程池里的普通线程，没有事件循环
        return asyncio.run(factory())

    # 兜底路径：当前线程已有事件循环，另起一个线程跑独立循环。
    # 子 agent 的检查点在内存里、不跨线程共享，所以这么搬是安全的
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


@tool
@make_tool(
    POLICIES["dispatch_subagent"],
    lambda task, context="": build_dispatch_action(task, context),
)
def dispatch_subagent(task: str, context: str = "") -> str:
    """把一个"只要读东西就能回答"的子任务派给隔离的只读子 agent，只回收结论。

    适用：在多个文件/目录里汇总信息、反复检索后给出总结、需要大量试读才敢下判断的调研。
    不适用：需要写文件或跑命令的活儿（子 agent 拿不到写/执行工具，会被红线拦住）；
            一句话就能答的问题（派子 agent 反而更慢更贵）；
            需要跟用户来回确认的活儿（子 agent 不能跟用户对话）。
    写出结论后请用自己的话向用户复述关键点，不要把子 agent 的原话整段贴出来。

    :param task: 子任务描述。要写清"读哪些地方、回答什么问题、结论要什么形式"
    :param context: 可选背景：主对话已经知道的线索（子 agent 看不到主对话历史）
    :return: "OK: 子 agent 的结论" 或 "FAIL: 原因"
    """
    if not enabled():
        return fmt(
            False,
            "子 agent 功能没有开启：请到「设置 → Agent 行为 → 启用子 agent」打开后再试；"
            "这一步也可以自己直接用只读工具完成",
        )

    cleaned = (task or "").strip()
    if not cleaned:
        return fmt(False, "子任务描述不能为空：请写清要读哪些地方、回答什么问题")
    if len(cleaned) > _MAX_TASK_CHARS:
        return fmt(False, f"子任务描述太长（{len(cleaned)} 字，上限 {_MAX_TASK_CHARS} 字），请精简后再派")

    brief = (context or "").strip()[:_MAX_CONTEXT_CHARS]

    if not _acquire_slot():
        return fmt(
            False,
            f"同时运行的子 agent 已达上限（{max_parallel()} 个）。"
            "请等其中一个结束再派，或者自己用只读工具把这个子任务做掉",
        )

    # 延迟导入：这两个异常类型来自 langgraph，放在模块顶部会让"没装 langgraph 时连工具都导不进来"
    from langgraph.errors import GraphRecursionError

    # 延迟导入：拿主对话的会话 id（ContextVar 在线程池里已被复制过来）
    from app.tools.session import current_session_id

    try:
        # wait_for 兜的是"子 agent 卡住不动"：超时会把协程取消并抛 TimeoutError
        answer = _run_coro_blocking(
            lambda: asyncio.wait_for(
                _run_sub_agent(cleaned, brief, current_session_id()),
                timeout=_SUB_TIMEOUT_SECONDS,
            )
        )
    except asyncio.TimeoutError:
        log.warning("子 agent 超时：%.0f 秒未结束，任务=%r", _SUB_TIMEOUT_SECONDS, cleaned[:80])
        return fmt(
            False,
            f"子 agent 超过 {_SUB_TIMEOUT_SECONDS:.0f} 秒仍未结束，已中止。"
            "请把子任务拆得更小（例如一次只查一个目录），或自己直接做",
        )
    except GraphRecursionError:
        log.warning("子 agent 步数超限：任务=%r", cleaned[:80])
        return fmt(
            False,
            "子 agent 步数超过上限仍没得出结论，已中止。"
            "请把子任务拆得更具体（明确要读哪几个文件/目录），或自己直接做",
        )
    except Exception as exc:  # noqa: BLE001 —— 子 agent 里什么都可能发生，必须兜住
        log.exception("子 agent 执行失败：%s", exc)
        return fmt(False, f"子 agent 执行失败：{exc}")
    finally:
        _release_slot()

    if not answer:
        return fmt(False, "子 agent 没有写出任何结论（可能它以为任务已经完成），可以换一种问法再派一次")

    if len(answer) > _MAX_ANSWER_CHARS:
        answer = answer[:_MAX_ANSWER_CHARS] + f"\n…（结论超过 {_MAX_ANSWER_CHARS} 字，已截断）"

    # 注意：这里刻意**不**把子 agent 的中间步骤贴出来。主对话要的是结论，
    # 把过程也灌进来就失去了"隔离"的意义
    return fmt(True, f"子 agent 的结论（只读调研，未改动任何文件）：\n{answer}")


# 本模块对外暴露的工具列表（默认不挂进主对话，由 agent.subagent_enabled 控制）
SUBAGENT_TOOLS = [dispatch_subagent]
