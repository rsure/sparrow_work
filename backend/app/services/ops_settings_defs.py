# app/services/ops_settings_defs.py
"""运维相关设置声明（OPS-3 / OPS-6）。

两个新键 + 一个"搬家"的键：
    ops.log_level     日志级别（改完立即生效，不用重启）
    ops.auto_update_check  桌面版启动时是否检查更新（OPS-4，桌面壳启动时读一次）
    trace.keep_days   轨迹保留天数（启动时按它清理旧数据）
    trace.enabled     原本声明在 BUILTIN_DEFS 的 advanced 分区里，这里**重新声明**到
                      diagnostic 分区——`register_defs` 明确允许后注册者覆盖，
                      目的是让"轨迹开关 + 保留天数 + 日志级别"待在同一个分区里，
                      用户不用在两个地方找同一件事
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


OPS_DEFS: list[SettingDef] = [
    SettingDef(
        key="trace.enabled", label="留存执行轨迹", kind=SettingKind.BOOL, default=True,
        category="diagnostic", since="M1",
        description="是否留存结构化的 Agent 执行轨迹（每轮的工具调用、确认、预算、耗时）。"
                    "关掉后不产生任何写入；诊断包里的轨迹也会是空的",
    ),
    SettingDef(
        key="trace.keep_days", label="轨迹保留天数", kind=SettingKind.INT, default=7, min=0, max=365,
        category="diagnostic", since="M5",
        description="轨迹保留天数：启动时自动删除更早的记录；0 表示永不清理",
    ),
    SettingDef(
        key="ops.log_level", label="日志级别", kind=SettingKind.SELECT, default="info",
        options=("debug", "info", "warning", "error"), option_labels=("调试", "常规", "警告", "仅错误"),
        category="diagnostic", since="M5",
        description="后端日志级别（写入用户数据目录下的 logs/app.log）；"
                    "排查问题时切到 debug，平时用 info",
    ),
    SettingDef(
        key="ops.auto_update_check", label="启动时检查更新", kind=SettingKind.BOOL, default=True,
        category="diagnostic", since="M5",
        description="桌面版启动后是否自动检查新版本（OPS-4）。桌面壳在启动时读这个开关，"
                    "改完下一次启动生效；关掉后仍可在「关于」页手动检查",
    ),
]


def register_ops_defs() -> None:
    """把运维设置声明注册进全局注册表（幂等）。"""
    register_defs(OPS_DEFS)
