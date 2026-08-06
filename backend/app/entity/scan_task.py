"""扫描任务实体 TaskInfo：入库的记账字段 + 只存在于内存的运行时字段（取消信号 / 锁 / 线程 / 文件明细）。"""
# datetime：记录任务的创建、开始、结束时间
from datetime import datetime
# 线程原语：Event 作取消信号，Lock 保护共享计数，Thread 跑后台扫描
from threading import Event, Lock, Thread
# Optional[...] 标注可为空的可选字段
from typing import Optional

# SQLAlchemy 列类型与 SQL 函数：JSON 列存结果明细，func.now() 作入库时间的默认值
from sqlalchemy import String, Integer, DateTime, func, JSON
# ORM：Mapped 标注列类型、mapped_column 声明列、reconstructor 标记"从库加载之后"跑的回调
from sqlalchemy.orm import Mapped, mapped_column, reconstructor

# 项目内：SQLAlchemy 声明式基类，继承它才能把本类映射成数据库表
from app.db.db_config import Base
# 项目内：文件快照，运行时把 files_json 还原成 FileInfo 列表
from app.entity.file_Info import FileInfo
# 项目内：字节数人读格式化，供 total_bytes_human 计算字段使用
from app.entity.file_kind import human_size
# 项目内：扫描配置（是否跳过隐藏文件/目录、黑名单目录等）
from app.services.scan_servicer import ScanOptions
# 项目内：任务状态枚举（pending/running/done/cancelled/failed）
from app.entity.scan_progress import TaskState


class TaskInfo(Base):
    """
    任务记录实体,只承载数据与状态:

    - 入库字段:计数、起止时间、错误信息、最终结果,便于历史查询
    - 计算字段(elapsed/total_bytes_human):由已入库字段现算,不单独存列
    - 运行时字段(前缀 _,以及 options):仅存在于内存中,不入库,
      供 app.services.task_service 中的扫描业务逻辑读写

    扫描流程(启动/取消/查进度/取结果)等业务逻辑见 app.services.task_service。

    注:继承 Base 接入 SQLAlchemy ORM,但用普通 __init__ 赋真实默认值
    (而非依赖 mapped_column 的 default),避免把 mapped_column() 构造
    对象当成字段默认值;_cancel/_lock/_thread/_files/_skipped_list/options
    未使用 Mapped[] 标注,因此不会被映射入库,只存在于内存中。
    """
    __tablename__ = "task_info"

    # 由调用方生成后传入(如 uuid4().hex),非自增
    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 扫描根目录的绝对路径
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # pending/running/done/cancelled/failed
    status: Mapped[TaskState] = mapped_column(
        String(20), nullable=False, default=TaskState.PENDING
    )

    # 扫描记账字段
    # 成功读取到的文件数（被跳过的文件不计入）
    scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 已扫文件的字节数合计（进度条"已扫描多少 MB"用它算）
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 被跳过的文件/目录数量（隐藏、软链接、权限拒绝等都会计入）
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 失败原因（仅 status=failed 时有值），形如 "PermissionError: ..."
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 记录入库时间,与扫描实际起止时间分开
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # 扫描线程真正开始的时刻；尚未开始为 None
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 扫描结束（完成/取消/失败）的时刻；未结束为 None。end - start 即任务耗时
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 完成后的完整结果(ScanResult.to_json 反序列化),文件/跳过明细汇总于此
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 扫描到的全部文件明细(FileInfo.to_dict 列表),不同于 result_json 里仅含 top N 的 "top" 字段
    files_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    def __init__(self, task_id: str, path: str, *, options: Optional[ScanOptions] = None):
        """构造内存中的任务对象：给所有字段填真实默认值（不依赖 mapped_column 的 default），
        并把运行时字段（取消信号、锁、明细列表）准备好。

        :param task_id: 任务唯一 id，由调用方生成（如 uuid4().hex）
        :param path: 扫描根目录（会被转成字符串）
        :param options: 扫描配置，仅存在于内存、不入库；None 表示用 ScanOptions() 默认值
        """
        self.task_id = task_id
        self.path = str(path)
        self.options = options

        self.status: TaskState = TaskState.PENDING
        self.scanned = 0
        self.total_bytes = 0
        self.skipped = 0
        self.error: Optional[str] = None

        self.created_at: datetime = datetime.now()
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.result_json: Optional[dict] = None
        self.files_json: Optional[list] = None

        # ---------- 运行时字段(不入库) ----------
        self._cancel = Event()         # 取消信号
        self._lock = Lock()            # 保护共享计数
        self._thread: Optional[Thread] = None   # 后台扫描线程，未启动时为 None

        self._files: list[FileInfo] = []        # 已扫描到的文件明细（内存态，落库时转到 files_json）
        self._skipped_list: list[str] = []      # 跳过原因明细（内存态，落库时汇总进 result_json）

    @reconstructor
    def _init_on_load(self):
        """ORM 从数据库加载时不会调用 __init__,需在此补齐运行时字段(不入库)。"""
        # status 列类型是 String,从库里读出来是裸 str,不会自动还原成 TaskState,
        # 补回枚举,否则 task_progress()/task_files_since() 里 .state.value 会直接报错
        self.status = TaskState(self.status)
        self.options = None
        self._cancel = Event()
        self._lock = Lock()
        self._thread: Optional[Thread] = None
        self._files: list[FileInfo] = []
        self._skipped_list: list[str] = []

    # ---------- 计算字段(不入库) ----------

    @property
    def elapsed(self) -> float:
        """已耗时秒数"""
        if not self.started_at:
            return 0.0
        end = self.ended_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def total_bytes_human(self) -> str:
        """total_bytes 的可读形式"""
        return human_size(self.total_bytes)
