# app/controllers/diagnostic_controller.py
"""诊断接口（OPS-3）。

两个端点：
    GET /api/diagnostic/summary   版本、库版本、日志大小、轨迹条数（前端「诊断」页展示）
    GET /api/diagnostic/export    下载诊断包（zip）

为什么导出用普通 Response 而不是 StreamingResponse：
    包体只有几百 KB（日志截断在 2MB 内），一次性读进内存更简单，
    也不会因为流式超时导致"下载了一半的 zip"（那种包打不开，用户会更困惑）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：路由与响应
from fastapi import APIRouter
from fastapi.responses import Response

# 项目内：打包逻辑
from app.services import diagnostic_service


# 本模块的路由，由 app/api/router.py 挂载（统一前缀 /api）
router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


@router.get("/summary", summary="诊断概要（版本 / 库版本 / 日志与轨迹规模）")
async def get_summary() -> dict:
    """返回诊断页需要的几个数字，不含任何敏感内容。

    :return: {version, python, platform, db_revision, log_file, log_bytes, trace_events, tables}
    """
    return diagnostic_service.summary()


@router.get("/export", summary="导出诊断包（zip，已脱敏）")
async def export_package() -> Response:
    """生成并下载诊断包。

    包内容见 `services/diagnostic_service.py` 的模块说明；**密钥不会出现在包里**
    （按键名脱敏 + 容器键整段脱敏 + 密钥形态兜底擦除）。

    :return: zip 响应
    """
    filename, payload = diagnostic_service.build_package()
    # Content-Disposition 用 filename* 兼顾非 ASCII：中文文件名在部分浏览器会乱码
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{filename}",
            # 让前端能读到文件名（默认跨域下只暴露少数几个头）
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
