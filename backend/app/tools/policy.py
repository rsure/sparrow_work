# app/tools/policy.py
"""
工具权限模型：把"某次操作能不能做"集中成一次裁决，所有工具都必须过这一关。

为什么要有这个文件（读代码前先记住）：
    第 01 步把"路径能不能碰"收敛成了 tool_utils.path_decision，但它仍然靠工具自觉调用。
    本文件把它升级成**强制入口**：工具不再自己判断该不该问、该不该拒，只声明"我要做什么"，
    由 decide() 统一裁决。这样"新增工具忘记加检查"在结构上变得不可能——
    因为工具是通过 make_tool() 注册的，注册时就绑定了 Policy，调用时框架自动裁决。

三层概念：
    Policy   静态策略：一个工具"是什么类型、参数里哪些是路径、默认要不要确认"（注册时定死）
    Action   动态操作：这一次调用实际要做的事（工具函数运行时构造）
    Decision 裁决结果：allow / ask / deny + 原因 + 给弹窗看的预览（decide() 算出）

默认拒绝（fail-closed）：
    没注册 Policy 的工具一律 DENY。宁可让新工具"跑不起来、被迫去注册"，
    也不要让它"默认放行、悄悄越权"。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、dict[str, Any] 等新语法
from __future__ import annotations

# 标准库：枚举定义"操作类型"和"裁决等级"，避免到处写裸字符串
from enum import Enum
# 标准库：dataclass 描述 Policy / Action / Decision / SessionContext
from dataclasses import dataclass, field
# 标准库：functools.wraps 在包装工具函数时保留原函数的名字与 docstring
from functools import wraps
# 标准库：Any 用于 args 这类结构由各工具自定的字段
from typing import Any, Callable
# 标准库：路径对象，解析参数里的路径并交给 path_decision
from pathlib import Path

# 项目内：工具统一返回格式
from app.tools.tool_utils import (
    OP_EXEC,
    OP_READ,
    OP_WRITE,
    path_decision,
    resolve_abs_path,
)


class Kind(str, Enum):
    """操作类型：决定默认裁决等级。"""

    # 只读查询：列目录、读文件、检索。默认直接放行
    READ = "read"
    # 写磁盘：新建、覆盖、修改、删除、移动
    WRITE = "write"
    # 执行命令：跑脚本、跑测试、跑构建
    EXEC = "exec"
    # 联网：搜索、抓取网页
    NET = "net"
    # 外部 MCP server 提供的工具（EXT-2）：
    # 我们无法在本地判断它到底做了什么（可能是读，也可能是删库），
    # 所以默认等级是 DENY，必须由策略显式要求确认才允许执行。
    MCP = "mcp"


class Level(str, Enum):
    """裁决等级。"""

    # 直接执行，不打扰用户
    ALLOW = "allow"
    # 需要用户确认（由调用方弹窗）
    ASK = "ask"
    # 拒绝执行，不弹窗
    DENY = "deny"


# --------------------------------------------------------------------------- #
# Agent 作用域（ARCH-7）
# --------------------------------------------------------------------------- #
# 主对话 agent 的作用域取值：全量工具、走完整权限模式（与改造前完全一致）
SCOPE_MAIN = "main"
# 子 agent 的作用域取值：受限只读工具集 + 写/执行操作强制每次询问
SCOPE_SUB = "sub"
# 子 agent 下"不能免确认"的操作类型（红线）：
# 写盘与执行命令都会产生不可撤销的副作用，而子 agent 是自主跑的、没人盯着它，
# 所以即使 permission_mode=allow、即使这个工作区已经批准过该工具，也必须每次问。
_SUB_FORCED_KINDS: frozenset[Kind] = frozenset({Kind.WRITE, Kind.EXEC})


@dataclass(frozen=True)
class Policy:
    """一个工具的静态安全策略（注册时声明，运行期不变）。"""

    # 工具名，必须与 @tool 函数名一致（前端确认弹窗按它选标题）
    tool: str
    # 操作类型，决定默认裁决等级
    kind: Kind
    # 参数中属于"路径"的键名：这些参数的值会被解析成绝对路径并逐个交给 path_decision
    path_args: tuple[str, ...] = ()
    # 这些参数里的路径按哪个操作类型校验（默认与 kind 一致；写工具里的"源路径"只读，可单独指定）
    path_op: str = ""
    # 强制要求用户确认（覆盖 kind 的默认等级）。例如同为 WRITE，删除必须问、写日志可以不问
    require_confirm: bool = False
    # 显式指定裁决等级（优先级高于 require_confirm 与 kind 的默认等级）。
    # 为什么需要它：EXT-2 的 MCP 工具"要不要问"是可以按 server/工具配置的，
    # 而 Kind.MCP 的默认等级是 DENY（未知能力一律拒绝）。若只靠 require_confirm，
    # 免确认时 require_confirm=False 会退化成 DENY，反而把工具禁用掉。
    # 因此这两种情况都用 default_level 显式表达：ALLOW=免确认，ASK=需确认。
    default_level: "Level | None" = None
    # 免确认条件说明（给读代码的人看：为什么这个工具可以不问）
    confirm_note: str = ""
    # 是否默认关闭（例如联网工具），开启需要用户在设置里显式打开
    off_by_default: bool = False


@dataclass
class Action:
    """一次待执行的具体操作（由工具函数在产生副作用之前构造）。"""

    # 工具名
    tool: str
    # 操作类型
    kind: Kind
    # 本次操作的目标（人类可读的描述，如文件路径或命令字符串）；没有单一目标时给概要
    target: str
    # 需要校验的路径列表（工具自己从参数里挑出来）
    paths: tuple[Path, ...] = ()
    # 展示给确认弹窗的关键参数（键 → 已截断的值）
    preview: dict[str, Any] = field(default_factory=dict)
    # 附加说明：写进 Decision.reason 的"这次到底要做什么"
    detail: str = ""


@dataclass(frozen=True)
class Decision:
    """一次裁决的结果。"""

    # 裁决等级
    level: Level
    # 原因或说明：level=DENY 时是拒绝理由（直接作为 FAIL 文案）；
    # level=ASK 时是弹窗正文；level=ALLOW 时可为空
    reason: str = ""
    # 弹窗标题（仅 level=ASK 时有意义）
    title: str = ""


@dataclass
class SessionContext:
    """会话级上下文：把"这次是谁在什么范围内操作"传给裁决逻辑。

    第 06 篇「会话级安全」会真正用上 workspace_roots / allow_tools；
    本步先把它建成参数，让后续扩展不必改动 decide() 的签名。
    """

    # 会话 id，用于审计与"记住本次选择"
    session_id: str = ""
    # 本会话允许写入/执行的目录白名单；为空表示用全局 WORKSPACE_ROOTS（见 tool_utils）
    workspace_roots: tuple[Path, ...] = ()
    # 本会话显式禁用的工具名（用户在界面上关掉的能力）
    deny_tools: frozenset[str] = frozenset()
    # 本会话显式允许的执行命令（第 03 篇的会话级命令白名单）
    allowed_commands: frozenset[str] = frozenset()
    # 当前工作区 id（ARCH-3）；空串表示还没有工作区，此时"工作区授权"无从谈起。
    # UX-7 的 workspace 模式靠 (workspace_id, tool) 查 approvals 表决定要不要弹窗。
    workspace_id: str = ""
    # 权限模式（UX-7，来自设置键 permission.mode）：
    #   ask       每次询问（默认，fail-safe）
    #   workspace 本工作区首次批准后同类操作自动放行
    #   allow     完全授权：跳过确认弹窗（DENY 硬护栏仍然生效）
    permission_mode: str = "ask"
    # Agent 作用域（ARCH-7）：SCOPE_MAIN=主对话，SCOPE_SUB=子 agent。
    # 子 agent 的写/执行操作**强制每次询问**，这条是红线、不开放配置，见 decide() 第 5 步。
    scope: str = SCOPE_MAIN


# --------------------------------------------------------------------------- #
# 工具注册表：工具 → 策略
# --------------------------------------------------------------------------- #
# 为什么用注册表而不是写一串 if tool_name == ...：
#   第 03/04/05 篇会各加若干工具，if 链会越来越长且容易漏。
#   注册表让"没注册"成为一个**可被测试断言的状态**（见第 5 节的自查测试）。
POLICIES: dict[str, Policy] = {}


def register(policy: Policy) -> Policy:
    """把一个工具的策略登记进注册表（重复注册同名工具会报错，避免静默覆盖）。

    :param policy: 待登记的策略
    :return: 同一个 policy，便于当作装饰器使用
    :raises ValueError: 同名工具已注册过
    """
    if policy.tool in POLICIES:
        raise ValueError(f"工具 {policy.tool} 的策略已注册，不要重复注册（会掩盖旧策略）")
    POLICIES[policy.tool] = policy
    return policy


def builtin_policies() -> list[Policy]:
    """声明项目中**全部**工具的静态策略。

    新增工具时必须在这里加一条，否则工具会在启动自检（verify_all_tools_registered）时暴露。
    判定基准（与产品定位一致）：
        只读        → ALLOW（不打扰用户；系统目录已在 resolve_abs_path 拦截）
        写磁盘      → ASK  （人类必须看见每一次落盘）
        删知识库    → ASK  （不可恢复）
        执行命令    → ASK  （第 03 篇；最高危）
        联网        → 默认关闭，开启后 ASK
    """
    return [
        # ---------- 只读 ----------
        Policy(tool="list_dir", kind=Kind.READ, path_args=("path",), path_op=OP_READ),
        Policy(tool="read_file", kind=Kind.READ, path_args=("path",), path_op=OP_READ),
        Policy(tool="grep_files", kind=Kind.READ, path_args=("root",), path_op=OP_READ),
        Policy(tool="list_indexed_docs", kind=Kind.READ),
        Policy(tool="rag_search", kind=Kind.READ),
        # 技能（EXT-1）：只读清单与正文；本身不产生副作用，真正的风险在技能指引你去调用的工具上
        Policy(tool="list_skills", kind=Kind.READ),
        Policy(tool="read_skill", kind=Kind.READ),
        # ---------- 写知识库 ----------
        Policy(
            tool="index_path", kind=Kind.WRITE,
            path_args=("path",), path_op=OP_READ,   # 只读源文件，写入的是数据库
            require_confirm=True, confirm_note="会向知识库写入切片与向量，且可能解析上百个文件",
        ),
        Policy(
            tool="delete_index", kind=Kind.WRITE,
            require_confirm=True, confirm_note="知识库记录不可恢复",
        ),
        # ---------- 写磁盘 ----------
        Policy(
            tool="write_file", kind=Kind.WRITE,
            path_args=("path",), path_op=OP_WRITE,
            require_confirm=True, confirm_note="落盘位置必须让用户看到（新建与覆盖都要）",
        ),
        Policy(
            tool="edit_file", kind=Kind.WRITE,
            path_args=("path",), path_op=OP_WRITE,
            require_confirm=True, confirm_note="改动已有文件，改错会破坏原内容（有 .bak 兜底）",
        ),
        # ---------- 执行命令（第 03 篇） ----------
        Policy(
            tool="run_command", kind=Kind.EXEC,
            path_args=("cwd",), path_op=OP_EXEC,
            require_confirm=True,
            confirm_note="命令会在你的机器上真实执行，请逐条确认",
        ),
        # ---------- 查找（只读） ----------
        Policy(tool="glob", kind=Kind.READ, path_args=("root",), path_op=OP_READ),
        # ---------- 文件管理（一次调用可能动很多文件，必须确认） ----------
        Policy(
            tool="file_ops", kind=Kind.WRITE,
            require_confirm=True,
            confirm_note="移动/复制/删除会改变磁盘内容；删除默认进回收站，直删不可恢复",
        ),
        # ---------- 联网（第 05 篇）：唯一默认关闭的能力 ----------
        Policy(
            tool="web_search", kind=Kind.NET,
            require_confirm=True, off_by_default=True,
            confirm_note="会把你的搜索词发送到外部搜索引擎",
        ),
        Policy(
            tool="web_fetch", kind=Kind.NET,
            require_confirm=True, off_by_default=True,
            confirm_note="会访问外部网站，抓回的内容属于不可信数据",
        ),
        # ---------- EXT-3 通用 HTTP（NET）：与联网工具同开关，默认关闭 ----------
        Policy(
            tool="http_request", kind=Kind.NET,
            require_confirm=True, off_by_default=True,
            confirm_note="会把请求发到外部地址；POST/PUT 等写方法还需另开开关，响应体属于不可信数据",
        ),
        # ---------- EXT-3 SQLite 只读查询（READ）：按 db_path 做路径范围校验 ----------
        Policy(
            tool="sql_query", kind=Kind.READ,
            path_args=("db_path",), path_op=OP_READ,
            confirm_note="只读查询：只允许 SELECT/WITH/EXPLAIN，且以 mode=ro 打开数据库",
        ),
        # ---------- ARCH-7 子 agent 派发（READ）：本身不动任何东西 ----------
        # 为什么登记成 READ 而不是 WRITE：
        #   这个工具自己没有副作用，它只是"另起一个隔离的 agent 去读东西然后汇报"。
        #   真正的风险在子 agent 内部调用的工具上，而那一层已经被 SCOPE_SUB 的红线接管
        #   （写盘/执行在子作用域里强制逐次询问，见 _SUB_FORCED_KINDS），
        #   所以在门口再拦一道只会让用户每派一次子任务都点一次"允许"，纯属噪音。
        Policy(
            tool="dispatch_subagent", kind=Kind.READ,
            confirm_note="子 agent 只拿得到只读工具，且写盘/执行在子作用域里仍强制逐次确认",
        ),
    ]


def install_builtin_policies() -> None:
    """把内置策略装进注册表；重复调用安全（已存在则跳过）。"""
    for policy in builtin_policies():
        if policy.tool not in POLICIES:
            register(policy)


def register_dynamic(policy: Policy) -> None:
    """登记（或覆盖）一条**运行时才发现**的工具策略。

    与 `register()` 的区别：允许覆盖同名。为什么需要它：
        MCP server 的工具是连接之后才知道的（EXT-2），每次重连都可能拿到新的
        名字/新的免确认状态（用户在设置里改了 `mcp.auto_approve_tools`）。
        如果沿用"重复注册就报错"，重连一次就会炸；如果沿用"已存在就跳过"，
        用户改的免确认名单永远不生效。所以这里明确选"以最新的为准"。

    :param policy: 待登记的策略
    """
    POLICIES[policy.tool] = policy


def unregister_prefix(prefix: str) -> int:
    """按前缀批量移除策略（MCP server 被删掉/改名时清理残留）。

    为什么要清理：残留策略的后果是"这个工具明明已经没了，但策略还在"——
    本身不至于出错，但会让"策略表与实际可用工具一致"这条不变量失效，
    也会让审计里出现永远不会有调用的工具名。

    :param prefix: 工具名前缀，如 "mcp__"
    :return: 实际移除的条数
    """
    victims = [name for name in POLICIES if name.startswith(prefix)]
    for name in victims:
        POLICIES.pop(name, None)
    return len(victims)


# 模块导入时立即登记内置策略。
# 原因：各工具模块的 @make_tool(POLICIES["xxx"], ...) 是在**模块导入时**求值的，
# 而 rag_agent.py 会先导入工具模块、后调用 install_builtin_policies()，
# 顺序一颠倒 POLICIES 还是空字典，就会抛 KeyError: 'write_file'。
# 放在这里后，只要导入了 policy，注册表就一定是填好的（函数本身幂等，重复调用无害）。
install_builtin_policies()





# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 裁决
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 各操作类型的默认等级：没被策略显式覆盖时生效
_DEFAULT_LEVEL: dict[Kind, Level] = {
    Kind.READ: Level.ALLOW,
    Kind.WRITE: Level.DENY,      # 未声明的写操作一律拒绝，迫使工具作者显式声明
    Kind.EXEC: Level.DENY,       # 同上，执行类必须显式声明
    Kind.NET: Level.DENY,        # 联网默认关闭
    Kind.MCP: Level.DENY,        # 外部工具：不知道它做什么，未显式声明确认就拒绝
}


def decide(tool: str, action: Action, session: SessionContext | None = None) -> Decision:
    """裁决一次操作：能不能做、要不要问用户。

    判定顺序（每一步都能单独测试）：
        1. 工具是否注册了策略（没注册 → DENY，fail-closed）
        2. 会话是否显式禁用了这个工具（→ DENY）
        3. 策略是否默认关闭（→ DENY，提示用户去设置里打开）
        4. 逐个校验路径（走 tool_utils.path_decision，沿用第 01 步的规则表）
        5. 按 kind 与 require_confirm 得出等级

    :param tool: 工具名
    :param action: 工具声明的本次操作
    :param session: 会话上下文；None 表示用默认上下文（等价于空 SessionContext）
    :return: 裁决结果
    """
    ctx = session or SessionContext()

    # 1. 未注册策略：默认拒绝。这条是整个模型的基石（fail-closed）
    policy = POLICIES.get(tool)
    if policy is None:
        return Decision(
            Level.DENY,
            f"工具 {tool} 没有登记安全策略，已拒绝执行。"
            f"请在 app/tools/policy.py 的 builtin_policies() 里为它声明一条 Policy。",
        )

    # 2. 会话级禁用：用户在界面上关掉的能力
    if tool in ctx.deny_tools:
        return Decision(Level.DENY, f"当前会话已禁用工具 {tool}")

    # 3. 默认关闭的能力（如联网）：未开启时拒绝，并告诉用户怎么开
    if policy.off_by_default and not _feature_enabled(tool):
        return Decision(
            Level.DENY,
            f"工具 {tool} 默认关闭。开启方法：在后端 .env 里设置 APP_ALLOW_WEB_TOOLS=true 后重启后端",
        )

    # 4. 路径校验：对每个待校验路径走一遍统一的路径策略
    op = policy.path_op or policy.kind.value
    for p in action.paths:
        reason = path_decision(p, op, roots=ctx.workspace_roots or None)
        if reason:
            return Decision(Level.DENY, reason)

    # decide() 里，EXEC 类操作先看会话白名单
    if action.kind is Kind.EXEC and session is not None:
        head = " ".join(action.target.split()[:2])   # 取 "git status" 这样的前缀
        if head in session.allowed_commands:
            return Decision(Level.ALLOW)

    # 5. 等级：显式等级 > 显式要求确认 > 该类型的默认等级
    if policy.default_level is not None:
        level = policy.default_level
    elif policy.require_confirm:
        level = Level.ASK
    else:
        level = _DEFAULT_LEVEL.get(action.kind, Level.DENY)

    # 5.1 子 agent 红线（ARCH-7）：写盘 / 执行命令**不允许免确认**。
    # 只在"本来是 ALLOW"时升级为 ASK；DENY 保持 DENY（安全等级只能收紧、不能放松）。
    if ctx.scope == SCOPE_SUB and action.kind in _SUB_FORCED_KINDS and level is Level.ALLOW:
        level = Level.ASK

    if level is Level.ALLOW:
        return Decision(Level.ALLOW)

    title = f"确认{_KIND_LABEL.get(action.kind, '操作')}"
    reason = action.detail or f"AI 准备执行工具 {tool}"
    if policy.confirm_note:
        reason += f"（{policy.confirm_note}）"
    return Decision(Level.ASK, reason=reason, title=title)


# 弹窗标题里用的中文动作名
_KIND_LABEL: dict[Kind, str] = {
    Kind.READ: "读取",
    Kind.WRITE: "写入",
    Kind.EXEC: "执行命令",
    Kind.NET: "联网访问",
    Kind.MCP: "执行外部工具",
}

def _feature_enabled(tool: str) -> bool:
    """判断某个"默认关闭"的工具是否已被用户显式开启。

    :param tool: 工具名
    :return: 已开启返回 True
    """
    # 项目内：延迟导入，避免 policy 在 config 初始化前被导入
    from app.config import settings

    if tool in ("web_search", "web_fetch", "http_request"):
        # 三个联网工具共用一个开关：用户说的是"允许上网"，不是"允许用某个具体工具"
        return settings.allow_web_tools
    return False

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 统一注册入口
# --------------------------def wrapper------------------------------------------------ #
# --------------------------------------------------------------------------- #
def _resolve_ask(
    tool: str,
    action: Action,
    decision: Decision,
    session: SessionContext,
) -> bool:
    """按权限模式决定「原本要 ASK 的操作」是否放行（UX-7 三档）。

    安全不变量：本函数只在 `decide()` 已经给出 ASK 时才被调用。
    DENY（未注册工具 / 会话禁用 / 默认关闭 / 路径越界）在这一步之前就已返回，
    任何模式都不可能把 DENY 变成放行。

    另一条不变量（ARCH-7）：`scope == SCOPE_SUB` 且操作是写盘/执行时，
    **无论 permission_mode 是什么、无论工作区是否已授权**，都直接弹窗逐次确认。
    这是"子 agent 自主性高、确认不能省"的落地位置，且刻意不读任何设置键。

    :param tool: 工具名（也是授权的匹配维度之一）
    :param action: 本次操作（用于记录授权时的 target/kind，仅审计展示）
    :param decision: decide() 的裁决结果（标题与正文直接用于弹窗）
    :param session: 会话上下文（带 workspace_id / permission_mode / scope）
    :return: True=允许执行
    """
    # 项目内：延迟导入，避免 policy 在导入期就把服务层（依赖数据库）拉进来
    from app.services import approval_service
    from app.tools.tool_utils import ask_user_decide

    mode = (session.permission_mode or "ask").strip().lower()

    # ARCH-7 红线：子 agent 的写盘/执行操作**不许任何模式免确认**。
    # 这一段必须放在下面两个 bypass 之前——否则 allow 模式会把它们整体跳过。
    # 用户仍然可以逐次点"允许"，只是不能"提前一次性放行"。
    if session.scope == SCOPE_SUB and action.kind in _SUB_FORCED_KINDS:
        approved, _remember = ask_user_decide(
            tool, decision.title, f"（子 agent 操作，需逐次确认）{decision.reason}", action.preview,
            allow_remember=False,
        )
        return approved

    # 完全授权：跳过弹窗（DENY 已在更上游被拦下）
    if mode == "allow":
        return True

    # 工作区内授权：本工作区已批准过这个工具就直接放行
    if mode == "workspace" and session.workspace_id:
        if approval_service.exists(session.workspace_id, tool):
            return True

    # 其余情况仍然弹窗；workspace 模式额外给「记住本工作区」勾选
    allow_remember = mode == "workspace" and bool(session.workspace_id)
    approved, remember = ask_user_decide(
        tool, decision.title, decision.reason, action.preview,
        allow_remember=allow_remember,
    )
    if approved and remember:
        # 只有用户主动勾选才写授权；写失败不影响本次放行（approval_service 内部已吞异常）
        approval_service.upsert(
            session.workspace_id, tool, action.kind.value, action.target,
        )
    return approved


def _resolve_budget(tool: str, session: SessionContext) -> str | None:
    """预算熔断：超阈值时弹「继续 / 停止」，用户选停止则返回一段 FAIL 文案。

    为什么返回字符串而不是布尔：调用方要把它直接当成工具失败文案回给模型，
    并把这次调用记进审计（"被预算拦下"本身就是一个需要留痕的事件）。

    :param tool: 工具名（仅用于文案）
    :param session: 会话上下文（取 session_id 找本轮预算）
    :return: None=可以继续；字符串=已停止，字符串为给模型的说明
    """
    # 项目内：延迟导入，避免循环依赖
    from app.tools.budget import get_budget
    from app.tools.tool_utils import ask_budget

    budget = get_budget(session.session_id)
    if budget is None:
        return None
    if budget.blocked:
        # 用户已经在本轮里选过"停止"：不再弹窗，直接拒绝，让模型去总结
        return (
            f"用户已经选择停止本轮，工具 {tool} 未执行。"
            "请总结已完成的部分，并说明还差什么。"
        )
    hit = budget.exceeded()
    if hit is None:
        return None
    dimension, current, limit = hit
    if ask_budget(dimension, current, limit):
        # 用户选"继续"：本轮不再就这个维度提醒（防骚扰）
        budget.release(dimension)
        return None
    # 用户选"停止"：标记整轮阻塞，后续工具调用不再询问也不再执行
    budget.blocked = True
    return (
        f"用户因为预算超出（{dimension}: {current} > {limit}）选择停止本轮，"
        f"工具 {tool} 未执行。请总结已经完成的部分，并说明还差什么。"
    )


@dataclass(frozen=True)
class GuardResult:
    """一次工具调用的前置裁决结果（`guard()` 产出，`finalize()` 消费）。

    为什么单独成对象而不是返回布尔：
        blocked 之后的处理有三种（拒绝、预算停止、用户拒绝），审计里要记的
        `level` / `decision` / `reason` 也各不相同。用对象带出来，
        同步工具（make_tool）与异步工具（MCP 适配器）可以共用同一套语义。
    """

    # 非 None 表示"不要执行"，这个字符串直接作为工具返回值交给模型
    blocked: str | None
    # 裁决等级（allow/ask/deny），写审计用
    level: str
    # 用户选择（none/approved/rejected），写审计用
    decision_word: str
    # 裁决说明，写审计用
    reason: str


def guard(tool: str, action: Action, session: SessionContext | None = None) -> GuardResult:
    """工具执行前的统一关卡：裁决 → 预算 → 确认 → 写审计（仅在被拦时）。

    为什么把它从 `make_tool` 里抽出来：
        EXT-2 的 MCP 工具是**运行时才知道**的，而且只有异步实现，
        没法套 `@make_tool` 装饰器。抽出这一层后，两条路径共用完全相同的
        裁决/预算/确认语义，不会出现"MCP 工具漏了预算检查"这种分叉。

    安全不变量：DENY 一定先于预算与确认返回，任何权限模式都改不了它。

    :param tool: 工具名
    :param action: 本次操作
    :param session: 会话上下文；None 表示默认上下文
    :return: GuardResult；其 blocked 非 None 时调用方必须直接返回该文本
    """
    # 项目内：延迟导入，避免循环导入
    from app.services import audit_service
    from app.tools.session import current_session_id
    from app.tools.tool_utils import fmt

    ctx = session or SessionContext()
    decision = decide(tool, action, session=ctx)
    level = decision.level.value

    if decision.level is Level.DENY:
        audit_service.record(
            session_id=current_session_id(), tool=tool,
            kind=action.kind.value, target=action.target, detail=decision.reason,
            level=level, outcome="skipped", output=decision.reason,
        )
        return GuardResult(fmt(False, decision.reason), level, "none", decision.reason)

    # UX-9：预算熔断——先于确认弹窗（避免"先弹同意、再弹预算"两次打扰）。
    # 只拦工具调用，不拦纯文本生成；用户选"继续"后本轮该维度不再拦。
    budget_block = _resolve_budget(tool, ctx)
    if budget_block:
        audit_service.record(
            session_id=current_session_id(), tool=tool,
            kind=action.kind.value, target=action.target,
            detail="预算超限，用户选择停止", level=level, outcome="skipped",
            output=budget_block,
        )
        return GuardResult(fmt(False, budget_block), level, "none", decision.reason)

    decision_word = "none"
    if decision.level is Level.ASK:
        approved = _resolve_ask(tool, action, decision, ctx)
        decision_word = "approved" if approved else "rejected"
        if not approved:
            audit_service.record(
                session_id=current_session_id(), tool=tool,
                kind=action.kind.value, target=action.target, detail=decision.reason,
                level=level, decision=decision_word, outcome="skipped",
                output="用户拒绝",
            )
            reason = f"用户拒绝了 {tool} 操作，未做任何改动"
            return GuardResult(fmt(False, reason), level, decision_word, decision.reason)

    return GuardResult(None, level, decision_word, decision.reason)


def finalize(tool: str, action: Action, guard_result: GuardResult, result: str) -> str:
    """工具执行后的统一收尾：EXT-5 输出治理 + 写审计。

    顺序很关键：先治理、后审计——保证"模型看到的"与"审计记下来的"是同一份文本，
    否则排查时会发现日志里的输出比模型实际收到的长，误以为是模型截断的。

    :param tool: 工具名
    :param action: 本次操作
    :param guard_result: guard() 的结果（提供 level/decision/reason）
    :param result: 工具原始返回文本
    :return: 治理后的文本（调用方直接返回给模型）
    """
    # 项目内：延迟导入，避免循环导入
    from app.services import audit_service
    from app.tools.session import current_session_id

    result = _apply_output_contract(result, tool)
    audit_service.record(
        session_id=current_session_id(), tool=tool,
        kind=action.kind.value, target=action.target, detail=guard_result.reason,
        level=guard_result.level, decision=guard_result.decision_word,
        # 工具约定返回 "OK: ..." / "FAIL: ..."，据此判定结果
        outcome="ok" if result.startswith("OK:") else "fail",
        output=result,
    )
    return result


def _apply_output_contract(result: str, tool_name: str) -> str:
    """对工具输出执行 EXT-5 治理（截断 + 落盘续读），返回模型最终看到的文本。

    为什么吞掉异常：治理层是"保险丝"，它自身出问题（设置表不可读、磁盘满）不该让
    一次正常的工具调用变成失败。失败时退化为"不截断"，最坏情况与治理前一致。

    :param result: 工具函数的原始返回文本（"OK: ..." / "FAIL: ..."）
    :param tool_name: 工具名，登记"最近一次截断"供 tool_end 事件读取
    :return: 截断后的文本
    """
    # 项目内：延迟导入——output_contract 会间接读设置库，避免在模块导入期就依赖数据库
    from app.tools.output_contract import apply_output_contract
    from app.tools.session import current_session_id

    try:
        return apply_output_contract(
            result, tool_name=tool_name, session_id=current_session_id()
        ).output
    except Exception:
        return result


def _append_steer_notes(result: str, session_id: str) -> str:
    """把排队中的用户插话追加到工具结果末尾（ARCH-6 的注入点）。

    为什么注入在"工具结果"而不是"新的一条 user 消息"：
        正在跑的图只接受一次输入，中途插入新 user 消息需要改动图结构与恢复机制；
        而 ToolMessage 的内容本来就会在下一步喂给模型，把插话写进这里，
        模型看到的效果与"插了一句"完全一样，且不需要任何新机制。

    为什么放在 finalize 之后：
        截断（EXT-5）与审计都只该处理"工具自己产出的内容"。插话是用户原话，
        既不该被截断，也不该被记成工具输出——否则审计里会出现"某个工具吐出了用户的话"这种怪事。

    :param result: 已经过治理与审计的工具结果文本
    :param session_id: 会话 id（插话按会话排队）
    :return: 可能被追加了插话块的文本
    """
    # 项目内：延迟导入，避免 policy 在导入期拉起服务层
    from app.services import steering

    items = steering.drain(session_id)
    if not items:
        return result
    # 多条插话按用户发送顺序排列：模型读到的是一个连续的时间线
    lines = [f"{steering.INJECT_PREFIX} {item.content}" for item in items]
    return f"{result}\n\n" + "\n".join(lines) + f"\n{steering.INJECT_HINT}"


def make_tool(policy: Policy, action_builder: Callable[..., Action]):
    """把"声明策略"与"构造 Action"绑成一个装饰器，供工具模块叠加在 @tool 之内。

    用法（写工具时照抄这个顺序，顺序不能反）：

        @tool                                     # LangChain：把函数变成模型可调用的工具
        @make_tool(POLICIES["write_file"], build_write_action)
        def write_file(path: str, content: str, overwrite: bool = False) -> str:
            ...                                    # 函数体只管干活，不再自己判断该不该问

    装饰器做了什么（三步）：
        1. 调用 action_builder(*args, **kwargs) 得到 Action（由工具自己提供，因为它最清楚参数含义）
        2. 调 decide() 裁决；DENY → 直接返回 "FAIL: ..."；ASK → 调 ask_user() 弹窗，被拒同样返回 FAIL
        3. 允许 → 执行原函数

    注意：ask_user 内部是 LangGraph 的 interrupt()，会让工具函数**从头重跑**，
    所以工具函数体里"产生副作用之前"的部分必须都是只读的（与现有 write_file 的写法一致）。

    :param policy: 该工具的静态策略
    :param action_builder: 由参数构造 Action 的函数，签名为 (*args, **kwargs) -> Action
    :return: 装饰器
    """

    def decorator(func: Callable[..., str]) -> Callable[..., str]:
        """真正的装饰器：包一层裁决逻辑，保留原函数的元信息。"""

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            """先裁决、再执行；并记录审计（无论成功、被拒还是失败）。"""
            # 项目内：延迟导入，避免循环导入
            from app.tools.tool_utils import fmt
            from app.services import audit_service, steering
            from app.tools.session import current_session_id, current_context

            session_id = current_session_id()

            # ---- ARCH-6 步骤 1：用户在界面上点了这个工具的「取消」 ----
            # 放在 action_builder 之前：用户已经明确不要这次操作了，
            # 再去解析参数、算目标路径没有意义（也免得半截参数先报个"参数不合法"）。
            # 只影响"还没开始"的工具；已经开始执行的同步工具无法安全中断（见 steering 模块说明）。
            if steering.take_tool_cancel(session_id, func.__name__):
                audit_service.record(
                    session_id=session_id, tool=func.__name__, kind="unknown",
                    target="(用户取消)", outcome="skipped", level="ask",
                    output="用户在执行前取消了这个工具调用",
                )
                # 用 OK 前缀而不是 FAIL：这不是工具出错，模型不该重试；
                # 文案里明确要求"不要重试"，避免它在下一步又调一次同一个工具
                return fmt(True, "用户取消了这个操作，未做任何改动。请不要重试，继续后面的步骤或直接给出结论")

            try:
                action = action_builder(*args, **kwargs)
            except Exception as e:
                # 参数级校验失败：也算一次"被拒绝的操作"，记进审计
                audit_service.record(
                    session_id=session_id, tool=func.__name__, kind="unknown",
                    target="(参数不合法)", outcome="skipped", level="deny",
                    output=f"参数不合法: {e}",
                )
                return fmt(False, f"{func.__name__} 参数不合法: {e}")

            # 裁决 / 预算 / 确认 都在这一个函数里，两种工具路径语义完全一致
            result = guard(func.__name__, action, current_context())
            if result.blocked is not None:
                return result.blocked

            output = finalize(func.__name__, action, result, func(*args, **kwargs))
            # ---- ARCH-6 步骤 2：把用户在这次工具执行期间追发的指令带进模型上下文 ----
            return _append_steer_notes(output, session_id)

        # 把关卡函数挂在工具对象上：启动自检与测试靠它确认"这个工具真的过裁决"
        wrapper.__policy_action_builder__ = action_builder  # type: ignore[attr-defined]
        return wrapper

    return decorator


def verify_all_tools_registered(tools: list[Any]) -> None:
    """启动自检：交给模型的每个工具都必须登记策略，否则直接抛错（不让它上线）。

    放在 app/agents/rag_agent.py 建 agent 之前调用。这样"新增工具忘了登记"会在
    **启动时**就暴露，而不是等某天被人越权访问才发现。

    :param tools: 准备交给模型的工具对象列表
    :raises RuntimeError: 存在未登记策略的工具
    """
    missing = [getattr(t, "name", repr(t)) for t in tools
               if getattr(t, "name", "") not in POLICIES]
    if missing:
        raise RuntimeError(
            "以下工具没有在 app/tools/policy.py 登记安全策略，拒绝启动："
            + "、".join(missing)
        )