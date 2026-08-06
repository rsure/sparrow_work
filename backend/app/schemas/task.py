"""任务信息的 API 响应模型(与 app.entity.scan_task.TaskInfo 区分:
TaskInfo 是 ORM 实体,还带线程/锁等运行时字段,不能直接当响应体用)。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库：时间字段类型，pydantic 会自动把 datetime 序列化成 ISO8601 字符串
from datetime import datetime

# 数据校验：BaseModel 作为模型基类；ConfigDict 用来声明「可从 ORM 对象属性直接构造」
from pydantic import BaseModel, ConfigDict

# 项目内：任务状态枚举（pending/running/done/cancelled/failed）
from app.entity.scan_progress import TaskState


class ScanStartIn(BaseModel):
    """发起扫描的请求体：只需要一个目录路径。"""

    # 要扫描的根目录路径（绝对路径或相对当前工作目录）
    path: str
class ScanStartIn2(BaseModel):
    """按任务 id 取结果的请求体。"""

    # 目标扫描任务的 id，由 /scan/start 接口返回
    task_id: str


class TaskInfoOut(BaseModel):
    """扫描任务的对外展示模型：字段与前端 TaskInfo 类型一一对应，供列表页与进度页使用。"""

    # 允许用 TaskInfoOut.model_validate(orm_task) 直接从 ORM 实体按属性名取值构造
    model_config = ConfigDict(from_attributes=True)

    # 任务唯一 id，创建时生成，前端后续用它查进度、取结果、订阅流
    task_id: str
    # 本次扫描的根目录路径
    path: str
    # 任务状态（序列化后为字符串）：pending=已创建未开始 / running=扫描中 /
    # done=正常完成 / cancelled=用户取消 / failed=出错终止
    status: TaskState
    # 已扫描的文件数量，扫描过程中实时累加
    scanned: int
    # 已扫描文件的总字节数（原始值，格式化交给 total_bytes_human）
    total_bytes: int
    # 总字节数的人类可读形式，如 "1.2 GB"，由后端算好省得前端再转换
    total_bytes_human: str
    # 被跳过的条目数量，如无权限目录、软链接等无法读取的内容
    skipped: int
    # 失败原因；任务正常时为 None
    error: str | None
    # 任务创建（记录入库）时间，与真正开始扫描的 started_at 区分
    created_at: datetime
    # 任务真正开始执行的时间；排队中尚未开始时为 None
    started_at: datetime | None
    # 任务进入终态（完成/取消/失败）的时间；未结束时为 None
    ended_at: datetime | None
    # 已耗时秒数，由 started_at 与 ended_at（未结束时取当前时间）现算，不是入库字段
    elapsed: float
