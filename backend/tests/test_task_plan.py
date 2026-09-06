# tests/test_task_plan.py
"""TASK 复杂任务拆分的单元测试。

覆盖四块纯逻辑（都不依赖模型，因此跑得很快）：
    1. 启发式判定：简单请求不该多花一次调用；
    2. 计划解析：模型输出千奇百怪，解析必须宽容但**不猜测**；
    3. 冲突处置与拓扑排序：写同一文件的两个子任务绝不能并行/互相覆盖；
    4. 写前校验：读后被改过的文件必须拒绝写入。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：临时文件与当前解释器
import sys
from pathlib import Path

# 测试框架
import pytest

# 项目内：被测模块
from app.schemas.task_plan import SubTask, TaskPlan
from app.services import task_planner, task_scheduler
from app.tools import file_guard


# --------------------------------------------------------------------------- #
# 1. 启发式判定
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("message", ["你好", "现在几点", ""])
def test_looks_complex_false_for_trivial(message: str) -> None:
    """寒暄/单句短问不该进模型判定（省一次调用）。"""
    assert task_planner.looks_complex(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "扫描整个项目统计所有 TODO 并写报告",
        "把 a.py 改成异步，然后跑测试",
        "第一，读配置；第二，改端口；第三，重启",
        "帮我重构 src 下的工具模块",
        "多行需求\n第二行",
    ],
)
def test_looks_complex_true_for_multi_step(message: str) -> None:
    """多步/批量/产出类请求要进入判定。"""
    assert task_planner.looks_complex(message) is True


# --------------------------------------------------------------------------- #
# 2. 计划解析
# --------------------------------------------------------------------------- #
_VALID = """
```json
{
  "complexity": "complex",
  "reason": "要改两个文件",
  "subtasks": [
    {"id": 1, "title": "改 A", "description": "把 A 改成异步", "files": ["a.py"], "depends_on": []},
    {"id": 2, "title": "改 B", "description": "让 B 调用新的 A", "files": ["./b.py"], "depends_on": [1]}
  ]
}
```
"""


def test_parse_plan_accepts_fenced_json() -> None:
    """模型爱加 ```json 围栏，必须能剥掉再解析。"""
    plan = task_planner.parse_plan(_VALID, max_subtasks=5)

    assert plan is not None and plan.is_complex
    assert [task.title for task in plan.subtasks] == ["改 A", "改 B"]
    assert plan.subtasks[1].depends_on == [1]


def test_parse_plan_returns_none_for_garbage() -> None:
    """解析不出来就返回 None（退回单 agent），绝不"尽力猜一个计划"。"""
    assert task_planner.parse_plan("好的，我来分析一下这个需求", max_subtasks=5) is None
    assert task_planner.parse_plan("", max_subtasks=5) is None


def test_parse_plan_simple_has_no_subtasks() -> None:
    """模型判 simple 时不应带子任务（即使它顺手给了）。"""
    plan = task_planner.parse_plan(
        '{"complexity":"simple","reason":"一句话能答","subtasks":[{"id":1,"title":"x"}]}',
        max_subtasks=5,
    )
    assert plan is not None
    assert plan.is_complex is False
    assert plan.subtasks == []


def test_parse_plan_single_subtask_degrades_to_simple() -> None:
    """只拆出一个子任务等于没拆——多花的调用与展示都不值得。"""
    plan = task_planner.parse_plan(
        '{"complexity":"complex","subtasks":[{"id":1,"title":"只做一件事"}]}',
        max_subtasks=5,
    )
    assert plan is not None
    assert plan.is_complex is False


def test_parse_plan_renumbers_and_caps() -> None:
    """模型偶尔跳号/超量：必须重编号并截断，依赖里指向不存在 id 的要清掉。"""
    payload = (
        '{"complexity":"complex","subtasks":['
        '{"id":5,"title":"一","depends_on":[9]},'
        '{"id":9,"title":"二"},'
        '{"id":20,"title":"三"}'
        "]}"
    )
    plan = task_planner.parse_plan(payload, max_subtasks=2)

    assert plan is not None
    assert [task.id for task in plan.subtasks] == [1, 2]
    # 依赖 9 在截断后不存在（且原本就越界），必须被剔除，否则拓扑排序会永远等它
    assert plan.subtasks[0].depends_on == []


# --------------------------------------------------------------------------- #
# 3. 冲突检测与调度
# --------------------------------------------------------------------------- #
def _tasks(*specs: tuple[str, list[str]]) -> list[SubTask]:
    """按 (标题, 文件) 快速造子任务。"""
    return [
        SubTask(id=index + 1, title=title, description=title, files=files)
        for index, (title, files) in enumerate(specs)
    ]


def test_conflict_detects_same_file() -> None:
    """两个子任务都写同一个文件 → 同一组。"""
    tasks = _tasks(("改 A", ["a.py"]), ("也改 A", ["a.py"]), ("改 C", ["c.py"]))
    assert task_scheduler.find_conflict_groups(tasks) == [[0, 1]]


def test_conflict_ignores_path_spelling() -> None:
    """`a.py` 与 `./a.py`、大小写差异必须视为同一文件（Windows 上尤其重要）。"""
    tasks = _tasks(("改 A", ["a.py"]), ("改 A2", ["./A.PY"]))
    assert task_scheduler.find_conflict_groups(tasks) == [[0, 1]]


def test_conflict_is_transitive() -> None:
    """A∩B 有交集、B∩C 有交集 → A/B/C 应归为同一组（并查集）。"""
    tasks = _tasks(("一", ["x.py", "y.py"]), ("二", ["y.py", "z.py"]), ("三", ["z.py"]))
    assert task_scheduler.find_conflict_groups(tasks) == [[0, 1, 2]]


def test_no_files_never_conflicts() -> None:
    """只读子任务（没有 files）不参与冲突。"""
    tasks = _tasks(("读一", []), ("读二", []))
    assert task_scheduler.find_conflict_groups(tasks) == []


def test_merge_policy_combines_group() -> None:
    """merge：冲突组合并成一个子任务，文件取并集，标题标注合并。"""
    tasks = _tasks(("改 A", ["a.py"]), ("也改 A", ["a.py"]), ("改 C", ["c.py"]))
    result, groups, blocked = task_scheduler.apply_conflict_policy(tasks, "merge")

    assert blocked is False
    assert len(groups) == 1
    assert len(result) == 2
    assert "合并 2 项" in result[0].title
    assert result[0].files == ["a.py"]


def test_serialize_policy_adds_dependency() -> None:
    """serialize：保留拆分，后者依赖前者（逐步校验才能定位是哪一步改坏的）。"""
    tasks = _tasks(("改 A1", ["a.py"]), ("改 A2", ["a.py"]))
    result, _groups, blocked = task_scheduler.apply_conflict_policy(tasks, "serialize")

    assert blocked is False
    assert result[1].depends_on == [result[0].id]


def test_block_policy_reports_blocked() -> None:
    """block：不自动执行（调用方退回单 agent）。"""
    tasks = _tasks(("改 A", ["a.py"]), ("也改 A", ["a.py"]))
    _result, groups, blocked = task_scheduler.apply_conflict_policy(tasks, "block")

    assert blocked is True
    assert groups == [[0, 1]]


def test_order_follows_dependencies() -> None:
    """拓扑排序：依赖在前。"""
    tasks = [
        SubTask(id=1, title="一", depends_on=[2]),
        SubTask(id=2, title="二", depends_on=[]),
        SubTask(id=3, title="三", depends_on=[1]),
    ]
    ordered = task_scheduler.order_subtasks(tasks)
    assert [task.id for task in ordered] == [2, 1, 3]


def test_order_falls_back_on_cycle() -> None:
    """依赖成环时退化为原顺序，绝不能死循环。"""
    tasks = [
        SubTask(id=1, title="一", depends_on=[2]),
        SubTask(id=2, title="二", depends_on=[1]),
    ]
    ordered = task_scheduler.order_subtasks(tasks)
    assert [task.id for task in ordered] == [1, 2]


# --------------------------------------------------------------------------- #
# 4. 校验命令
# --------------------------------------------------------------------------- #
def test_run_verify_success_and_failure() -> None:
    """退出码 0 = 通过；非 0 = 失败并把输出带回来。"""
    ok, _ = task_planner.run_verify(f'"{sys.executable}" -c "print(1)"', None)
    assert ok is True

    passed, output = task_planner.run_verify(
        f'"{sys.executable}" -c "import sys; print(\'boom\'); sys.exit(1)"', None,
    )
    assert passed is False
    assert "boom" in output


def test_run_verify_empty_command_passes() -> None:
    """没配校验命令时视为通过（不是失败）——否则每个子任务都会记成 verify_failed。"""
    assert task_planner.run_verify("", None) == (True, "")


def test_run_verify_timeout() -> None:
    """超时必须返回失败而不是把整轮对话拖住。"""
    passed, output = task_planner.run_verify(
        f'"{sys.executable}" -c "import time; time.sleep(5)"', None, timeout=1,
    )
    assert passed is False
    assert "超时" in output


# --------------------------------------------------------------------------- #
# 5. 写前校验（防丢失更新）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def guarded_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """一个开启写前校验的临时文件。"""
    # 直接替换开关判断，避免依赖数据库里的设置值
    monkeypatch.setattr(file_guard, "_enabled", lambda: True)
    file_guard.reset_for_test()
    path = tmp_path / "a.py"
    path.write_text("v1", encoding="utf-8")
    yield path
    file_guard.reset_for_test()


def test_write_allowed_when_file_unchanged(guarded_file: Path) -> None:
    """读过、磁盘没变 → 可以写。"""
    file_guard.record_read("s1", guarded_file)
    assert file_guard.check_write("s1", guarded_file) is None


def test_write_rejected_when_changed_after_read(guarded_file: Path) -> None:
    """读过之后被改过 → 拒绝，并提示重新读（这是 lost update 的唯一防线）。"""
    file_guard.record_read("s1", guarded_file)
    guarded_file.write_text("被别人改了", encoding="utf-8")

    reason = file_guard.check_write("s1", guarded_file)
    assert reason is not None
    assert "重新读取" in reason


def test_write_updates_snapshot(guarded_file: Path) -> None:
    """写成功后要更新登记，否则紧接着的第二次写入会被自己误判成"被改过"。"""
    file_guard.record_read("s1", guarded_file)
    guarded_file.write_text("v2", encoding="utf-8")
    file_guard.record_write("s1", guarded_file)

    assert file_guard.check_write("s1", guarded_file) is None


def test_new_file_needs_no_read(guarded_file: Path, tmp_path: Path) -> None:
    """新建文件不存在"覆盖别人改动"的问题，不该被拦。"""
    assert file_guard.check_write("s1", tmp_path / "brand-new.py") is None


def test_snapshot_is_per_session(guarded_file: Path) -> None:
    """别的会话读过不算数：A 会话的登记不能让 B 会话的写入被拒。"""
    file_guard.record_read("s1", guarded_file)
    guarded_file.write_text("s1 读完之后 s2 改了", encoding="utf-8")
    assert file_guard.check_write("s2", guarded_file) is None
