"""文件预览接口：GET /api/file/meta（清单）、GET /api/file/preview（文本）、GET /api/file/raw（二进制）、GET /api/file/search（工作区内按名搜索）。

为什么预览要走后端而不是 Electron 的 openPath：
    1. 渲染进程没有 Node 能力，前端读不了任意路径；
    2. 权限必须只有一处判定——Agent 工具能读什么，用户点击就应当能看什么（同一套 resolve_abs_path + path_decision）。
    3. 用 URI 协议把任意本地路径喂给渲染进程是危险做法（等于开了一个任意文件读取的口子）。
"""
# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter、Query 参数校验；Response 用于返回二进制
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

# 项目内：文件浏览服务
from app.services import file_browse_service
# 项目内：统一响应外壳
from app.schemas.common import ApiResponse

# 本模块路由，由 app/api/router.py 挂载
router = APIRouter(prefix="/file", tags=["file"])


@router.get("/catalog", summary="批量取文件清单（类型、大小、能否预览）")
async def file_catalog(
    paths: list[str] = Query(description="文件绝对路径，可重复传多个"),
) -> ApiResponse[list[dict]]:
    """把一批路径转成文件清单，供前端渲染路径片段旁的图标与提示。"""
    return ApiResponse(code=0, message="ok", data=file_browse_service.build_catalog(paths))


@router.get("/preview", summary="读取文本预览内容（有长度上限）")
async def file_preview(
    path: str = Query(description="文件绝对路径"),
    max_chars: int = Query(default=200_000, ge=1, le=500_000, description="最多返回多少字符"),
) -> ApiResponse[dict]:
    """返回预览内容或"为什么不能预览"的原因；越界路径会在这里被拒绝。"""
    return ApiResponse(code=0, message="ok",
                       data=file_browse_service.read_preview(path, max_chars=max_chars))


@router.get("/search", summary="在当前工作区里按文件名搜索（输入框 `@` 的候选）")
async def file_search(
    q: str = Query(default="", description="搜索关键词：匹配文件名或相对路径，空表示随便列一些"),
    limit: int = Query(default=20, ge=1, le=50, description="最多返回多少条候选"),
) -> ApiResponse[dict]:
    """给输入框的 `@` 候选列表用：在**当前工作区**里按文件名/相对路径模糊搜索。

    为什么只搜工作区而不是整个磁盘：与 Agent 工具能看到的范围保持一致
    （见 tool_utils.WORKSPACE_ROOTS），候选列表天然和当前项目相关，
    也避免一次 `@` 就把整块硬盘走一遍。
    """
    return ApiResponse(code=0, message="ok", data=file_browse_service.search_files(q, limit=limit))


@router.get("/raw", summary="原样返回文件内容（仅用于 <img> 等场景）")
async def file_raw(path: str = Query(description="文件绝对路径")) -> FileResponse:
    """把文件内容原样返回给浏览器，供 <img src> 直接加载图片。

    注意：这里**不做** Content-Disposition 附件下载，也不允许目录与系统路径；
    校验逻辑复用 build_catalog 的同一条路径，避免出现第二种放行规则。
    """
    # 项目内：只做路径与策略校验，不读内容（FileResponse 自己流式读）
    from app.tools.tool_utils import OP_READ, path_decision, resolve_abs_path

    p = resolve_abs_path(path)
    reason = path_decision(p, OP_READ)
    if reason or not p.is_file():
        # 403 而不是 404：让前端能区分"不存在"和"不允许"
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=reason or "不是普通文件")
    return FileResponse(str(p))