# app/tools/run_command_tool.py
"""
执行命令工具：让 Agent 能跑测试、跑类型检查、跑脚本，从而**验证自己刚才写的代码**。

这是本项目风险最高的工具，安全靠四道闸（少了任何一道都不要上线）：
    1. 命令允许列表：只放行 COMMAND_RULES 里登记的可执行文件与子命令（fail-closed）
    2. 参数数组 + shell=False：命令与参数分开传，shell 不参与解析，杜绝 ; && | 注入
    3. 工作目录囚笼：cwd 必须落在允许的工作区内，且必须由模型显式给出，不继承后端进程目录
    4. 每次调用都要用户确认（由 policy.make_tool 统一弹窗）+ 超时 + 输出截断

为什么 allowlist 而不是 denylist：
    危险命令的名字是列举不完的（rm / del / format / dd / reg / taskkill / curl | bash …），
    反过来"这个项目里安全需要跑什么"是列举得完的。宁可让用户多维护几行 COMMAND_RULES。

为什么 cwd 必填：
    后端进程的工作目录是 backend/，如果默认继承，模型以为在项目根跑 pnpm，实际会在 backend/ 跑，
    既跑不对也说不清。要求显式给出，让"在哪儿执行"成为一次可见的决策。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：subprocess 执行外部程序（run + 超时），这里刻意不用 shell=True
import subprocess
# 标准库：路径对象，解析与校验工作目录
from pathlib import Path

# LangChain 工具装饰器：把普通函数变成模型可调用的工具
from langchain_core.tools import tool

# 项目内：统一返回格式
from app.tools.tool_utils import fmt
# 项目内：权限模型——Action（描述本次操作）、Kind（操作类型）、POLICIES/make_tool（登记与强制入口）
from app.tools.policy import POLICIES, Action, Kind, make_tool

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
# 单次命令最长执行时间（单位：秒）。超时即杀进程，避免挂死把一轮对话拖住
_TIMEOUT_SECONDS = 60

# 超时的硬上限：模型传的 timeout 再大也不超过它（单位：秒）
_MAX_TIMEOUT_SECONDS = 300

# stdout / stderr 各自最多回传多少字符，超出部分截断（防止几十万行日志灌进模型上下文）
_MAX_OUTPUT_CHARS = 20_000

# 命令允许列表：{可执行文件名(小写, 不带路径) : 允许的子命令集合}
#   - 空集合 set() 表示"这个程序任何参数都放行"（仅用于本身无破坏性的程序，如 echo）
#   - 集合里的元素是该程序的**第一个参数**；不在集合里 → 拒绝
#   - 想放行整类参数（如 python -m xxx）用通配项 "*"（谨慎使用，见 COMMAND_RULES 说明）
COMMAND_RULES: dict[str, set[str]] = {
    # 只读的版本控制查询：允许看，不允许 commit / push / reset / clean
    "git": {"status", "diff", "log", "show", "grep", "ls-files", "rev-parse", "branch", "describe"},
    # 类型检查与测试：本项目的两条自检命令（见 README 的 pnpm 脚本）
    "pnpm": {"typecheck", "test:backend", "run", "exec", "-v", "--version"},
    "npm": {"run", "-v", "--version"},
    # Python 侧：只允许 pytest 与"通过 -m 运行模块"，不允许 -c 直接执行代码
    "uv": {"run", "sync", "--version", "pip"},
    "pytest": set(),
    # 纯信息类：无副作用
    "echo": set(),
    "where": set(),
    "node": {"-v", "--version"},
}

# 明确禁止的参数：即使可执行文件在允许列表内，命中这些参数也一律拒绝。
# 典型：python -c 等于任意代码执行，等价于绕过了整个允许列表。
FORBIDDEN_ARGS: frozenset[str] = frozenset({
    "-c", "--command", "-e", "--eval",        # 直接执行代码片段
    "-rf", "-fr", "--force", "--hard",        # 强制 / 递归强制
    "-delete", "-exec",                       # find 的删除与执行
    "/c", "/k", "cmd", "powershell", "pwsh",  # 借壳绕过
    "sh", "bash",                             # 同上（非 Windows）
})

# 允许作为工作目录的根（工作区）。为空时的兜底见 _resolve_cwd
# 第 06 篇会把它换成"用户在界面上选定的工作区"，这里先给出可用的默认值
DEFAULT_WORKSPACE_ROOTS: tuple[Path, ...] = ()

'''
COMMAND_RULES 是这份文档里最需要你按项目实际情况改的地方。 上面这几条是按本仓库的脚本（package.json 的 typecheck / test:backend）写的示例。 你自己的项目要跑什么，就补什么——保持"穷举安全项"的思路，不要改成黑名单。
'''

# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _resolve_workspace_roots() -> tuple[Path, ...]:
    """取当前允许的工作区根目录：优先用配置的、否则退回"项目根"。

    :return: 允许作为 cwd 的根目录元组（至少一项）
    """
    if DEFAULT_WORKSPACE_ROOTS:
        return DEFAULT_WORKSPACE_ROOTS
    # app/tools/run_command_tool.py → 向上三级 = 仓库根（project/）
    return (Path(__file__).resolve().parents[3],)


def _resolve_cwd(raw: str) -> Path:
    """把模型给的 cwd 解析成绝对路径，并确认它落在允许的工作区内。

    :param raw: 模型给的工作目录（必须是绝对路径，与其它工具保持一致）
    :return: 已 resolve 的绝对路径
    :raises ValueError: 路径为空、不是绝对路径、不存在、不是目录，或不在允许的工作区内
    """
    # 项目内：延迟导入避免与 policy 的循环依赖
    from app.tools.tool_utils import resolve_abs_path

    p = resolve_abs_path(raw)
    if not p.is_dir():
        raise ValueError(f"工作目录不存在或不是目录: {p}")
    roots = _resolve_workspace_roots()
    # 项目内：same_or_under 做"就是它或在其之下"的判断（Windows 大小写不敏感）
    from app.tools.tool_utils import same_or_under

    if not any(same_or_under(p, r) for r in roots):
        allowed = "、".join(str(r) for r in roots)
        raise ValueError(f"工作目录 {p} 不在允许的工作区内（{allowed}）")
    return p


def _check_command(command: str, args: list[str]) -> str | None:
    """校验一条命令是否在允许列表内，并检查禁用参数。

    :param command: 可执行文件名（如 "git"），允许带 .exe 后缀
    :param args: 参数数组（保持模型给的顺序）
    :return: 允许时返回 None；不允许时返回原因
    """
    name = Path(command).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    allowed_sub = COMMAND_RULES.get(name)
    if allowed_sub is None:
        known = "、".join(sorted(COMMAND_RULES))
        return f"命令 {command} 不在允许列表内（当前允许：{known}）"

    # 禁用参数：任何位置出现都拒绝。python -c 这类等于任意代码执行，必须挡住
    for a in args:
        if a.lower() in FORBIDDEN_ARGS:
            return f"参数 {a} 被禁止（它等价于直接执行任意代码或强制破坏性操作）"

    if allowed_sub:  # 非空集合才校验子命令
        if not args:
            return f"命令 {name} 需要给出子命令（允许：{'、'.join(sorted(allowed_sub))}）"
        first = args[0].lower()
        if first not in allowed_sub:
            return f"{name} 的子命令 {args[0]} 不在允许列表内（允许：{'、'.join(sorted(allowed_sub))}）"
    return None

# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #
def _clip(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """截断过长输出，并在末尾标明被截掉多少字符。

    :param text: 原始输出
    :param limit: 保留的字符数上限
    :return: 截断后的文本
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[输出被截断，共 {len(text)} 字符，只保留前 {limit} 字符]"


