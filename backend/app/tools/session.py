# app/tools/session.py
"""
会话上下文传递：把当前请求的 session_id 与工作区设置传给工具层。

为什么用 ContextVar 而不是函数参数：
    工具是"原子能力"，签名里塞一个 session_id 会让每个工具的接口都被污染；
    而且模型也要为这个参数生成值（它根本不知道 session id）。
    ContextVar 是"隐式上下文"，随调用链传播，且天然按请求隔离。

注意：工具在 LangGraph 节点里执行（可能被丢进线程池），
ContextVar 的值会随 asyncio.to_thread / 线程池上下文复制一起带过去；
但如果你换了执行方式（例如自己 new 一个裸线程），需要手动 copy_context。
"""

# 标准库：contextvars 提供按请求隔离的隐式上下文
from contextvars import ContextVar

# 项目内：策略层的会话上下文与两个作用域取值（ARCH-7）
# SessionContext 是裁决逻辑的入参（本模块返回它，也用作返回类型注解）；
# SCOPE_MAIN 是"主对话"的默认作用域取值
from app.tools.policy import SCOPE_MAIN, SessionContext

# 当前会话 id；未设置时为空串（表示"不在某次对话里"，例如脚本直接调用工具）
_current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")

# 当前 Agent 作用域（ARCH-7）：主对话默认 SCOPE_MAIN；
# 将来跑子 agent 时由驱动方 set_agent_scope(SCOPE_SUB)，工具层据此执行"写操作强制询问"的红线。
# 用 ContextVar 与 session_id 同理：工具签名不该被这个参数污染，模型更不可能填对。
_current_scope: ContextVar[str] = ContextVar("current_scope", default=SCOPE_MAIN)


def set_session_id(session_id: str) -> None:
    """设置当前上下文的会话 id（由 chat_controller 在每轮对话开始时调用）。"""
    _current_session_id.set(session_id)


def current_session_id() -> str:
    """读取当前上下文的会话 id；未设置时为空串。"""
    return _current_session_id.get()


def set_agent_scope(scope: str) -> None:
    """设置当前上下文的 Agent 作用域（ARCH-7）：MAIN 或 SUB。

    只在"真的以子 agent 身份跑一段"时调用；主对话路径永远保持默认值，
    所以这个函数存在本身不会改变任何现有行为。
    """
    _current_scope.set(scope)


def current_scope() -> str:
    """读取当前上下文的 Agent 作用域；默认 SCOPE_MAIN。"""
    return _current_scope.get()


# app/tools/session.py（追加）
def current_context() -> SessionContext:
    """组装当前会话的权限上下文：工作区来自「当前 active 工作区」，禁用工具来自会话内开关。

    ARCH-3 之后工作区不再是单一扁平列表，而是多profile；这里取的是 active 工作区的根目录并集，
    且已过滤掉实际不存在的目录（外接硬盘拔掉、目录被移动等）。

    :return: 供 policy.decide 使用的 SessionContext
    """
    try:
        # 项目内：工作区服务，读当前 active 工作区的根目录（内部已做旧数据迁移）
        from app.services.workspace_service import get_active, get_active_roots

        roots = tuple(get_active_roots())
        # 工作区 id 供 UX-7 的"工作区级授权"使用；读不到就当没有工作区（不放行）
        active = get_active() or {}
        workspace_id = str(active.get("id") or "")
    except Exception:
        # 数据库未就绪/表不存在时退回"不限制"，绝不因读设置失败而挡掉工具本身
        roots = ()
        workspace_id = ""

    # UX-7：权限模式。读不到一律回退 ask（最严）——
    # "读设置失败"绝不能变成"默认放行"，这是本模块最重要的安全不变量。
    permission_mode = "ask"
    try:
        # 项目内：设置注册表（已落库值优先，未落库回落声明默认值）
        from app.services.settings_registry import get_setting

        raw_mode = str(get_setting("permission.mode") or "ask").strip().lower()
        if raw_mode in ("ask", "workspace", "allow"):
            permission_mode = raw_mode
    except Exception:
        permission_mode = "ask"

    return SessionContext(
        session_id=current_session_id(),
        workspace_roots=roots,
        workspace_id=workspace_id,
        permission_mode=permission_mode,
        # ARCH-7：作用域也随上下文传递；默认 main，子 agent 由驱动方显式设置。
        # 它是"写操作强制询问"红线的唯一开关，因此不能从设置里读（不开放配置）。
        scope=current_scope(),
    )
