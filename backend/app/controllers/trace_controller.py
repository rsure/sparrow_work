# app/controllers/trace_controller.py
"""执行轨迹查询（OPS-6 + ARCH-7 回放）。

三个端点：
    GET /api/trace/sessions                  —— 列出"有轨迹的会话"（回放页先挑一个会话）
    GET /api/trace/sessions/{id}/turns       —— 列出该会话的轮次（再挑一轮）
    GET /api/trace/sessions/{id}?turn_id=&limit= —— 读具体轨迹事件

为什么要有它们（而不是只靠诊断包）：
    诊断包是"打包带走"用的；排查当下问题时，直接按会话/轮次取一段结构化轨迹
    更快，也是「历史会话回放」与 B8 eval（以 trace 为数据源）的基础。
    前两个端点是回放 UI 的入口：轨迹表里只存 session_id/turn_id（都是 uuid），
    没有"挑一个"的能力，回放页根本进不去。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：路由
from fastapi import APIRouter, Query

# 项目内：对话记录服务，用来把 session_id 换成用户认得出的标题
from app.services import chat_history_service
# 项目内：轨迹服务
from app.services import trace_service


# 本模块的路由，由 app/api/router.py 挂载（统一前缀 /api）
router = APIRouter(prefix="/trace", tags=["trace"])


@router.get("/sessions", summary="列出有执行轨迹的会话（回放页入口）")
async def list_trace_sessions(
    limit: int = Query(50, ge=1, le=200, description="最多返回多少个会话，按最近有轨迹倒序"),
) -> dict:
    """列出"跑过 Agent、留下了轨迹"的会话。

    会顺手把会话标题查回来（一次 IN 查询）：只有 uuid 的话用户没法挑，
    查不到标题的会话（比如轨迹还在、对话记录已被删）退回空标题，前端显示 id 前 8 位。

    :param limit: 上限
    :return: {"sessions": [{session_id, title, event_count, turn_count, started_at, last_at}]}
    """
    rows = trace_service.list_trace_sessions(limit=limit)
    titles = chat_history_service.session_titles([row["session_id"] for row in rows])
    for row in rows:
        row["title"] = titles.get(row["session_id"], "")
    return {"sessions": rows}


@router.get("/sessions/{session_id}/turns", summary="列出某个会话的执行轮次")
async def list_trace_turns(
    session_id: str,
    limit: int = Query(50, ge=1, le=200, description="最多返回多少轮，按最近倒序"),
) -> dict:
    """列出该会话里的轮次（回放的最小单位）。

    :param session_id: 会话 id
    :param limit: 上限
    :return: {"session_id", "count", "turns": [{turn_id, event_count, mode, started_at, last_at}]}
    """
    turns = trace_service.list_turns(session_id, limit=limit)
    return {"session_id": session_id, "count": len(turns), "turns": turns}


@router.get("/sessions/{session_id}", summary="读取某个会话（可限定某一轮）的执行轨迹")
async def list_trace(
    session_id: str,
    turn_id: str | None = Query(None, description="只看某一轮；不传则返回整个会话"),
    limit: int = Query(500, ge=1, le=5000, description="最多返回多少条"),
) -> dict:
    """按顺序返回轨迹事件。

    排序保证：
        限定 turn_id 时按 `seq`（轮内步号）排序 —— 这才是"这一轮的执行顺序"；
        不限定 turn_id 时按写入顺序（id）—— 跨轮按时间即可。

    :param session_id: 会话 id
    :param turn_id: 轮次 id（可选）
    :param limit: 上限
    :return: {"session_id", "turn_id", "count", "events"}
    """
    events = trace_service.list_events(session_id, turn_id=turn_id, limit=limit)
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "count": len(events),
        "events": events,
    }
