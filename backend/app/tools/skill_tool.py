# app/tools/skill_tool.py
"""技能读取工具：让模型能"按需读说明书"，而不是把全部技能正文塞进系统提示词。

两个工具：
    list_skills  列出已安装技能（名字 + 描述 + 声明会用到的工具）
    read_skill   读取某个技能的完整正文（执行前必须先读，避免凭名字猜步骤）

为什么是工具而不是只注入提示词：
    技能正文有长有短，一轮对话通常只用一个。系统提示词里只放"目录"，
    真正要用时再花一次工具调用读正文，token 成本最低，也不会让提示词随技能数量膨胀。

安全：两者都是只读，策略登记为 READ；输出仍会经过 EXT-5 的截断治理（走 @make_tool 统一出口）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# LangChain 工具装饰器：把普通函数变成模型可调用的工具
from langchain_core.tools import tool

# 项目内：权限模型（Action / Kind / POLICIES / make_tool）
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：统一返回格式
from app.tools.tool_utils import fmt
# 项目内：技能注册表
from app.skills import registry as skill_registry


def build_list_action() -> Action:
    """构造"列出技能"的只读操作（无参数、无路径）。

    :return: 供 policy.decide 裁决的 Action
    """
    return Action(
        tool="list_skills",
        kind=Kind.READ,
        target="技能清单",
        detail="读取本机已安装的技能列表",
    )


def build_read_action(name: str) -> Action:
    """构造"读取技能正文"的只读操作。

    :param name: 技能名
    :return: 供 policy.decide 裁决的 Action
    """
    return Action(
        tool="read_skill",
        kind=Kind.READ,
        target=name or "(空)",
        detail=f"读取技能 {name} 的说明正文",
    )


@tool
@make_tool(POLICIES["list_skills"], build_list_action)
def list_skills() -> str:
    """列出本机已安装的技能（名字、一句话说明、声明会用到的工具）。

    适用："有哪些技能可用""有没有能处理 Excel 的技能"。
    只看清单、不读正文；要执行某个技能前请用 read_skill 读它的完整说明。

    :return: "OK: 技能清单" 或 "FAIL: 原因"
    """
    specs = skill_registry.list_specs(include_disabled=True)
    if not specs:
        return fmt(True, "当前没有安装任何技能（技能目录里没有带 SKILL.md 的子目录）")
    lines = []
    for spec in specs:
        state = "已禁用" if skill_registry.is_disabled(spec.name) else "可用"
        tools = f"，工具：{', '.join(spec.tools)}" if spec.tools else ""
        lines.append(f"- {spec.name}（{state}）：{spec.description}{tools}")
    return fmt(True, f"共 {len(specs)} 个技能：\n" + "\n".join(lines))


@tool
@make_tool(POLICIES["read_skill"], build_read_action)
def read_skill(name: str) -> str:
    """读取某个技能的完整说明正文，然后按说明执行。

    执行技能前**先调用它**：技能的具体步骤（用哪个工具、注意什么）只写在正文里，
    凭名字猜步骤往往做错。

    :param name: 技能名（用 list_skills 查看确切名字）
    :return: "OK: 技能正文" 或 "FAIL: 原因"
    """
    spec = skill_registry.usable(name)
    if spec is None:
        available = [item.name for item in skill_registry.list_specs(include_disabled=False)]
        if not available:
            return fmt(False, f"没有名为 {name} 的可用技能；当前也没有安装任何技能")
        return fmt(False, f"没有名为 {name} 的可用技能。可用：{'、'.join(available[:12])}")
    header = f"技能 {spec.name}：{spec.description}"
    if spec.tools:
        header += f"\n声明会用到的工具：{', '.join(spec.tools)}"
    return fmt(True, f"{header}\n\n{spec.body}")


# 供 agent 层聚合：与其它 *_TOOLS 常量保持同一种形状
SKILL_TOOLS = [list_skills, read_skill]
