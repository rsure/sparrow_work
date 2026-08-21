"""执行中插话（steering）的会话队列（ARCH-6）。

解决的问题：
    用户发了一条长任务，模型正在跑工具（比如连跑十几条命令）。这时他想补一句
    "别动 test 目录"——改造前的做法只有两种：等这一轮跑完，或者整轮终止。
    steering 提供第三种：**把这句话塞进正在跑的那一轮**，不打断已经生成的内容。

为什么不做"工具执行中途强杀"：
    工具是同步函数，跑在 LangChain 的线程池里，Python 没有安全的"中途掐断一个线程"的手段
    （杀线程会留下半写的文件、半提交的事务）。所以本模块只在**两个步间边界**介入：
        1. 工具**开始前**：如果用户请求取消，直接不执行，返回一段"已跳过"的文案；
        2. 工具**结束后**：把攒下的插话追加进这次工具的结果文本里。
    追加进结果文本是关键：模型下一步收到的就是 ToolMessage 的内容，
    它会像读普通工具输出一样读到"用户刚说了什么"，因此**不需要改动图结构**。

数据结构：
    每个会话一条待注入队列 + 一条"已注入待上报"队列 + 一个取消标记。
    用 `threading.Lock` 而不是 asyncio.Lock：工具跑在线程池里（同步），
    而控制器在事件循环里（异步），两边的互斥只能用线程级锁。

与设置的关系：
    总开关是 `agent.steering_enabled`（默认开）。关掉后 `/chat/{id}/steer` 返回 400，
    前端退化为"执行期间禁用输入框"——也就是改造前的行为。
"""

# 标准库：生成插话 id、记录时间戳、线程级互斥锁
import threading
import time
import uuid
# 数据类：让一条插话有明确的字段，而不是裸 dict
from dataclasses import dataclass

# 项目内：单条插话的最大字符数。超长的"插话"其实是新任务，应该等这一轮结束再发：
# 模型正在改文件时塞进两千字需求，只会让它同时干两件事、两件都干不好。
MAX_CONTENT_CHARS = 2000
# 单个会话最多攒多少条待注入插话。超出就拒绝——防止前端失控刷屏把上下文撑爆
MAX_PENDING = 5
# 插话总开关的设置键（ARCH-6；值在设置页「任务与上下文」组里）
SETTING_ENABLED = "agent.steering_enabled"
# 追加到工具结果里的插话块前缀。用固定字样是为了让模型能一眼分辨"这是用户说的"，
# 而不是把它当成工具自己吐出来的内容
INJECT_PREFIX = "[用户插话]"
# 插话块末尾的说明：告诉模型这条插话是"追加指令"，不是新的独立任务
INJECT_HINT = "（以上是用户在本次工具执行期间追发的指令，请在下一步一并考虑；不要把它当成新任务重做一遍。）"


@dataclass(frozen=True)
class SteerItem:
    """一条待注入的用户插话。"""

    # 插话 id，前端用它把"已接收"的气泡和随后的 steer_injected 事件对上
    steer_id: str
    # 用户原话（已去掉首尾空白）
    content: str
    # 入队时间（Unix 秒），用于排查"为什么这条没被注入"
    created_at: float


# 待注入队列：{session_id: [SteerItem, ...]}，先进先出
_PENDING: dict[str, list[SteerItem]] = {}
# 已注入但还没上报给前端的队列：{session_id: [SteerItem, ...]}。
# 工具跑在线程里、发 SSE 在事件循环里，只能"工具先记账、控制器后取走"。
_INJECTED: dict[str, list[SteerItem]] = {}
# 取消标记：{session_id: 工具名}；空串表示"下一个开始的工具，不管叫什么"。
# 只影响"还没开始"的工具——见模块 docstring 的说明。
_CANCEL: dict[str, str] = {}
# 全局锁：上面三张表的所有读写都必须在它里面（线程池 + 事件循环并发访问）
_LOCK = threading.Lock()


def enabled() -> bool:
    """插话总开关是否打开（读设置键 `agent.steering_enabled`，默认开）。

    读设置失败按"开"处理：这个开关只影响交互方式，不影响安全
    （写盘依然要确认），所以失败时宁可用新交互，也不要把功能悄悄关掉。

    :return: True=允许插话
    """
    # 项目内：延迟导入，避免服务层在模块导入期就依赖设置库
    from app.services.settings_registry import get_setting

    try:
        return bool(get_setting(SETTING_ENABLED))
    except Exception:
        return True


