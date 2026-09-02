# app/skills/__init__.py
"""技能（Skill）系统：把「一段可复用的任务说明书」变成可发现、可调用、可管理的扩展点。

模块分工：
    loader.py    扫描目录 + 解析 SKILL.md（frontmatter + 正文）
    registry.py  进程内注册表 + 启停开关 + 系统提示词摘要
    slash.py     `/skill-name 参数` 的解析与展开

与 EXT-2（MCP）的关系：两者都是"给 Agent 增加能力"，注册表与启停开关的形状刻意做成同构，
MCP server 后续可以复用同一套"列出来 / 启用 / 注入提示词"的心智。
"""
