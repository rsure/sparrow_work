# app/controllers/memory_controller.py
"""工作空间记忆接口（MEM）。

七个端点：
    GET    /api/memory                  列出本工作区的记忆（可按分类过滤）
    GET    /api/memory/stats            条数与分类分布（设置页顶部摘要）
    POST   /api/memory/search           **本地检索**（不调 LLM、不花 token）
    POST   /api/memory/query            **检索 + 大模型回答**（SSE 流式）
    POST   /api/memory                  手动新增一条记忆
    DELETE /api/memory/{id}             删除一条记忆
    POST   /api/memory/extract          手动对某个会话跑一次抽取（调试用）
    DELETE /api/memory?workspace_id=    清空某工作区的记忆

MEM 增强（2026-10-23）新增两个维护端点：
    POST   /api/memory/prune            立即做一次「过期淘汰 + 条数上限」整理
    POST   /api/memory/reindex          按当前向量化后端重算全部向量（换后端后必跑）

为什么 `search` 与 `query` 都要有：
    `search` 是"检索"本身——调试、前端面板、甚至别的工具都直接用它；
    `query` 是"检索 → 拼提示 → 模型回答"的完整链路，用来验证"记忆真的有用"。
    把两者混成一个接口，会让"只想看看检索结果"变成一次付费调用。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：JSON（SSE 帧）、时间戳、uuid（每次查询一个 trace id）
import json
import time
import uuid
from typing import Any

# Web 框架：路由、请求体模型、流式响应
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# 项目内：记忆服务
from app.services import memory_service


# 本模块的路由，由 app/api/router.py 挂载（统一前缀 /api）
router = APIRouter(prefix="/memory", tags=["memory"])


# --------------------------------------------------------------------------- #
# 请求体
# --------------------------------------------------------------------------- #
class MemorySearchRequest(BaseModel):
    """本地检索请求。"""

    # 工作区 id；省略时取当前 active 工作区（前端通常不传）
    workspace_id: str | None = Field(None, description="工作区 id；省略表示当前工作区")
    # 检索关键词 / 问题
    query: str = Field(..., min_length=1, max_length=2000, description="检索关键词或问题")
    # 返回条数；省略取设置里的 memory.top_k
    top_k: int | None = Field(None, ge=1, le=50, description="返回条数；省略取设置值")


class MemoryQueryRequest(MemorySearchRequest):
    """「检索 + 大模型回答」请求（比检索多一个可选的条数上限说明）。"""


class MemoryCreateRequest(BaseModel):
    """手动新增一条记忆。"""

    # 记忆正文
    content: str = Field(..., min_length=1, max_length=500, description="记忆正文（一句话）")
    # 分类：不传按 fact 处理
    category: str = Field("fact", description="preference / decision / fact / todo")
    # 重要度 1~5
    importance: int = Field(3, ge=1, le=5, description="重要度 1~5")
    # 工作区 id；省略取当前 active
    workspace_id: str | None = Field(None, description="工作区 id；省略表示当前工作区")


class MemoryExtractRequest(BaseModel):
    """手动触发抽取（调试用）。"""

    # 要抽取的会话 id
    session_id: str = Field(..., min_length=1, description="会话 id")
    # 工作区 id；省略取当前 active
    workspace_id: str | None = Field(None, description="工作区 id；省略表示当前工作区")


class MemoryMaintenanceRequest(BaseModel):
    """维护动作（整理 / 重建向量）的公共请求体。"""

    # 工作区 id；省略取当前 active
    workspace_id: str | None = Field(None, description="工作区 id；省略表示当前工作区")
    # 只对 reindex 有意义：是否连「维度已经一致」的行也重算
    force: bool = Field(False, description="reindex 时是否强制重算全部向量（默认只补缺失/维度不符的）")


# --------------------------------------------------------------------------- #
# 列表 / 统计
# --------------------------------------------------------------------------- #
@router.get("", summary="列出本工作区的记忆")
async def list_memories(
    workspace_id: str | None = Query(None, description="工作区 id；省略表示当前工作区"),
    category: str | None = Query(None, description="只看某一类：preference / decision / fact / todo"),
    limit: int = Query(100, ge=1, le=500, description="最多返回多少条"),
) -> dict:
    """按重要度、时间倒序列出记忆。

    :return: {"workspace_id", "enabled", "memories": [...]}
    """
    wid = workspace_id if workspace_id is not None else memory_service.current_workspace_id()
    return {
        "workspace_id": wid,
        "enabled": memory_service.is_enabled(),
        "memories": memory_service.list_memories(wid, category=category, limit=limit),
    }


@router.get("/stats", summary="记忆条数与分类分布")
async def memory_stats(
    workspace_id: str | None = Query(None, description="工作区 id；省略表示当前工作区"),
) -> dict:
    """给设置页顶部的摘要行用（别让它为了一个数字去拉全量列表）。

    :return: {"workspace_id", "total", "by_category"}
    """
    return memory_service.stats(workspace_id)


# --------------------------------------------------------------------------- #
# 检索 / 检索问答
# --------------------------------------------------------------------------- #
@router.post("/search", summary="本地记忆检索（不调 LLM）")
async def search_memory(req: MemorySearchRequest) -> dict:
    """在本工作区的记忆里做相似度检索。

    这条接口是**纯本地计算**：本地哈希向量 + numpy 内积，不产生任何模型调用费用。

    :param req: 检索请求
    :return: {"workspace_id", "query", "hits": [{id, content, category, importance, score}]}
    """
    wid = req.workspace_id if req.workspace_id is not None else memory_service.current_workspace_id()
    return {
        "workspace_id": wid,
        "query": req.query,
        "hits": memory_service.search(wid, req.query, req.top_k),
    }


def _frame(event: str, trace_id: str, data: dict[str, Any]) -> str:
    """把一条事件编码成 SSE 帧（与 chat 的事件格式保持一致，前端可以复用同一套解析）。

    :param event: 事件名
    :param trace_id: 本次请求的追踪 id
    :param data: 事件负载
    :return: SSE 文本帧
    """
    payload = {"trace_id": trace_id, "ts": round(time.time(), 3), **data}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


_QUERY_PROMPT = """请只根据下面这些「工作区记忆」回答用户的问题。