def _run(argv: list[str], cwd: Path, timeout: int) -> tuple[bool, str]:
    """执行命令并回收结果；超时或启动失败都返回失败而不是抛异常。

    :param argv: 命令 + 参数的完整数组（第一个元素是可执行文件）
    :param cwd: 已验证的工作目录
    :param timeout: 超时秒数（调用方已裁剪到上限内）
    :return: (是否成功, 说明文本)；说明文本里含退出码与合并后的输出
    """
    try:
        # shell=False（默认）是这里最重要的一点：不经过任何 shell 解析，
        # 因此参数里的 ; && | > 都只是普通字符，不会被当成命令分隔符
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            shell=False,
            # 用文本模式并按 UTF-8 解码，errors="replace" 兜住非 UTF-8 输出（Windows 控制台常见 GBK）
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, f"命令执行超时（超过 {timeout} 秒），已终止"
    except FileNotFoundError:
        return False, f"找不到可执行文件：{argv[0]}（请检查是否已安装并在 PATH 中）"
    except OSError as e:
        return False, f"无法启动命令：{e}"

    # stdout 与 stderr 分开标注，模型与用户都能看出哪部分是报错
    body = []
    if proc.stdout and proc.stdout.strip():
        body.append(f"[stdout]\n{_clip(proc.stdout.rstrip())}")
    if proc.stderr and proc.stderr.strip():
        body.append(f"[stderr]\n{_clip(proc.stderr.rstrip())}")
    if not body:
        body.append("(命令没有任何输出)")

    ok = proc.returncode == 0
    head = f"退出码 {proc.returncode}，工作目录 {cwd}，执行 {' '.join(argv)}"
    return ok, head + "\n" + "\n".join(body)

