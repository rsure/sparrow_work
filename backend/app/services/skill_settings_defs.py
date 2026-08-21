# app/services/skill_settings_defs.py
"""技能系统的设置声明（EXT-1）。

四个键的分工：
    skill.enabled     总开关（关掉后技能列表不再注入提示词，`/技能名` 也不生效）
    skill.auto_inject 是否把技能摘要注入系统提示词（关掉 = 只能用 `/技能名` 显式调用）
    skill.dirs        额外的技能目录（JSON 数组，支持 `~/xxx`）
    skill.disabled    按名字禁用某些技能（JSON 数组）

为什么用设置键而不是单独的配置文件：
    doc/27 的约定是"配置统一走设置体系"——声明一次，设置页自动出现、改完即时生效，
    不需要再为技能写一套读写接口。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


# 技能系统的全部设置声明
SKILL_DEFS: list[SettingDef] = [
    SettingDef(
        key="skill.enabled", label="启用技能", kind=SettingKind.BOOL, default=True,
        category="skill", since="M4",
        description="技能系统总开关：关闭后技能不再注入提示词，`/技能名` 也不会被识别",
    ),
    SettingDef(
        key="skill.auto_inject", label="自动提示可用技能", kind=SettingKind.BOOL, default=True,
        category="skill", since="M4",
        description="是否把「技能名 + 描述」注入系统提示词让模型自动判断使用；"
                    "关闭后仍可用 `/技能名` 显式调用",
    ),
    SettingDef(
        key="skill.dirs", label="技能目录", kind=SettingKind.JSON, default=[],
        category="skill", since="M4",
        description="额外的技能根目录（JSON 数组，支持 ~ 开头）；"
                    "默认目录是用户数据目录下的 app-backend/skills",
    ),
    SettingDef(
        key="skill.disabled", label="禁用的技能", kind=SettingKind.JSON, default=[],
        category="skill", since="M4",
        description="按名字禁用某些技能（JSON 数组，如 [\"my-skill\"]）；"
                    "清单里仍会显示，但不会被调用",
    ),
]


def register_skill_defs() -> None:
    """把技能设置声明注册进全局注册表（幂等）。"""
    register_defs(SKILL_DEFS)
