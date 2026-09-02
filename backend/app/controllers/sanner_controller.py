"""文件扫描接口：发起扫描、SSE 推送进度与增量文件、查询结果、取消任务。

路由统一挂在 /scan 前缀下；真正的扫描线程与任务状态管理在
app.services.scan_manager 与 app.services.task_service 中，本文件只做协议适配。
"""

# 标准库：SSE 循环里 sleep 控制推送间隔，避免空转占满 CPU
import asyncio
# 标准库：把进度/文件对象序列化成 JSON 文本，放进 SSE 事件体的 data 字段
import json
# 标准库：记录客户端断开、流超时等运行日志，便于排查前端连不上的问题
import logging

# Web 框架：APIRouter 声明本模块的 /scan 路由；Request 用于检测前端是否已断开连接
# （HTTPException 为历史遗留引用，当前代码统一改用 ScanException）
from fastapi import APIRouter, HTTPException, Request
# 项目内：通用分页结果模型，/pages 接口用它包装任务列表
from app.db.paginate import Page
# 项目内：把字节数格式化成人类可读大小（如 "1.2 GB"），前端直接展示
from app.entity.file_kind import human_size
# 项目内：扫描任务实体类型，用于 get_task_by_id 的返回值类型标注
from app.entity.scan_task import TaskInfo
# 项目内：统一响应外壳，保证所有接口返回同一种 JSON 形状
from app.schemas.common import ApiResponse
# 项目内：业务异常，抛出后由 main.py 注册的全局处理器转成 JSON 错误响应
from app.schemas.scan_exception import ScanException
# 项目内：接口出入参模型（分页输出 TaskInfoOut、开始扫描 ScanStartIn、取结果 ScanStartIn2）
from app.schemas.task import TaskInfoOut, ScanStartIn, ScanStartIn2
# 项目内：扫描管理器，负责启动、登记、取消正在跑的扫描任务
from app.services.scan_manager import scan_manager
# 项目内：任务服务模块，提供任务列表/进度/结果/持久化记录等查询能力
from app.services import task_service
# 第三方：SSE 响应实现，按 Server-Sent Events 协议把事件流推给浏览器
from sse_starlette.sse import EventSourceResponse

# 本模块路由：统一前缀 /scan，在 /docs 文档里归到 scan 分组
router = APIRouter(prefix="/scan" , tags=["scan"])

# 本模块日志器：名字即模块路径，日志里能直接看出是哪一层打的
logger = logging.getLogger(__name__)

# 任务终态集合：进度流/文件流看到这些状态就说明任务已结束，可以收尾关流
TERMINAL_STATES = {"done", "cancelled", "failed"}

@router.get("/pages", response_model=ApiResponse[Page[TaskInfoOut]])
def pages(page_size: int = 10 , page_num: int = 1):
    """分页查询历史扫描任务列表，供「扫描记录」页展示。

    :param page_size: 每页条数，默认 10
    :param page_num: 页码，从 1 开始
    :return: 统一响应壳，data 为 Page 对象（含 items/total/page/size/pages/has_next 等）
    """
    page = task_service.list_tasks(page_size, page_num)
    out = Page(
        items=[TaskInfoOut.model_validate(t) for t in page.items],
        total=page.total,
        page=page.page,
        size=page.size,
    )
    return ApiResponse(code=0, message="ok", data=out)

@router.post("/start", response_model=ApiResponse[str])
def start_scan(body: ScanStartIn):
    """发起扫描，立即返回 task_id，不阻塞。

    :param body: 请求体，其中 path 为要扫描的根目录
    :return: 统一响应壳，data 为新任务的 task_id，前端用它订阅进度流
    """
    task_id = scan_manager.start_scan(body.path)
    return ApiResponse(code=0, message="ok", data=task_id)

