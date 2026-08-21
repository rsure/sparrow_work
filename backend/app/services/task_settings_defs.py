# app/services/task_settings_defs.py
"""复杂任务拆分（TASK）的设置声明。

按用途分组：
    拆不拆：task.decompose_enabled / task.max_subtasks
    怎么拆：task.conflict_policy
    跑完怎么验：task.verify_loop_enabled / task.verify_command
    写入安全：task.write_stale_guard（与拆分无关，但同属本模块的契约，见 doc/26 §5.3 L2）
    Phase 2：task.max_parallel_subtasks（L3 并行度）/ task.snapshot_rollback_enabled（L4 快照回滚）
             / task.replan_enabled（§5.2 动态重规划）

默认值都是"保守但有用"：开启拆分（否则功能等于不存在）、合并冲突（最安全）、
校验开关打开但**命令留空**——没有命令时校验自动跳过，不会因为默认值而报错。

Phase 2 的三个新键默认都偏保守：并行度 1（等于串行，零回归）、快照回滚开（纯本地备份，
失败时能救命）、动态重规划**关**（它会让模型改写计划，属于行为变更，必须用户主动打开）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：设置声明与注册入口
from app.services.settings_registry import SettingDef, SettingKind, register_defs


TASK_DEFS: list[SettingDef] = [
    SettingDef(
        key="task.decompose_enabled", label="自动拆分复杂任务", kind=SettingKind.BOOL, default=True,
        category="task", since="M4",
        description="是否把复杂请求自动拆成子任务逐个执行；关闭后所有请求都按单轮处理",
    ),
    SettingDef(
        key="task.max_subtasks", label="最多拆几个子任务", kind=SettingKind.INT, default=5, min=2, max=8,
        category="task", since="M4",
        description="单个任务最多拆成几个子任务；拆得太碎反而更难收敛",
    ),
    SettingDef(
        key="task.conflict_policy", label="文件冲突处理", kind=SettingKind.SELECT, default="merge",
        options=("merge", "serialize", "block"), option_labels=("合并为一个子任务", "串行并逐步校验", "不自动执行"),
        category="task", since="M4",
        description="多个子任务要写同一文件时怎么办："
                    "merge=合并成一个子任务（推荐）/ serialize=串行且逐步校验 / block=不自动执行",
    ),
    SettingDef(
        key="task.verify_loop_enabled", label="子任务完成后校验", kind=SettingKind.BOOL, default=True,
        category="task", since="M4",
        description="子任务完成后是否运行校验命令；校验失败会把报错回补给模型重试一次",
    ),
    SettingDef(
        key="task.verify_command", label="校验命令", kind=SettingKind.STRING, default="",
        category="task", since="M4",
        description="校验命令（在工作区根目录执行，如 pnpm run typecheck）；留空表示不校验",
    ),
    SettingDef(
        key="task.write_stale_guard", label="防止覆盖他人修改", kind=SettingKind.BOOL, default=True,
        category="task", since="M4",
        description="防丢失更新：读取文件后若磁盘内容被改过，再次写入会被拒绝并要求重新读取",
    ),
    SettingDef(
        key="task.max_parallel_subtasks", label="同时跑几个子任务", kind=SettingKind.INT, default=1, min=1, max=4,
        category="task", since="M5",
        description="按'会不会写同一个文件'分成若干车道，车道之间并行、车道内部串行；"
                    "1=完全串行（默认，最稳），大于 1 时真正并行执行多条车道",
    ),
    SettingDef(
        key="task.snapshot_rollback_enabled", label="失败时回滚文件", kind=SettingKind.BOOL, default=True,
        category="task", since="M5",
        description="每个子任务开始前把它声明要改的文件备份到应用数据目录；"
                    "该子任务失败或校验不通过时按子任务粒度还原，避免半成品留在工作区",
    ),
    SettingDef(
        key="task.replan_enabled", label="允许失败后重新规划", kind=SettingKind.BOOL, default=False,
        category="task", since="M5",
        description="某个子任务失败后，让模型重新给出一份完整计划（需要你确认后才执行）；"
                    "关闭时失败就停在原计划上",
    ),
]


def register_task_defs() -> None:
    """把任务拆分设置声明注册进全局注册表（幂等）。"""
    register_defs(TASK_DEFS)