要求：
- 只能使用记忆里的信息；记忆里没有的就说"记忆里没有相关信息"，不要编造。
- 回答简洁，必要时用列表。
- 不要复述记忆原文，直接回答问题。

【工作区记忆】
{memories}

【问题】
{question}
"""


@router.post("/query", summary="检索记忆并用大模型回答（SSE 流式）")
async def query_memory(req: MemoryQueryRequest) -> StreamingResponse:
    """先检索记忆，再把记忆作为上下文让模型回答。

    与 `\\doc` 检索问答的结构相同：先本地取证据，再让模型基于证据作答；
    区别只是证据来自"对话记忆"而不是"导入的文档"。

    :param req: 查询请求
    :return: SSE 流（thinking / token / done / error）
    """
    trace_id = uuid.uuid4().hex[:12]
    wid = req.workspace_id if req.workspace_id is not None else memory_service.current_workspace_id()

    async def _stream():
        """生成 SSE 事件流。"""
        try:
            hits = memory_service.search(wid, req.query, req.top_k)
            yield _frame("thinking", trace_id, {
                "stage": "searching",
                "text": f"在 {len(hits)} 条相关记忆里查找…",
                "hits": len(hits),
            })
            if not hits:
                answer = "记忆里没有相关信息。"
                yield _frame("token", trace_id, {"text": answer})
                yield _frame("done", trace_id, {"answer": answer, "hits": []})
                return

            block = "\n".join(f"- [{h['category']}] {h['content']}" for h in hits)
            # 项目内：延迟导入模型（设置变化时会自动失效重建）
            from langchain_core.messages import HumanMessage

            from app.llm.state import get_model

            model = get_model()
            collected: list[str] = []
            async for chunk in model.astream([
                HumanMessage(content=_QUERY_PROMPT.format(memories=block, question=req.query))
            ]):
                text = getattr(chunk, "content", "") or ""
                if not isinstance(text, str):
                    text = str(text)
                if not text:
                    continue
                collected.append(text)
                yield _frame("token", trace_id, {"text": text})
            yield _frame("done", trace_id, {
                "answer": "".join(collected),
                "hits": hits,
            })
        except Exception as exc:  # noqa: BLE001 —— 流里抛异常会变成"连接莫名断开"，必须转成 error 帧
            yield _frame("error", trace_id, {"message": f"记忆问答失败：{exc}"})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# 写：新增 / 删除 / 抽取
# --------------------------------------------------------------------------- #
@router.post("", summary="手动新增一条记忆")
async def create_memory(req: MemoryCreateRequest) -> dict:
    """手动添加记忆（用户在设置页填一句"以后都要记住的事"）。

    重复的内容不会重复入库：`saved=false` 表示被判为重复（哈希相同或相似度过高）。

    :param req: 新增请求
    :return: {"saved": bool, "memory": {...} | None}
    """
    wid = req.workspace_id if req.workspace_id is not None else memory_service.current_workspace_id()
    memory = memory_service.add_memory(
        wid,
        req.content,
        category=req.category,
        importance=req.importance,
        source="manual",
    )
    return {"saved": memory is not None, "memory": memory}


@router.delete("/{memory_id}", summary="删除一条记忆")
async def delete_memory(memory_id: int) -> dict:
    """按 id 删除一条记忆。

    :param memory_id: 记忆 id
    :return: {"deleted": bool}
    """
    return {"deleted": memory_service.delete_memory(memory_id)}


@router.delete("", summary="清空某工作区的全部记忆")
async def clear_memories(
    workspace_id: str | None = Query(None, description="工作区 id；省略表示当前工作区"),
) -> dict:
    """清空记忆（设置页的「清空本工作区记忆」按钮）。

    :return: {"removed": 删除条数}
    """
    wid = workspace_id if workspace_id is not None else memory_service.current_workspace_id()
    return {"removed": memory_service.clear_workspace(wid)}


@router.post("/extract", summary="对某个会话手动触发一次记忆抽取（调试用）")
async def extract_memories(req: MemoryExtractRequest) -> dict:
    """对已有会话的最后一条「提问 + 回答」跑一次抽取。

    正常流程里抽取由每轮对话自动触发，这个接口用于：
        - 关闭自动抽取后想补跑一次；
        - 调整了抽取 prompt，拿历史会话验证效果。

    :param req: 抽取请求
    :return: {"stored": [...本次新增的记忆...]}
    """
    stored = await memory_service.extract_from_session(req.session_id, req.workspace_id)
    return {"stored": stored}


@router.post("/prune", summary="立即整理记忆（过期淘汰 + 条数上限）")
async def prune_memories(req: MemoryMaintenanceRequest | None = None) -> dict:
    """手动跑一次整理（设置页的「整理记忆」按钮）。

    正常流程里抽取结束会自动整理一次；这个接口用于：
        - 用户刚把保留天数/条数上限调小，想立刻看到效果；
        - 排查"为什么记忆列表里还有旧条目"（可能是还没等到下一次抽取）。

    :param req: 可选请求体（省略时按当前工作区整理）
    :return: {"workspace_id", "removed", "removed_expired", "removed_overflow", "total"}
    """
    workspace_id = req.workspace_id if req is not None else None
    return memory_service.prune(workspace_id)


@router.post("/reindex", summary="按当前向量化后端重建记忆向量")
async def reindex_memories(req: MemoryMaintenanceRequest | None = None) -> dict:
    """重算向量：换过 embedding 后端（本地 ↔ 远端）之后必须跑一次，否则旧记忆检索不到。

    为什么会"检索不到"：两套后端维度不同，相似度计算会把维度不符的行直接跳过。
    这不是报错，所以只能靠用户主动重建——因此在设置页把按钮做显眼一点。

    :param req: 可选请求体（`force=True` 时连维度一致的行也重算）
    :return: {"workspace_id", "total", "updated", "skipped", "dim", "embedding"}
    """
    workspace_id = req.workspace_id if req is not None else None
    force = bool(req.force) if req is not None else False
    return memory_service.reindex(workspace_id, force=force)
