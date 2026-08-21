# app/services/office_settings_defs.py
"""Office 家族解析（EXT-4）的设置声明。

五个键的来历（见 doc/22 §4.8）：
    office.enabled     总开关。关掉后 `.docx/.xlsx/.pptx` 不再走本地 Office 引擎，
                       而是回落到旧实现（docx2txt / openpyxl），行为等价于改造前。
    office.port        引擎端口。0 = 按 39099→39108 顺序自动探测；填具体值表示固定端口
                       （桌面壳拉起引擎时读同一个键，避免"壳里固定 40000、后端还在探 39099"）。
    office.timeout_ms  单次引擎调用超时。大文件可调高；超时返回已读到的部分。
    office.max_rows    单个子表最多读多少行（取代常量 MAX_XLSX_ROWS）。
    office.max_cols    单个子表最多读多少列（取代常量 MAX_XLSX_COLS）。

默认值取"能干活"的一档：开关打开（否则功能等于不存在）、端口自动、超时 15 秒、
5000 行 × 40 列（与改造前的常量一致，存量用户感知不到变化）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


# Office 引擎的全部设置声明
OFFICE_DEFS: list[SettingDef] = [
    SettingDef(
        key="office.enabled", label="用本地 Office 引擎读文档", kind=SettingKind.BOOL, default=True,
        category="office", since="M5",
        description="打开后 .docx/.doc/.xlsx/.xls/.pptx/.ppt 由本地 Office 引擎解析（能读出表格、页、方框）；"
                    "关闭或不填端口时回落到旧解析器（只读文本，图片与版式会丢）",
    ),
    SettingDef(
        key="office.port", label="Office 引擎端口", kind=SettingKind.INT, default=0, min=0, max=65535,
        category="office", since="M5",
        description="0=自动探测 39099~39108；固定端口时请与桌面壳拉起引擎用的端口一致，"
                    "否则后端探不到引擎、会一直按降级处理",
    ),
    SettingDef(
        key="office.timeout_ms", label="引擎调用超时", kind=SettingKind.INT, default=15000,
        min=1000, max=120000, category="office", since="M5",
        description="单次引擎调用的超时（毫秒）；超时不会报错，而是返回已经读到的那部分，并在结尾标注截断",
    ),
    SettingDef(
        key="office.max_rows", label="单个工作表最多读多少行", kind=SettingKind.INT, default=5000,
        min=100, max=50000, category="office", since="M5",
        description="防止一次把十万行表格读进模型上下文；超出部分截断并标注行号",
    ),
    SettingDef(
        key="office.max_cols", label="单个工作表最多读多少列", kind=SettingKind.INT, default=40,
        min=5, max=200, category="office", since="M5",
        description="作用同 office.max_rows，限制列数；宽表通常只需要前几十列就能判断内容",
    ),
]


def register_office_defs() -> None:
    """把 Office 解析的设置声明注册进全局注册表（幂等）。"""
    register_defs(OFFICE_DEFS)