# --------------------------------------------------------------------------- #
# Action 构造 + 工具函数
# --------------------------------------------------------------------------- #
def build_run_action(command: str, command_args: list[str], cwd: str,
                     timeout: int = _TIMEOUT_SECONDS, purpose: str = "") -> Action:
    """把 run_command 的参数翻译成一次待裁决的执行操作。

    这里只做"形状校验"（命令是否在允许列表、cwd 是否合规），
    真正的裁决（要不要问用户、路径是否越界）交给 policy.decide。

    参数名刻意叫 command_args 而不是 args：LangChain 从函数签名生成工具入参模型时，
    会把名为 args 的字段当成 pydantic 的"可变位置参数占位字段"过滤掉，
    并留下一个 v__args 字段；结果是模型无法传入参数，工具每次调用都报
    "unexpected keyword argument 'v__args'"（2026-10 实际踩过的坑）。

    :param command: 可执行文件名
    :param command_args: 参数数组
    :param cwd: 工作目录（绝对路径）
    :param timeout: 超时秒数
    :return: 供裁决的 Action
    :raises ValueError: 命令不在允许列表、或参数命中禁用项
    :raises PermissionError: cwd 不在允许的工作区内（由 resolve_abs_path / 自身校验抛出）
    """
    reason = _check_command(command, command_args)
    if reason:
        raise ValueError(reason)
    workdir = _resolve_cwd(cwd)
    shown = " ".join([command, *command_args])
    detail = f"AI 将在 {workdir} 执行命令：{shown}"
    if purpose:
        detail += f"\n目的：{purpose}"
    return Action(
        tool="run_command",
        kind=Kind.EXEC,
        target=shown,
        paths=(workdir,),          # 交给 path_decision 按 OP_EXEC 校验工作目录
        preview={"command": shown, "cwd": str(workdir), "timeout": timeout},
        detail=detail,
    )



@tool
@make_tool(POLICIES["run_command"], build_run_action)
def run_command(command: str, command_args: list[str], cwd: str,
                timeout: int = _TIMEOUT_SECONDS, purpose: str = "") -> str:
    """在本机执行一条**已获授权**的命令，并返回退出码与输出（用于跑测试、跑类型检查、跑脚本）。

    适用："帮我跑一下测试""看看类型检查有没有过""跑个脚本统计一下"。
    不适用：需要交互输入的命令、长时间运行的服务（如 dev server）、需要联网下载的命令。
    命令必须来自允许列表（常见的安全命令已在列表内）；不在列表内的命令会直接返回 FAIL 并告知可选项。
    执行前系统会自动弹窗请用户确认，用户拒绝则返回 FAIL。

    :param command: 可执行文件名，如 "git" / "pnpm" / "pytest"（不要写整串命令）
    :param command_args: 参数数组，如 ["status", "--short"]；每个参数一个元素，不要用引号拼接
    :param cwd: 工作目录的绝对路径（必须是已存在目录，且位于允许的工作区内）
    :param timeout: 超时秒数，默认 60，上限 300
    :param purpose: 一句话说明"为什么要跑这条命令"，会显示在用户的确认弹窗里
    :return: "OK: 退出码 + 输出" 或 "FAIL: 原因"
    """
    try:
        workdir = _resolve_cwd(cwd)
        # 上限裁剪：模型给再大也不超过 _MAX_TIMEOUT_SECONDS，且不小于 1
        effective = max(1, min(int(timeout), _MAX_TIMEOUT_SECONDS))
        ok, msg = _run([command, *command_args], workdir, effective)
        if purpose:
            msg = f"目的：{purpose}\n{msg}"
        return fmt(ok, msg)
    except Exception as e:
        return fmt(False, f"执行失败: {e}")


# 本模块对外暴露的工具列表，由 app/agents/rag_agent.py 合并
RUN_TOOLS = [run_command]