def enqueue(session_id: str, content: str) -> SteerItem:
    """把一条用户插话放进该会话的待注入队列。

    :param session_id: 会话 id
    :param content: 用户原话
    :return: 入队后的插话（含 steer_id，前端拿它做乐观更新）
    :raises ValueError: 内容为空 / 超长 / 攒得太多
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("插话内容不能为空")
    if len(text) > MAX_CONTENT_CHARS:
        raise ValueError(f"插话请控制在 {MAX_CONTENT_CHARS} 字以内；更长的需求请等这一轮结束后再发")

    item = SteerItem(steer_id=uuid.uuid4().hex[:12], content=text, created_at=time.time())
    with _LOCK:
        queue = _PENDING.setdefault(session_id, [])
        if len(queue) >= MAX_PENDING:
            raise ValueError(f"这一轮已经有 {MAX_PENDING} 条插话在排队，请等模型消化完再发")
        queue.append(item)
    return item


def drain(session_id: str) -> list[SteerItem]:
    """取走该会话全部待注入插话（先进先出），并把它们登记为"已注入"。

    谁调用它，谁就负责把内容真正交给模型：目前唯一的调用方是
    `tools.policy.make_tool` 的 wrapper（它把内容追加进工具结果文本）。
    登记"已注入"这个动作放在这里，而不是让调用方自己去 note，
    是为了保证"取走"与"记账"是同一个原子操作——漏记会让前端一直等不到 steer_injected。

    :param session_id: 会话 id
    :return: 本次取走的插话列表（可能为空）
    """
    with _LOCK:
        items = _PENDING.pop(session_id, [])
        if items:
            _INJECTED.setdefault(session_id, []).extend(items)
        return items


def take_injected(session_id: str) -> list[SteerItem]:
    """取走"已注入但还没上报"的插话，供控制器发 steer_injected 事件。

    :param session_id: 会话 id
    :return: 尚未上报的插话列表（可能为空）
    """
    with _LOCK:
        return _INJECTED.pop(session_id, [])


def pending_count(session_id: str) -> int:
    """当前还有多少条插话在排队（前端「插话」按钮上的角标用）。

    :param session_id: 会话 id
    :return: 排队条数
    """
    with _LOCK:
        return len(_PENDING.get(session_id, []))


def request_tool_cancel(session_id: str, tool: str = "") -> None:
    """登记"下一个开始的工具不要执行"。

    :param session_id: 会话 id
    :param tool: 指定工具名；空串表示不管下一个是什么工具都取消
    """
    with _LOCK:
        _CANCEL[session_id] = tool


def take_tool_cancel(session_id: str, tool: str) -> bool:
    """工具开始前询问"我该不该跳过"，命中则把标记消费掉。

    命中规则：登记的是空串（任意工具），或登记的工具名与自己相同。
    没命中的标记不消费——用户可能是隔着一次工具点击的"取消"，
    等真正要取消的那个工具开始时再命中。

    :param session_id: 会话 id
    :param tool: 即将执行的工具名
    :return: True=应跳过本次执行
    """
    with _LOCK:
        marked = _CANCEL.get(session_id)
        if marked is None:
            return False
        if marked and marked != tool:
            return False
        _CANCEL.pop(session_id, None)
        return True


def has_tool_cancel(session_id: str) -> bool:
    """是否登记了取消标记（不消费），供端点判断"要不要提示用户"。

    :param session_id: 会话 id
    :return: 是否存在标记
    """
    with _LOCK:
        return session_id in _CANCEL


def begin_turn(session_id: str) -> None:
    """新一轮开始时清空该会话的插话状态。

    为什么必须清：上一轮没来得及注入的插话（模型在一轮末尾已经不再调工具了）
    如果留到下一轮，就会在用户完全没有预期的时候突然出现在模型上下文里。
    宁可丢掉——前端会在流结束时把"未注入"的插话自动改发成一条普通消息（见 ChatView），
    这样用户输入不会真的消失，但也不会串轮。

    :param session_id: 会话 id
    """
    with _LOCK:
        _PENDING.pop(session_id, None)
        _INJECTED.pop(session_id, None)
        _CANCEL.pop(session_id, None)


def end_turn(session_id: str) -> None:
    """本轮结束时收尾：丢掉残留的排队与取消标记（语义与 begin_turn 相同，分开命名便于阅读）。

    :param session_id: 会话 id
    """
    begin_turn(session_id)


def reset_for_test() -> None:
    """清空全部状态，供测试隔离用。"""
    with _LOCK:
        _PENDING.clear()
        _INJECTED.clear()
        _CANCEL.clear()