@router.get("/stream")
async def stream_status(
    task_id: str,
    request: Request,
    interval: float = 5.0,
    max_duration: float = 3600.0,   # 最长 1 小时，防僵尸连接
):
    """以 SSE 推送任务进度：按 interval 秒轮询一次，进入终态时补发 end 事件后关流。

    场景：前端扫描页订阅该接口实时刷新进度条。
    任务 id 不存在时直接抛 ScanException(404)。

    :param task_id: 要订阅的任务 id
    :param request: 用于检测前端是否已断开，断开就停止推送、释放连接
    :param interval: 两次进度推送之间的间隔（秒），默认 5
    :param max_duration: 单条连接的最长存活时间（秒），到点强制关流，默认 1 小时
    """
    task = get_task_by_id(task_id);
    if task is None:
        raise ScanException(404, "任务不存在")

    async def event_gen():
        """异步生成器：循环产出 progress 事件；任务到达终态时再产出一条 end 事件后结束。"""
        import time  # 用单调时钟计时，不受系统时间被调整的影响
        start = time.monotonic()
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("client disconnected: %s", task_id)
                    break

                if time.monotonic() - start > max_duration:
                    logger.warning("SSE max_duration reached: %s", task_id)
                    break

                prog = task_service.task_progress(task)
                snap = prog.to_dict()

                yield {
                    "event": "progress",
                    "id": str(int(prog.elapsed * 1000)),
                    "data": json.dumps(snap, ensure_ascii=False),
                }

                if prog.state.value in TERMINAL_STATES:
                    yield {
                        "event": "end",
                        "data": json.dumps(snap, ensure_ascii=False),
                    }
                    break

                await asyncio.sleep(interval)
        finally:
            logger.info("SSE stream closed: %s", task_id)

    return EventSourceResponse(
        event_gen(),
        # 每 15 秒发一次心跳注释，防止中间代理把空闲连接掐掉
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/files/stream")
async def stream_files(
    task_id: str,
    request: Request,
    from_index: int = 0,
    interval: float = 1.0,
    max_duration: float = 3600.0,   # 最长 1 小时，防僵尸连接
):
    """增量推送扫描到的文件：每轮把 from_index 之后新增的文件以 camelCase 形状推给前端，
    文件数/大小随进度实时更新；任务终态且已推完时结束流。对已完成的历史任务，
    第一轮即可拿到全量文件，紧接着收到 end。

    :param task_id: 要订阅的任务 id，不存在时抛 ScanException(404)
    :param request: 用于检测前端是否已断开，断开就停止推送
    :param from_index: 前端已拿到的文件下标，从它之后开始增量推送（断线重连时传入已收条数）
    :param interval: 两轮推送之间的间隔（秒），默认 1，文件流要比重试进度流更勤
    :param max_duration: 单条连接的最长存活时间（秒），到点强制关流，默认 1 小时
    """
    task = get_task_by_id(task_id)
    if task is None:
        raise ScanException(404, "任务不存在")

    async def event_gen():
        """异步生成器：持续产出 files 事件（含本轮新增文件与最新计数），终态时补发 end 后结束。"""
        import time  # 用单调时钟计时，不受系统时间被调整的影响
        start = time.monotonic()
        idx = from_index
        try:
            while True:
                if await request.is_disconnected():
                    logger.info("files stream client disconnected: %s", task_id)
                    break

                if time.monotonic() - start > max_duration:
                    logger.warning("files stream max_duration reached: %s", task_id)
                    break

                new_files, idx, prog = task_service.task_files_since(task, idx)
                is_terminal = prog.state.value in TERMINAL_STATES

                if new_files or is_terminal:
                    payload = {
                        "items": [f.to_api_dict() for f in new_files],
                        "fromIndex": idx,
                        "scanned": prog.scanned,
                        "totalBytes": prog.total_bytes,
                        "totalBytesHuman": human_size(prog.total_bytes),
                        "state": prog.state.value,
                        "error": prog.error,
                    }
                    yield {
                        "event": "files",
                        "data": json.dumps(payload, ensure_ascii=False),
                    }

                if is_terminal:
                    # 收尾事件：items 清空（避免前端重复渲染最后一批），其余计数保留
                    yield {
                        "event": "end",
                        "data": json.dumps({**payload, "items": []}, ensure_ascii=False),
                    }
                    break

                await asyncio.sleep(interval)
        finally:
            logger.info("files stream closed: %s", task_id)

    return EventSourceResponse(
        event_gen(),
        # 每 15 秒发一次心跳注释，防止中间代理把空闲连接掐掉
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status", response_model=ApiResponse[dict])
def status(task_id: str):
    """轮询任务进度：返回当前进度快照。

    场景：不方便使用 SSE 的调用方（如脚本、单次查询）用它一次性取进度。
    任务 id 不存在时抛 ScanException(404)。
    """
    task = get_task_by_id(task_id);
    if task is None:
        raise ScanException(404, "任务不存在")
    return ApiResponse(code=0, message="ok", data=task_service.task_progress(task).to_dict())


@router.post("/cancel", response_model=ApiResponse[dict])
def cancel(task_id: str):
    """请求取消扫描任务。

    只是给任务打上取消标记，后台线程会在下一个检查点自行退出，
    因此返回的 cancel_requested 表示「取消请求是否被接受」，不代表任务已立即停止。
    """
    task = get_task_by_id(task_id);
    if task is None:
        raise ScanException(404, "任务不存在")
    ok = scan_manager.cancel(task_id)
    return ApiResponse(code=0, message="ok", data={"task_id": task_id, "cancel_requested": ok})


@router.get("/info", response_model=ApiResponse[dict])
def result(task_id: str):
    """取结果；任务未完成时直接返回当前进度快照，不报错。

    场景：简单的结果查询（GET 传参），前端刷新页面后想立刻拿一次当前状态。
    """
    task = get_task_by_id(task_id);
    if task is None:
        raise ScanException(404, "任务不存在")
    if not task_service.task_is_finished(task):
        data = task_service.task_progress(task).to_dict()
        return ApiResponse(code=0, message="ok", data=data)
    r = task_service.task_result(task)
    data = json.loads(r.to_json()) if r else {"state": "no_result"}
    return ApiResponse(code=0, message="ok", data=data)

@router.post("/result", response_model=ApiResponse[dict])
def files(body: ScanStartIn2):
    """取结果；任务未完成时直接返回当前已扫描到的部分数据，不报错。

    场景：结果文件可能很大，用 POST 传 task_id 避免长 URL；
    与 /info 的区别是这里在未完成时返回「部分结果」而不是进度快照。
    """
    task = get_task_by_id(body.task_id);
    if task is None:
        raise ScanException(404, "任务不存在")
    if not task_service.task_is_finished(task):
        r = task_service.task_partial_result(task)
    else:
        r = task_service.task_result(task)
    data = json.loads(r.to_json()) if r else {"state": "no_result"}
    return ApiResponse(code=0, message="ok", data=data)

def get_task_by_id(task_id:str)->TaskInfo | None:
    """按 id 查任务：先看内存中正在运行的任务，找不到再回落到数据库里的历史记录。

    :param task_id: 目标任务 id
    :return: TaskInfo 实例；内存与数据库都没有该任务时返回 None
    """
    task = scan_manager.get(task_id)
    if task is None:
        task = task_service.task_info(task_id)
    return task
