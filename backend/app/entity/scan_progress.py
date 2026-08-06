"""扫描进度快照：任务状态枚举 TaskState + 可序列化的 ScanProgress。"""
# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# dataclass 自动生成 __init__/__repr__，这里只用来承载一份只读快照
from dataclasses import dataclass
# Enum：把任务状态收敛成有穷、可枚举的常量集合，避免到处写裸字符串写错
from enum import Enum
# Optional[str] 标注 error 字段可以为空
from typing import Optional

# 项目内：字节数 → "1.50 KB" 的人读格式化，供进度接口返回 total_bytes_human
from app.entity.file_kind import human_size


class TaskState(str, Enum):
    """扫描任务的生命周期状态：pending → running → done / cancelled / failed。

    继承 str 后成员可直接当字符串比较与序列化（落库、返回前端都不必再 .value）。
    """

    PENDING   = "pending"     # 已创建，未开始
    RUNNING   = "running"     # 扫描中
    DONE      = "done"        # 正常完成
    CANCELLED = "cancelled"   # 用户取消
    FAILED    = "failed"      # 出错终止


@dataclass
class ScanProgress:
    """可序列化的进度快照，供接口返回"""
    # 任务 id（uuid4 的 hex 形式），前端轮询/流式接口时带回来定位任务
    task_id: str
    # 本次扫描的根路径（绝对路径字符串）
    path: str
    # 当前状态，取值见 TaskState
    state: TaskState
    scanned: int          # 已扫文件数
    total_bytes: int      # 已扫字节数
    skipped: int          # 跳过数
    elapsed: float        # 已耗时秒
    error: Optional[str] = None   # 失败原因

    def to_dict(self) -> dict:
        """转成接口返回用的 dict：state 取字符串值、大小附带人读形式、耗时保留 3 位小数。"""
        return {
            "task_id": self.task_id,
            "path": self.path,
            "state": self.state.value,
            "scanned": self.scanned,
            "total_bytes": self.total_bytes,
            "total_bytes_human": human_size(self.total_bytes),
            "skipped": self.skipped,
            "elapsed": round(self.elapsed, 3),
            "error": self.error,
        }
