"""扫描任务的业务逻辑：任务落库/查询，以及后台线程里真正的目录遍历与线程安全记账。"""
# json：把 ScanResult.to_json() 的结果字符串解析成 dict 存入 result_json 列
import json
# os：os.walk 递归遍历目录
import os
# uuid：任务没有 id 时补一个 uuid4（uuid4().hex 生成 32 位十六进制）
import uuid
# datetime：记录任务开始/结束时刻
from datetime import datetime
# pathlib.Path：把任务路径转成 Path 以便判断文件/目录
from pathlib import Path
# Thread：后台 daemon 线程跑扫描，避免阻塞接口
from threading import Thread
# Optional[...]：参数与返回值可为空的类型标注
from typing import Optional

# SQLAlchemy：select 构造任务列表查询
from sqlalchemy import select

# 项目内：数据库会话工厂（with 块正常退出自动提交）
from app.db.db_config import get_session
# 项目内：通用分页助手，把 select 变成 Page[TaskInfo]
from app.db.paginate import paginate, Page
# 项目内：文件快照，把落库的 files_json 还原成 FileInfo 列表
from app.entity.file_Info import FileInfo
# 项目内：扫描结果集合，对外返回结果时组装它
from app.entity.scan_result import ScanResult
# 项目内：任务实体（落库字段 + 内存运行时字段都在它身上）
from app.entity.scan_task import TaskInfo
# 项目内：扫描配置与"单个文件安全取信息"的函数（不做异常抛出，失败返回错误文案）
from app.services.scan_servicer import ScanOptions, _safe_get_file_info
# 项目内：任务状态枚举与进度快照
from app.entity.scan_progress import TaskState, ScanProgress

# ---------- 任务落库 ----------

# 生成任务
def save(task: TaskInfo):
    """新建任务落库：task_id 为空时补一个 uuid4，然后写入数据库并 flush（拿到自增/主键）。

    :param task: 待落库的任务对象；task_id 为空时会就地补上
    """
    if task.task_id is None:
        task.task_id = str(uuid.uuid4());

    with get_session() as session:
        session.add(task)
        session.flush()



def task_info(task_id: str):
    """按 id 查任务；查到且带 files_json 时，把文件快照还原到内存字段 _files。

    :param task_id: 任务唯一标识
    :return: TaskInfo 对象；不存在时返回 None
    """
    with get_session() as session:
        task = session.get(TaskInfo , task_id)
        if task is not None and task.files_json:
            task._files = [FileInfo.from_dict(d) for d in task.files_json]
        return task

def update_status(task_id: str , status: TaskState):
    """更新任务状态；任务不存在时抛异常。

    :param task_id: 任务唯一标识
    :param status: 目标状态（TaskState 枚举，如 RUNNING/DONE/FAILED）
    """
    with get_session() as session:
        task = session.get(TaskInfo , task_id)
        if task :
            task.status = status
            session.commit()
        else:
            raise Exception("Task not found")


def list_tasks(page_size: int , page_num: int)-> Page[TaskInfo]:
    """按创建时间倒序分页查询任务列表（最近创建的排前面）。

    :param page_size: 每页条数
    :param page_num: 页码（从 1 开始）
    :return: Page[TaskInfo]，含当页任务与总条数
    """
    with get_session() as session:
        query = select(TaskInfo).order_by(TaskInfo.created_at.desc())
        page = paginate(session, query, page=page_num, size=page_size)
        return page


# ---------- 扫描任务运行(原 TaskInfo 的业务逻辑) ----------

def task_start(task: TaskInfo) -> None:
    """启动后台扫描线程。幂等。"""
    if task._thread is not None:
        return
    task._thread = Thread(target=_run_task, args=(task,), name=f"scan-{task.task_id}", daemon=True)
    task._thread.start()


def task_cancel(task: TaskInfo) -> bool:
    """请求取消。返回是否成功发出取消信号。"""
    with task._lock:
        if task.status in (TaskState.DONE, TaskState.CANCELLED, TaskState.FAILED):
            return False
        task._cancel.set()
        return True


def task_is_finished(task: TaskInfo) -> bool:
    """判断任务是否已进入终态（DONE / CANCELLED / FAILED）。

    前端"扫描是否结束"的轮询依据；加锁读取，避免与后台线程写状态竞争。
    """
    with task._lock:
        return task.status in (TaskState.DONE, TaskState.CANCELLED, TaskState.FAILED)


def task_progress(task: TaskInfo) -> ScanProgress:
    """当前进度快照,可随时调用。"""
    with task._lock:
        return ScanProgress(
            task_id=task.task_id,
            path=task.path,
            state=task.status,
            scanned=task.scanned,
            total_bytes=task.total_bytes,
            skipped=task.skipped,
            elapsed=task.elapsed,
            error=task.error,
        )


def task_result(task: TaskInfo) -> Optional[ScanResult]:
    """完成后拿结果;未完成返回 None。"""
    with task._lock:
        if task.status not in (TaskState.DONE, TaskState.CANCELLED):
            return None
        return ScanResult(
            path=task.path,
            files=list(task._files),
            skipped=list(task._skipped_list),
        )


def task_partial_result(task: TaskInfo) -> ScanResult:
    """不论是否完成，返回当前已扫描到的部分结果快照。"""
    with task._lock:
        return ScanResult(
            path=task.path,
            files=list(task._files),
            skipped=list(task._skipped_list),
        )


