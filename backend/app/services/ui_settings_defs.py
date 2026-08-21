# app/services/ui_settings_defs.py
"""
界面层设置声明（UX-2 主题定制 + UX-6 输入快捷键）。

为什么单独一个模块：
    doc/27 §9 的约定是「各模块只声明自己的设置项，不建自己的表、不开自己的接口」。
    主题与输入行为都属于「界面层」，放在这里统一声明，前端（settings store 的 meta 驱动渲染）
    与设置页都零改动即可读到；后端也不需要为它们写任何读写代码。

声明了哪些：
    theme.mode        明暗模式（dark / light / system）
    theme.preset      配色预设（决定一组基础 token）
    theme.accent      自定义主色（覆盖预设里的 --color-primary）
    theme.radius      圆角（px）
    theme.font_size   正文字号（px）
    theme.code_theme  代码高亮主题（auto 随明暗切换）
    theme.custom      高级：任意 token 覆盖（JSON，键是 CSS 变量名）
    input.enter_to_send  输入框 Enter 是发送还是换行（UX-6）

生效方式（前端 frontend/src/composables/useTheme.ts）：
    读这些键 → 合成一组 CSS 变量 → 写到 document.documentElement.style。
    因此「换肤」不需要重新构建，也不需要后端参与渲染。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


# 界面层（含主题与输入）的全部设置声明
UI_DEFS: list[SettingDef] = [
    # ---------------- 外观 / 主题（UX-2）----------------
    SettingDef(
        key="theme.mode", label="明暗模式", kind=SettingKind.SELECT, default="dark",
        category="theme", options=("dark", "light", "system"), option_labels=("深色", "浅色", "跟随系统"), since="M2",
        description="明暗模式：dark=深色，light=浅色，system=跟随系统（滚动条与原生控件同步切换）",
    ),
    SettingDef(
        key="theme.preset", label="配色预设", kind=SettingKind.SELECT, default="slate",
        category="theme", options=("slate", "midnight", "paper", "nord"), option_labels=("蓝灰（默认）", "深蓝", "纸白", "北欧"), since="M2",
        description="配色预设：slate=蓝灰（默认）、midnight=深蓝、paper=纸白、nord=北欧冷淡",
    ),
    SettingDef(
        key="theme.accent", label="主色", kind=SettingKind.STRING, default="#38bdf8",
        category="theme", since="M2",
        description="主色（十六进制，如 #38bdf8）：按钮、链接、选中态与焦点环都用它",
    ),
    SettingDef(
        key="theme.radius", label="圆角", kind=SettingKind.INT, default=14, min=0, max=24,
        category="theme", since="M2",
        description="卡片与气泡圆角（像素，0=直角，14=默认）",
    ),
    SettingDef(
        key="theme.font_size", label="正文字号", kind=SettingKind.INT, default=14, min=12, max=18,
        category="theme", since="M2",
        description="正文字号（像素）；代码块字号会按它自动减 1",
    ),
    SettingDef(
        key="theme.code_theme", label="代码高亮主题", kind=SettingKind.SELECT, default="auto",
        category="theme", options=("auto", "github-dark", "github"), option_labels=("跟随明暗", "GitHub 深色", "GitHub 浅色"), since="M2",
        description="代码高亮主题：auto=跟随明暗模式，其余为固定主题",
    ),
    SettingDef(
        key="theme.custom", label="自定义配色（高级）", kind=SettingKind.JSON, default={},
        category="theme", since="M2",
        description="高级：逐项覆盖主题 token（键为 CSS 变量名，如 {\"--color-bg\":\"#0b1120\"}）",
    ),
    # ---------------- 输入（UX-6）----------------
    SettingDef(
        key="input.enter_to_send", label="Enter 直接发送", kind=SettingKind.BOOL, default=True,
        category="input", since="M2",
        description="输入框 Enter 直接发送（关闭后 Enter 换行、需 Ctrl/⌘+Enter 发送）；"
                    "Shift+Enter 始终是换行，中文输入法选词时的 Enter 永远不会误发",
    ),
]


def register_ui_defs() -> None:
    """把界面层设置声明注册进全局注册表（幂等，重复调用覆盖同名声明）。

    在 create_app() 里调用；测试或脚本直接 import 注册表时，
    settings_registry._ensure_bootstrapped() 也会兜底装载内置声明，不会因为漏调而读不到。
    """
    register_defs(UI_DEFS)
