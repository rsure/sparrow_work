# app/services/policy_settings_defs.py
"""
权限与预算熔断的设置声明（UX-7 / UX-9）。

它们必须和 `policy.py` 的决策链同批落地，原因见 doc/23 §7.4 / §UX-9：
这两件事改的是同一段代码（`make_tool` 的 ASK 分支与前置检查），
分两批做等于二次动决策链、二次回归。

键的分工：
    permission.mode            三档授权（ask / workspace / allow）—— 只影响"确认弹窗"这一层
    cost.guard_enabled         预算熔断总开关（关掉需二次确认，前端负责）
    cost.max_*                 三个维度的阈值（token / 费用 / 时长）

安全不变量（不因为这里有开关而改变）：
    - DENY 永远先于模式判断：系统目录、未注册工具、默认关闭的联网工具，任何模式都拦；
    - 读不到设置时回退 `ask`（最严），绝不让"读配置失败"变成"放行"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


# 权限 + 预算相关的全部设置声明
POLICY_DEFS: list[SettingDef] = [
    # ---------------- 权限（UX-7）----------------
    SettingDef(
        key="permission.mode", label="权限模式", kind=SettingKind.SELECT, default="ask",
        category="permission", options=("ask", "workspace", "allow"), option_labels=("每次询问", "本工作区内免询问", "完全授权"), since="M5",
        description="有风险操作的授权方式：ask=每次询问（默认），"
                    "workspace=本工作区首次批准后同类操作自动放行，allow=完全授权（硬护栏仍然拦截）",
    ),
    # ---------------- 预算熔断（UX-9）----------------
    SettingDef(
        key="cost.guard_enabled", label="启用预算熔断", kind=SettingKind.BOOL, default=True,
        category="cost", since="M5",
        description="单任务预算熔断总开关：超阈值时在下一次工具调用前暂停并询问继续/停止；"
                    "关闭后不再拦截（不推荐，等于放弃成本保护）",
    ),
    SettingDef(
        key="cost.max_tokens_per_task", label="单任务 token 上限", kind=SettingKind.INT, default=500000,
        min=1000, max=5000000, category="cost", since="M5",
        description="单个任务（一轮用户请求到 done）的 token 上限；取真实 usage 累加值",
    ),
    SettingDef(
        key="cost.max_cost_per_task", label="单任务费用上限（元）", kind=SettingKind.FLOAT, default=5.0,
        min=0.0, max=1000.0, category="cost", since="M5",
        description="单个任务的费用上限（元）；按当前模型单价把 token 折算成金额",
    ),
    SettingDef(
        key="cost.max_duration_minutes", label="单任务时长上限（分钟）", kind=SettingKind.INT, default=30,
        min=1, max=600, category="cost", since="M5",
        description="单个任务的最长时长（分钟）；超时同样在下次工具调用前询问继续/停止",
    ),
]


def register_policy_defs() -> None:
    """把权限与预算的设置声明注册进全局注册表（幂等）。"""
    register_defs(POLICY_DEFS)
