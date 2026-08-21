"""扫描任务注册表：用内存字典管理任务对象（TaskInfo），负责创建、查询、取消与回收。"""
# uuid：给每个扫描任务生成唯一 id（uuid4().hex）
import uuid
# pathlib.Path：校验路径是否绝对路径/是否存在
from pathlib import Path
# Lock：保护任务字典，多个请求线程同时读写时不至于互相踩
from threading import Lock
# Optional[TaskInfo]：get() 可能查不到任务
from typing import Optional

# 项目内：任务实体（内存里保存的就是这些对象，业务逻辑在 task_service）
from app.entity.scan_task import TaskInfo
# 项目内：带状态码的业务异常，控制器会把它转成对应 HTTP 响应
from app.schemas.scan_exception import ScanException
# 项目内：任务真正的启动/取消/进度/落库逻辑都委托给它
from app.services import task_service


class ScanManager:
    """线程安全的任务注册表。"""

    def __init__(self, max_keep: int = 100):
        """初始化注册表。

        :param max_keep: 内存中最多保留多少个任务，超限时回收最旧的已完成任务
        """
        # task_id → TaskInfo，内存中的任务表
        self._tasks: dict[str, TaskInfo] = {}
        # 保护 _tasks 的读写
        self._lock = Lock()
        # 内存保留上限（见 _gc_locked）
        self._max_keep = max_keep

    def start_scan(self, path: str, *, options=None) -> int:
        """校验路径并新建一个扫描任务（同步返回 task_id，真正的扫描在后台线程跑）。

        场景：前端点"开始扫描"时调用。
        :param path: 要扫描的绝对路径
        :param options: 扫描配置（ScanOptions），None 用默认值
        :return: 新任务的 task_id，前端后续凭它查进度
        :raises ScanException: 路径不是绝对路径（400）或不存在（404）
        """
        p = Path(path)
        if not p.is_absolute():
            raise ScanException(400, "只能输入绝对路径，如 F:\\demo")
        if not p.exists():
            raise ScanException(404, f"路径不存在: {p}")

        task_id = uuid.uuid4().hex
        task = TaskInfo(task_id=task_id, path=str(p), options=options)
        task_service.save(task)
        with self._lock:
            self._tasks[task_id] = task
            self._gc_locked()

        task_service.task_start(task)
        return task_id

    def get(self, task_id: str) -> Optional[TaskInfo]:
        """按 task_id 取任务对象；不存在时返回 None。"""
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """请求取消一个任务。

        :return: 任务不存在或已结束（无法再取消）时返回 False，成功发出取消信号返回 True
        """
        task = self.get(task_id)
        if task is None:
            return False
        return task_service.task_cancel(task)

    def _gc_locked(self) -> None:
        """防止任务无限堆积：超过上限时清掉最旧的已完成任务。"""
        if len(self._tasks) <= self._max_keep:
            return
        finished = [
            (tid, t) for tid, t in self._tasks.items()
            if task_service.task_is_finished(t)
        ]
        # 简单按完成时间排序，删最早的一批
        finished.sort(key=lambda x: task_service.task_progress(x[1]).elapsed)
        for tid, _ in finished[: len(self._tasks) - self._max_keep]:
            self._tasks.pop(tid, None)


# 全局单例
scan_manager = ScanManager()
