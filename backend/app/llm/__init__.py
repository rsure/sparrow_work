# app/llm/__init__.py
"""
模型接入层：把「用哪家模型」从写死的代码常量变成运行时可切换的配置。

分层与职责（详见 doc/21 ARCH-1）：
    registry.py —— 数据：有哪些供应商 / 模型 / 能力元数据（含用户自定义）
    factory.py  —— 装配：按配置造出一个可用的聊天模型；连通性测试
    state.py    —— 运行时：缓存当前模型与 Agent，设置一变自动失效重建

上层（agents/rag_agent.py、controllers/chat_controller.py）只与本包打交道，
不再直接 import langchain_deepseek —— 这样加一家供应商不需要改任何调用方。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 本包对外的稳定入口：注册表的数据结构、工厂的构建与探测、运行时的状态管理。
#刻意不在这里 import factory/state 的具体符号到__all__ 之外，
# 让调用方明确写出 "from app.llm.factory import build_chat_model" 这样的来源，便于追溯。
__all__ = [
    "registry",
    "factory",
    "state",
]