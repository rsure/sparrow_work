"""/api/scan/result 接口自测：覆盖 task_id = 90d93e534f904794aa7bae51d68c62d6 的场景。

回归点：该接口曾直接把 ScanResult dataclass 实例塞进
response_model=ApiResponse[dict] 返回，FastAPI 校验 dict 时失败，
导致 500 Internal Server Error。现已改为 json.loads(r.to_json())。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 这类新语法
from __future__ import annotations

# 构造任务的时间戳（started_at / ended_at）
from datetime import datetime
# 构造扫描到文件的路径对象
from pathlib import Path

# 测试框架：用来声明 fixture 与断言
import pytest
# 测试客户端：在进程内直接调用 FastAPI 应用，不占用真实端口
from fastapi.testclient import TestClient

# 被测对象：项目根应用实例
from app.main import app
# 扫描结果里的单个文件实体，用来伪造「这条任务扫到了什么文件」
from app.entity.file_Info import FileInfo
# 任务状态枚举（RUNNING / DONE / CANCELLED 等），用来构造不同阶段的场景
from app.entity.scan_progress import TaskState
# 任务实体：本用例直接往 scan_manager 里塞一个假任务
from app.entity.scan_task import TaskInfo
# 扫描任务管理器单例，测试中直接操作它内部的 _tasks 字典
from app.services.scan_manager import scan_manager

# 复用同一个测试客户端
client = TestClient(app)

# 与测试用例约定的任务 ID（对应上面回归点里出问题的那条任务）
TASK_ID = "90d93e534f904794aa7bae51d68c62d6"


@pytest.fixture(autouse=True)
def _cleanup_task():
    """每个用例跑完后清掉塞进 scan_manager 的假任务，避免用例之间互相污染。"""
    # yield 之前是用例执行阶段
    yield
    # 加锁后从内部字典移除（与实际代码共用同一把锁，保证线程安全）
    with scan_manager._lock:
        scan_manager._tasks.pop(TASK_ID, None)


def _register_task(status: TaskState) -> TaskInfo:
    """往 scan_manager 里注册一个指定状态的假任务，并挂上 1 个假文件。"""
    # 建任务：只有 ID 与扫描根目录
    task = TaskInfo(task_id=TASK_ID, path="D:\\demo")
    # 设定状态（决定接口返回「部分结果」还是「完整结果」）
    task.status = status
    # 记录开始时间
    task.started_at = datetime.now()
    # 只有终态才需要结束时间
    if status in (TaskState.DONE, TaskState.CANCELLED):
        task.ended_at = datetime.now()
    # 给任务挂一个假文件，这样 total_count / total_size 才能断言出确定值
    task._files.append(
        FileInfo(
            path=Path("D:\\demo\\a.txt"),
            name="a.txt",
            # 固定 1024 字节，便于断言 total_size
            file_size=1024,
            kind="document",
            is_directory=False,
            modified_at=datetime.now(),
        )
    )
    # 登记到管理器（加锁，与实际代码一致）
    with scan_manager._lock:
        scan_manager._tasks[TASK_ID] = task
    # 返回任务对象，方便用例继续改字段
    return task


def test_result_task_not_found():
    """任务不存在时应返回 404，而不是 500 或空对象。"""
    resp = client.post("/api/scan/result", json={"task_id": "does-not-exist"})
    assert resp.status_code == 404


def test_result_task_running_returns_partial_result():
    """任务运行中时也要能返回已扫到的部分结果（前端刷新页面靠它）。"""
    _register_task(TaskState.RUNNING)

    resp = client.post("/api/scan/result", json={"task_id": TASK_ID})

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["path"] == "D:\\demo"
    assert body["data"]["total_count"] == 1


def test_result_task_done_returns_full_result():
    """任务完成后返回完整结果，且统计字段（文件数 / 总字节）正确。"""
    _register_task(TaskState.DONE)

    resp = client.post("/api/scan/result", json={"task_id": TASK_ID})

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["path"] == "D:\\demo"
    assert body["data"]["total_count"] == 1
    assert body["data"]["total_size"] == 1024
