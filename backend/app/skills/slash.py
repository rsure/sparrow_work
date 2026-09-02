# app/skills/slash.py
r"""`/技能名 参数` 指令的解析与展开。

为什么单独一层：
    `\doc` 是"程序直接执行"的内置指令，而 `/技能名` 的语义是
    **"把技能说明书塞进这一轮的用户消息里，让模型照着做"**。
    两者都会在聊天框里以斜杠/反斜杠开头，但执行路径完全不同，混在一个函数里最容易出错。

约定（与 Claude Code 保持一致）：
    - `/name`           只调用技能，无参数
    - `/name 参数文本`   参数原样传给技能（技能正文里可用"用户参数"指代）
    - 名字只允许 `[a-z0-9_-]`，长度 ≤64；其它形式的 `/` 开头文本（如 `/usr/bin`）不当作指令
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：正则匹配指令、dataclass 描述解析结果
import re
from dataclasses import dataclass

# 项目内：技能声明类型
from app.skills.loader import SkillSpec

# 指令前缀：行首斜杠 + 合法技能名 + 空白/结束。
# 刻意不允许 `/a/b` 这种路径形态，避免用户把 Unix 路径贴进来被误判成指令。
_SLASH_RE = re.compile(r"^/([a-z0-9][a-z0-9_-]{0,63})(?:[ \t]+(.*))?$", re.S)

# 展开后最多带多少参数：超长参数直接截断（它会被拼进用户消息，等于额外的上下文）
_MAX_ARGS_CHARS = 4_000


@dataclass(frozen=True)
class SlashCommand:
    """一次 `/技能名 参数` 解析结果。"""

    # 技能名
    name: str
    # 参数原文（可能为空串）
    args: str


def parse(text: str) -> SlashCommand | None:
    """解析一条用户输入。

    :param text: 输入框原文
    :return: SlashCommand；不是技能指令时返回 None
    """
    match = _SLASH_RE.match((text or "").strip())
    if not match:
        return None
    return SlashCommand(name=match.group(1), args=(match.group(2) or "").strip())


def expand(spec: SkillSpec, args: str) -> str:
    """把「技能 + 参数」展开成发给模型的一条用户消息。

    为什么要把正文拼进用户消息而不是系统提示词：
        系统提示词是全局的、每轮都付一遍 token；技能只在被调用时才需要正文。
        拼进这一轮的用户消息，等于"临时加了一份说明书"，成本最低且不会污染其它轮次。

    :param spec: 技能
    :param args: 用户参数
    :return: 展开后的用户消息
    """
    clean_args = (args or "").strip()[:_MAX_ARGS_CHARS]
    args_block = clean_args or "（用户没有提供额外参数，请按技能说明的默认流程执行）"
    return (
        f"用户通过 `/{spec.name}` 调用了技能「{spec.name}」。\n"
        f"请严格按下面的技能说明执行；需要调用工具时照常调用，"
        f"涉及写文件/执行命令等有风险的操作时系统仍会向用户确认。\n\n"
        f"【用户参数】\n{args_block}\n\n"
        f"【技能说明开始】\n{spec.body}\n【技能说明结束】"
    )


def unknown_hint(name: str, available: list[str]) -> str:
    """拼一条"没有这个技能"的提示，并列出可用技能。

    为什么给提示而不是当普通消息发给模型：
        打错名字时如果直接提问，模型会一本正经地猜着做，用户很难发现是名字写错了。

    :param name: 用户输入的名字
    :param available: 当前可用技能名
    :return: 展示给用户的文本
    """
    if not available:
        return (
            f"没有名为 `{name}` 的技能，当前也没有安装任何技能。\n"
            "安装方法：把带 SKILL.md 的目录放进技能目录，然后在设置页「技能」分区点「重新扫描」。"
        )
    listed = "、".join(f"/{item}" for item in available[:12])
    more = f"（共 {len(available)} 个）" if len(available) > 12 else ""
    return f"没有名为 `{name}` 的技能。可用技能：{listed}{more}。"
