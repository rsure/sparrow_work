# app/tools/budget.py
"""
单任务预算熔断（UX-9）：记录"这一轮已经烧了多少"，并在下一次工具调用前判断要不要拦。

为什么单独一个模块而不是塞进 SessionContext：
    SessionContext 是**决策参数**（策略层只读它做判断），而预算是**可变状态**：
    每完成一次模型调用就要累加 token/费用。把它做成按 session_id 索引的进程内对象，
    工具层（可能在别的线程）通过 session_id 拿到同一份数据，chat_controller 负责写。
    ContextVar 不适合：它按"上下文"复制，跨线程写回去不会传播。

口径（与 doc/23 UX-9 一致）：
    - "单任务" = 一轮用户请求（从 /chat/stream 到 done），不是整个会话；
    - token/费用取 provider 返回的真实 usage；费用按**当轮模型**的单价折算；
    - 只拦工具调用，不拦纯文本生成（没有工具的循环烧不了多少钱，拦它反而打断回答）。

防骚扰：
    用户在弹窗里选"继续"后，把该维度记进 `released`，本轮内不再重复拦。
    `released` 不落库、不跨轮——下一轮重新开始计。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：dataclass 描述预算状态，field 给 released 一个独立的默认集合
from dataclasses import dataclass, field
# 标准库：时间戳，用于时长维度
import time

# 兜底默认值：读不到设置时用它们（宁可保守也不放任）
_DEFAULT_MAX_TOKENS = 500_000
_DEFAULT_MAX_COST = 5.0
_DEFAULT_MAX_MINUTES = 30.0


@dataclass
class TurnBudget:
    """一轮对话的预算状态（chat_controller 每轮开始时新建，工具层只读+释放）。"""

    # 所属会话 id（与 SessionContext.session_id 一致）
    session_id: str
    # 本轮开始时间（Unix 秒），用于时长维度
    started_at: float
    # 总开关：False 时完全跳过检查（用户主动关掉了保护）
    guard_enabled: bool = True
    # token 上限（input+output）
    max_tokens: int = _DEFAULT_MAX_TOKENS
    # 费用上限（元）
    max_cost: float = _DEFAULT_MAX_COST
    # 时长上限（秒）
    max_seconds: float = _DEFAULT_MAX_MINUTES * 60.0
    # 本轮累计输入 token
    input_tokens: int = 0
    # 本轮累计输出 token
    output_tokens: int = 0
    # 本轮累计费用（元）；单价未知（如 Ollama 本地模型、自定义端点）时为 0
    cost: float = 0.0
    # 用户已经选过"继续"的维度（tokens / cost / duration），本轮内不再重复拦
    released: set[str] = field(default_factory=set)
    # 用户已经选过"停止本轮"：后续工具调用一律直接拒绝，不再弹框。
    # 不加这个标记的话，模型往往会换个工具继续试，用户会被同一个问题反复弹窗。
    blocked: bool = False

    @property
    def total_tokens(self) -> int:
        """本轮累计 token 总数（input + output）。"""
        return self.input_tokens + self.output_tokens

    def add_usage(self, usage: dict | None, price_in: float = 0.0, price_out: float = 0.0) -> None:
        """累加一次模型调用的用量与费用。

        :param usage: provider 返回的用量字典（input_tokens/output_tokens）
        :param price_in: 输入单价（元 / 百万 token）
        :param price_out: 输出单价（元 / 百万 token）
        """
        if not usage:
            return
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        # 单价按"元/百万 token"，所以这里除以 1e6
        self.cost += (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def exceeded(self) -> tuple[str, float, float] | None:
        """判断是否越过任一维度阈值（已"继续"的维度跳过）。

        :return: (维度, 当前值, 阈值)；都没超时返回 None
        """
        if not self.guard_enabled:
            return None
        if "tokens" not in self.released and self.total_tokens > self.max_tokens:
            return ("tokens", float(self.total_tokens), float(self.max_tokens))
        if "cost" not in self.released and self.cost > self.max_cost:
            return ("cost", round(self.cost, 4), self.max_cost)
        elapsed = time.time() - self.started_at
        if "duration" not in self.released and elapsed > self.max_seconds:
            return ("duration", round(elapsed / 60.0, 2), round(self.max_seconds / 60.0, 2))
        return None

    def release(self, dimension: str) -> None:
        """用户选择"继续"后释放该维度（本轮内不再拦）。

        :param dimension: tokens / cost / duration
        """
        self.released.add(dimension)


# 进程内预算表：session_id -> TurnBudget。
# 单机单用户，一轮对话只有一个活跃流，不需要锁；键里带 session_id 避免跨会话串味。
_BUDGETS: dict[str, TurnBudget] = {}


def _read_limits() -> tuple[bool, int, float, float]:
    """从设置里读总开关与三个阈值；任何一项读失败都用保守默认值。

    :return: (guard_enabled, max_tokens, max_cost, max_minutes)
    """
    # 项目内：延迟导入，避免工具层在应用启动早期就把设置库依赖带进来
    from app.services.settings_registry import get_setting

    try:
        enabled = bool(get_setting("cost.guard_enabled"))
        max_tokens = int(get_setting("cost.max_tokens_per_task"))
        max_cost = float(get_setting("cost.max_cost_per_task"))
        max_minutes = float(get_setting("cost.max_duration_minutes"))
    except Exception:
        return True, _DEFAULT_MAX_TOKENS, _DEFAULT_MAX_COST, _DEFAULT_MAX_MINUTES
    return enabled, max_tokens, max_cost, max_minutes


def start_budget(session_id: str) -> TurnBudget:
    """开启一轮的预算计时（chat_controller 在每轮开始时调用）。

    :param session_id: 会话 id
    :return: 新建的 TurnBudget（同时登记到进程内表里）
    """
    enabled, max_tokens, max_cost, max_minutes = _read_limits()
    budget = TurnBudget(
        session_id=session_id,
        started_at=time.time(),
        guard_enabled=enabled,
        max_tokens=max_tokens,
        max_cost=max_cost,
        max_seconds=max_minutes * 60.0,
    )
    _BUDGETS[session_id] = budget
    return budget


def get_budget(session_id: str) -> TurnBudget | None:
    """取某会话当前这一轮的预算状态；没有时返回 None（例如脚本直接调工具）。"""
    return _BUDGETS.get(session_id)


def add_usage(session_id: str, usage: dict | None, price_in: float = 0.0, price_out: float = 0.0) -> None:
    """把一次模型调用的用量记进本轮预算（没有活跃预算时静默忽略）。

    :param session_id: 会话 id
    :param usage: 用量字典
    :param price_in: 输入单价（元/百万 token）
    :param price_out: 输出单价（元/百万 token）
    """
    budget = _BUDGETS.get(session_id)
    if budget is not None:
        budget.add_usage(usage, price_in=price_in, price_out=price_out)


def clear_budget(session_id: str) -> None:
    """清掉某会话的预算状态（会话被删除 / 新建对话时调用）。"""
    _BUDGETS.pop(session_id, None)


def reset_for_test() -> None:
    """清空全部预算状态，供用例之间隔离。"""
    _BUDGETS.clear()
