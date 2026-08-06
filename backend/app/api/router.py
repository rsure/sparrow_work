"""API 路由聚合：新增 controller 时在这里 include_router 即可。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# Web 框架：APIRouter 用来把各 controller 的路由汇总成一个大路由，供 main.py 挂载
from fastapi import APIRouter

# 项目内：四个 controller 模块，各自暴露一个 router
# （health=健康检查、sanner=文件扫描、rag_store=文档库检索、chat=模拟对话）
from app.controllers import chat_controller, health_controller, rag_store_controller, sanner_controller, \
    audit_controller, file_controller, setting_controller, llm_controller, skill_controller, \
    mcp_controller, diagnostic_controller, trace_controller, memory_controller, command_controller

# 总路由：main.py 只挂这一个对象，并统一加上 /api 前缀
api_router = APIRouter()
# 健康检查：GET /api/health
api_router.include_router(health_controller.router)
# 文件扫描：/api/scan/*（开始、进度 SSE、结果、取消）
api_router.include_router(sanner_controller.router)
# 文档库（RAG）：/api/rag/*（入库、检索、删除、重建索引）
api_router.include_router(rag_store_controller.router)
# 对话：/api/chat/*（SSE 流式对话、`\doc` 知识库指令、人工确认、终止、对话记录查询）
api_router.include_router(chat_controller.router)
# 审计：GET /api/audit（谁在什么时候做了什么）
api_router.include_router(audit_controller.router)
# 设置：GET/PUT /api/settings/workspace（工作区白名单）+ 统一设置体系（/settings、/settings/meta、/settings/secrets/*）
api_router.include_router(setting_controller.router)
# 设置体系的统一入口与密钥接口（与上面的 workspace 路由是两个独立 router，路径前缀相同、端点不冲突）
api_router.include_router(setting_controller.api_router)

# 文件预览：GET /api/file/*（把 AI 回答里的路径变成可预览的入口）
api_router.include_router(file_controller.router)
# 模型接入：GET /api/llm/providers（供应商与模型清单）、POST /api/llm/probe（连通性测试）
api_router.include_router(llm_controller.router)
# 技能：GET /api/skills（清单）、GET /api/skills/{name}（正文）、POST /api/skills/reload（重扫）
api_router.include_router(skill_controller.router)
# MCP：GET /api/mcp/servers（状态）、POST /api/mcp/reload（重连）、POST /api/mcp/test（试连）
api_router.include_router(mcp_controller.router)
# 诊断：GET /api/diagnostic/summary（概要）、GET /api/diagnostic/export（下载脱敏诊断包）
api_router.include_router(diagnostic_controller.router)
# 执行轨迹：GET /api/trace/sessions/{id}（按会话/轮次读 OPS-6 的结构化轨迹）
api_router.include_router(trace_controller.router)
# 工作空间记忆：/api/memory/*（列表、本地检索、检索问答、增删、手动抽取）
api_router.include_router(memory_controller.router)
# 斜杠命令：GET /api/commands（输入框敲 `/` 时的候选清单：内置命令 + 已安装技能）
api_router.include_router(command_controller.router)