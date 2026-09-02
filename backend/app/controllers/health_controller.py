"""Controller 层：只做参数/协议处理，业务逻辑放 service 层。

每个 controller 模块暴露一个 `router`，由 app.api.router 统一注册。
"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# Web 框架：APIRouter 用来声明本模块的 /health 路由
from fastapi import APIRouter

# 项目内：统一响应外壳，保证本接口与其它接口返回同一种 JSON 形状
from app.schemas.common import ApiResponse
# 项目内：健康检查的返回体模型，作为 response_model 让 /docs 展示字段说明
from app.schemas.health import HealthData
# 项目内：健康检查的业务逻辑（采集进程与运行时信息），controller 只负责调用转发
from app.services.health_service import health_service

# 本模块路由：本身不带前缀，最终路径由 main.py 统一加上 settings.api_prefix（/api）
router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=ApiResponse[HealthData],
    summary="健康检查",
    description="前端首页「健康检查」按钮调用的接口，返回后端运行时状态。",
)
async def health_check() -> ApiResponse[HealthData]:
    """采集并返回后端健康快照，供前端首页「健康检查」按钮点击时调用。

    :return: 统一响应壳；code=0 表示成功，data 里是状态、版本、Python 版本、
             运行平台和已运行秒数等字段
    """
    return ApiResponse[HealthData](code=0, message="ok", data=health_service.get_health())
