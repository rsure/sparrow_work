# app/services/command_service.py
"""斜杠命令注册表（UX-8）：把「输入框里敲 `/` 能选什么」变成后端可下发的一份清单。

为什么要有注册表，而不是前端写死一份：
    技能是**磁盘上装进来的**（`<用户数据目录>/app-backend/skills` 与设置里的额外目录），
    用户随时可能新增/禁用技能。如果 `/` 列表写在前端，装完新技能必须改代码才有得选；
    放在后端，装好技能 → 刷新 → `/` 列表里自动就出现了（验收项之一）。

两类命令，执行路径完全不同（这是本文件最需要说清的一点）：
    - **内置命令**（source="builtin"）：由前端自己执行，`action` 字段告诉它做哪件事
      （doc=改走文档库链路、model=弹出模型选择、clear=新开一段对话、
      export=导出本会话、help=列出全部命令）。后端不认识它们，也不需要认识。
    - **技能命令**（source="skill"，action=""）：前端只负责把原始文本发出去，
      由后端 app/controllers/chat_controller.py 用 skills/slash.py 解析，
      把技能说明书拼进这一轮的用户消息。这是 EXT-1 已有的链路，本文件只是**登记**它。

名字冲突的约定：同名时以**内置命令**为准（前端按 source 排序，builtin 在前且优先生效）。
这样即使有人装了个叫 `help` 的技能，`/help` 也还是"列出全部命令"，不会突然变成别的东西。
"""

# 让类型注解延迟求值（PEP 563），便于直接用 list[dict]、str | None 这类新语法
from __future__ import annotations

# 标准库：dataclass 描述一条命令（不可变，模块级常量共享）
from dataclasses import dataclass

# 项目内：技能注册表（`/` 列表里技能那一半的数据源）
from app.skills import registry as skill_registry


@dataclass(frozen=True)
class CommandSpec:
    """一条斜杠命令的元信息（下发给前端渲染 `/` 列表用）。"""

    # 命令名，**不含**斜杠，例如 "doc"、"model"；技能命令就是技能名
    name: str
    # 一句话说明：列表里显示在名字右边，也是用户唯一能判断"这条是干什么的"的信息
    description: str
    # 参数提示（可为空串），例如 "[-l | -s 关键词]"；只用于占位展示，不做校验
    args_hint: str
    # 命令来源："builtin"=内置（前端执行），"skill"=技能（后端展开提示词）
    source: str
    # 前端要执行的动作；技能命令为空串（表示"原样发给后端"）。
    # 取值：doc / model / clear / export / help / ""（详见模块说明）
    action: str

    def to_dict(self) -> dict:
        """转成可 JSON 序列化的字典（接口直接下发这一份）。

        :return: {"name","description","args_hint","source","action"}
        """
        return {
            "name": self.name,
            "description": self.description,
            "args_hint": self.args_hint,
            "source": self.source,
            "action": self.action,
        }


# 内置命令清单。
# 只登记"前端真的能执行完"的命令——宁可少几条，也不要摆一排点了没反应的假按钮。
BUILTIN_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="doc",
        description="文档库：列出 / 检索 / 导入 / 删除已入库文档（与 \\doc 等价）",
        args_hint="-l 列表 / -s 关键词 / -i 路径 / -d 编号 / -h 帮助",
        source="builtin",
        action="doc",
    ),
    CommandSpec(
        name="model",
        description="查看当前模型，或切换到指定模型（只影响下一轮）",
        args_hint="不带参数=弹出选择；也可直接写 provider/model",
        source="builtin",
        action="model",
    ),
    CommandSpec(
        name="clear",
        description="清空当前会话上下文，开始一段新对话（历史记录保留在左栏）",
        args_hint="",
        source="builtin",
        action="clear",
    ),
    CommandSpec(
        name="export",
        description="导出当前会话（Markdown 便于阅读 / JSON 便于再加工）",
        args_hint="md 或 json，默认 md",
        source="builtin",
        action="export",
    ),
    CommandSpec(
        name="help",
        description="列出全部可用命令（含已安装的技能）",
        args_hint="",
        source="builtin",
        action="help",
    ),
)


def list_commands() -> list[dict]:
    """返回当前可用命令清单：内置命令在前，技能命令按名字排序在后。

    技能总开关关闭（`skill.enabled=false`）时不列技能——列出来也调不动，
    不如让 `/` 列表诚实反映"现在真的能用什么"。

    :return: [{"name","description","args_hint","source","action"}, ...]
    """
    items = [spec.to_dict() for spec in BUILTIN_COMMANDS]
    if not skill_registry.is_globally_enabled():
        return items
    for spec in skill_registry.list_specs(include_disabled=False):
        # 技能命令的 action 留空：前端只负责把原始文本发出去，展开由后端做
        items.append({
            "name": spec.name,
            "description": spec.description,
            "args_hint": "可带参数，原样传给技能",
            "source": "skill",
            "action": "",
        })
    return items
