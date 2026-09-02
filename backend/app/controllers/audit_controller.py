"""审计查询接口：GET /api/audit。"""
# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter 建路由，Query 声明查询参数的校验规则
from fastapi import APIRouter, Query

# 项目内：审计服务
from app.services import audit_service
# 项目内：统一响应外壳
from app.schemas.common import ApiResponse

# 本模块的路由，由 app/api/router.py 挂载
router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", summary="查询工具调用审计记录（按时间倒序）")
async def list_audit(
    session_id: str | None = Query(default=None, description="只看某个会话的记录；不传表示全部"),
    tool: str | None = Query(default=None, description="只看某个工具，如 run_command"),
    limit: int = Query(default=100, ge=1, le=500, description="最多返回多少条"),
) -> ApiResponse[list[dict]]:
    """返回审计记录列表，供前端「操作记录」页展示。"""
    rows = audit_service.list_logs(session_id=session_id, tool=tool, limit=limit)
    return ApiResponse(code=0, message="ok", data=rows)