def task_files_since(task: TaskInfo, from_index: int) -> tuple[list[FileInfo], int, ScanProgress]:
    """返回 from_index 之后新增的文件、新的 from_index、当前进度快照。"""
    with task._lock:
        new_files = list(task._files[from_index:])
        next_index = len(task._files)
        prog = ScanProgress(
            task_id=task.task_id,
            path=task.path,
            state=task.status,
            scanned=task.scanned,
            total_bytes=task.total_bytes,
            skipped=task.skipped,
            elapsed=task.elapsed,
            error=task.error,
        )
    return new_files, next_index, prog


def task_join(task: TaskInfo, timeout: Optional[float] = None) -> None:
    """等待后台扫描线程结束（阻塞调用方，主要用于测试或优雅关闭）。

    :param timeout: 最长等待秒数；None 表示一直等到线程结束
    """
    if task._thread:
        task._thread.join(timeout)


def save_result(task: TaskInfo) -> None:
    """扫描结束(DONE/CANCELLED/FAILED)后,把最终结果 JSON 和统计字段落库。"""
    result = task_result(task)
    with task._lock:
        task.result_json = json.loads(result.to_json()) if result else None
        task.files_json = [f.to_dict() for f in result.files] if result else None
        status, scanned, total_bytes = task.status, task.scanned, task.total_bytes
        skipped, error = task.skipped, task.error
        started_at, ended_at = task.started_at, task.ended_at
        result_json, files_json = task.result_json, task.files_json

    with get_session() as session:
        db_task = session.get(TaskInfo, task.task_id)
        if db_task is None:
            raise Exception("Task not found")
        db_task.status = status
        db_task.scanned = scanned
        db_task.total_bytes = total_bytes
        db_task.skipped = skipped
        db_task.error = error
        db_task.started_at = started_at
        db_task.ended_at = ended_at
        db_task.result_json = result_json
        db_task.files_json = files_json


# ---------- 内部:后台执行 ----------

def _run_task(task: TaskInfo) -> None:
    """后台线程主流程：置 RUNNING → 真正扫描 → 定终态 → 落库。

    异常统一兜底为 FAILED 并把异常文本写进 task.error；无论成功失败都会 save_result。
    """
    with task._lock:
        task.status = TaskState.RUNNING
        task.started_at = datetime.now()

    try:
        _do_scan(task)
    except Exception as e:                      # 兜底
        with task._lock:
            task.status = TaskState.FAILED
            task.error = f"{type(e).__name__}: {e}"
    else:
        with task._lock:
            # 若期间收到取消,状态为 CANCELLED,否则 DONE
            task.status = (
                TaskState.CANCELLED if task._cancel.is_set()
                else TaskState.DONE
            )
    finally:
        with task._lock:
            task.ended_at = datetime.now()
        save_result(task)


def _do_scan(task: TaskInfo) -> None:
    """真正的遍历：单文件直接处理，目录走 os.walk 并做剪枝/取消检查，逐个文件记账。

    :param task: 已置 RUNNING 的任务对象，读取它的 options._cancel，写入 _files/_skipped_list
    """
    opts = task.options or ScanOptions()
    root = Path(task.path)

    # 单文件
    if root.is_file():
        info, err = _safe_get_file_info(root, opts)
        _record(task, info, err)
        return

    for cur, dirs, names in os.walk(
            root,
            topdown=True,
            followlinks=False,
            onerror=lambda e: _record_skip(task, f"[目录访问失败] {e.filename}: {e.strerror}"),
    ):
        # ★ 关键:每个目录开头检查取消
        if task._cancel.is_set():
            return

        # 剪枝
        pruned = []
        for d in dirs:
            full = Path(cur) / d
            if opts.skip_hidden and d.startswith("."):
                _record_skip(task, f"[跳过隐藏目录] {full}")
                continue
            if d in opts.skip_dirs:
                _record_skip(task, f"[跳过目录] {full}")
                continue
            if opts.skip_symlink:
                try:
                    if full.is_symlink():
                        _record_skip(task, f"[跳过软链接目录] {full}")
                        continue
                except OSError as e:
                    _record_skip(task, f"[软链接检查失败] {full}: {e}")
                    continue
            pruned.append(d)
        dirs[:] = pruned

        # 处理文件
        for name in names:
            if task._cancel.is_set():
                return
            info, err = _safe_get_file_info(Path(cur) / name, opts)
            _record(task, info, err)


# ---------- 内部:线程安全记账 ----------

def _record(task: TaskInfo, info: Optional[FileInfo], err: Optional[str]) -> None:
    """把单个文件的扫描结果记进任务：成功则入文件列表并累加计数/字节，失败则入跳过列表。

    :param info: 成功时的文件快照；失败时为 None
    :param err: 失败时的可读错误文案；成功时为 None
    """
    with task._lock:
        if info is not None:
            task._files.append(info)
            task.scanned += 1
            task.total_bytes += info.file_size
        if err is not None:
            task._skipped_list.append(err)
            task.skipped += 1


def _record_skip(task: TaskInfo, msg: str) -> None:
    """只记一条"跳过了什么、为什么"的文案（隐藏目录/黑名单/软链接/目录不可读等）。

    :param msg: 形如 "[跳过隐藏目录] /abs/path" 的说明文案
    """
    with task._lock:
        task._skipped_list.append(msg)
        task.skipped += 1
