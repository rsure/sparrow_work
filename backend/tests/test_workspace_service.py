"""工作区多profile 服务（services/workspace_service.py）与白名单联动的单元测试。

与tests/test_settings_registry.py 的约定一致：本文件用例会写真实 app.db，
因此每个用例都用 `_isolate_workspaces` fixture 在结束后把自己写的键删掉
（workspaces.list / workspaces.active_id / 迁移用的 workspace_roots），
避免污染开发者的本地工作区设置——用户自己的工作区绝不能被测试顺手抹掉。

覆盖的验收点（对应 ARCH-3 §3.4）：
    - 多工作区 CRUD、切换 active；
    - 删除 active 后顺延，不出现"没有 active"的悬空状态；
    - get_active_roots 过滤掉已不存在的目录；
    - 旧 workspace_roots 自动迁移成一个默认工作区；
    - 切换 active 后 path_decision 的白名单跟着变；
    - WORKSPACE_ROOTS 的刷新逻辑。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：临时目录，用来造"真实存在的根目录"（get_active_roots 只返回存在的目录）
from pathlib import Path
# 标准库：json 序列化，把旧键 workspace_roots 的数组落成 app_settings 里那种 JSON 文本
import json

# 测试框架：pytest.fixture 定义夹具，pytest.raises 断言异常
import pytest

# 项目内：工作区服务本体（本文件的主要被测对象）
from app.services import workspace_service
# 项目内：工作区设置键名
from app.services.workspace_settings_defs import KEY_ACTIVE_ID, KEY_WORKSPACES
# 项目内：注册表（用例前要确保工作区声明已注册，否则 get_setting 会抛 KeyError）
from app.services.settings_registry import BUILTIN_DEFS, register_defs
# 项目内：落库层，用例前后用它删键 / 恢复键
from app.services import setting_service
# 项目内：工具层白名单与其刷新函数（验证 ARCH-3 的"切换 active 后白名单跟着变"）
from app.tools import tool_utils
from app.tools.tool_utils import OP_WRITE, WORKSPACE_ROOTS, path_decision
# 项目内：会话上下文（验证 current_context 读到的是 active 工作区的根）
from app.tools.session import current_context, set_session_id


# 本文件会触碰的全部设置键：夹具结束时统一删除
_ALL_KEYS = [KEY_WORKSPACES, KEY_ACTIVE_ID, workspace_service.LEGACY_ROOTS_KEY]


@pytest.fixture(autouse=True)
def _isolate_workspaces():
    """每个用例前后都把工作区相关设置恢复到"用例前的样子"，保证用例之间与开发者环境都不受影响。

    做的事：
        1. 用例前：先把三个键的原值删掉（让每个用例从"空工作区"这种干净状态出发），
           再补注册工作区声明（避免注册表被别的用例重置掉）；
        2. 用例后：再删一遍这三个键，并恢复注册表里的内置声明。
    """
    for key in _ALL_KEYS:
        setting_service.delete_setting_value(key)
    register_defs(BUILTIN_DEFS)
    # 重新注册本层声明 + 重订白名单刷新订阅（其他用例可能调用过 reset_for_test）
    from app.services.workspace_settings_defs import register_workspace_defs

    register_workspace_defs()
    # 白名单先归零，避免上一个用例残留的白名单影响判定
    WORKSPACE_ROOTS.clear()

    yield

    for key in _ALL_KEYS:
        setting_service.delete_setting_value(key)
    WORKSPACE_ROOTS.clear()
    # 恢复内置声明：别的测试文件（如 test_settings_registry）可能依赖应用启动时的注册结果
    register_defs(BUILTIN_DEFS)


def _write_legacy_roots(paths: list[str]) -> None:
    """把旧版 ``workspace_roots`` 键按 app_settings 的存储格式写进去（供迁移用例使用）。

    :param paths: 旧版格式的根目录字符串数组
    """
    setting_service.set_setting_value(workspace_service.LEGACY_ROOTS_KEY, "json", list(paths))


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_create_workspace_returns_profile_with_generated_id(tmp_path: Path):
    """新建工作区应返回带 id 的完整对象，且第一个工作区自动成为当前工作区。"""
    profile = workspace_service.create_workspace("主项目", [str(tmp_path)])

    assert profile["id"] == "w-1"
    assert profile["name"] == "主项目"
    assert profile["roots"] == [str(tmp_path)]
    # 第一个工作区自动成为当前工作区，用户不必再手动切一次
    assert profile["active"] is True
    assert workspace_service.get_active()["id"] == "w-1"


def test_create_second_workspace_does_not_steal_active(tmp_path: Path):
    """第二个工作区不应抢走当前工作区（active 仍指向第一个）。"""
    first = workspace_service.create_workspace("主项目", [str(tmp_path)])
    second = workspace_service.create_workspace("学习笔记", [str(tmp_path)])

    assert second["id"] == "w-2"
    assert second["active"] is False
    assert workspace_service.get_active()["id"] == first["id"]


def test_update_workspace_changes_name_and_roots(tmp_path: Path):
    """更新应同时支持改名与改根目录，且只传的字段生效、没传的保持原值。"""
    created = workspace_service.create_workspace("主项目", [str(tmp_path)])

    renamed = workspace_service.update_workspace(created["id"], name="新名字")
    assert renamed["name"] == "新名字"
    assert renamed["roots"] == [str(tmp_path)], "只传 name 时roots 不该被清空"

    other = tmp_path / "sub"
    other.mkdir()
    moved = workspace_service.update_workspace(created["id"], roots=[str(other)])
    assert moved["roots"] == [str(other)]
    assert moved["name"] == "新名字", "只传 roots 时 name 不该被清空"


def test_update_workspace_unknown_id_raises():
    """更新一个不存在的工作区应抛 ValueError（controller 据此回 404）。"""
    with pytest.raises(ValueError):
        workspace_service.update_workspace("w-999", name="x")


def test_delete_workspace_removes_it(tmp_path: Path):
    """删除后列表里不该再有它，且删除不存在的 id 返回 False。"""
    created = workspace_service.create_workspace("临时", [str(tmp_path)])

    assert workspace_service.delete_workspace(created["id"]) is True
    assert workspace_service.list_workspaces() == []
    assert workspace_service.delete_workspace("w-999") is False


# --------------------------------------------------------------------------- #
# active 切换与顺延
# --------------------------------------------------------------------------- #
def test_set_active_switches_current(tmp_path: Path):
    """切换 active 后 get_active 应立刻指向新工作区。"""
    first = workspace_service.create_workspace("A", [str(tmp_path)])
    second = workspace_service.create_workspace("B", [str(tmp_path)])

    assert workspace_service.get_active()["id"] == first["id"]
    assert workspace_service.set_active(second["id"])["id"] == second["id"]
    assert workspace_service.get_active()["id"] == second["id"]


def test_set_active_unknown_id_raises(tmp_path: Path):
    """切到一个不存在的工作区应抛 ValueError，且不改动当前工作区。"""
    workspace_service.create_workspace("A", [str(tmp_path)])
    with pytest.raises(ValueError):
        workspace_service.set_active("w-999")
    assert workspace_service.get_active()["id"] == "w-1"


def test_delete_active_workspace_promotes_first_remaining(tmp_path: Path):
    """删掉当前工作区后，active 必须顺延到剩下的第一个，不能出现悬空。"""
    first = workspace_service.create_workspace("A", [str(tmp_path)])
    second = workspace_service.create_workspace("B", [str(tmp_path)])
    third = workspace_service.create_workspace("C", [str(tmp_path)])
    workspace_service.set_active(second["id"])

    workspace_service.delete_workspace(second["id"])

    # 顺延到列表里剩下的第一个（A），而不是 C——顺延规则是"列表顺序第一个"
    assert workspace_service.get_active()["id"] == first["id"]
    assert workspace_service.get_active()["id"] != third["id"]


def test_delete_last_workspace_leaves_no_active(tmp_path: Path):
    """删光所有工作区后 active 应为空串（get_active 返回 None），而不是指向不存在的 id。"""
    created = workspace_service.create_workspace("唯一", [str(tmp_path)])
    workspace_service.delete_workspace(created["id"])

    assert workspace_service.get_active() is None
    assert workspace_service.get_active_roots() == []


def test_active_id_is_authority_not_active_field(tmp_path: Path):
    """active_id 是权威值：即便profile 里的 active 字段被手工改成true，get_active 仍以 active_id 为准。"""
    created = workspace_service.create_workspace("A", [str(tmp_path)])
    second = workspace_service.create_workspace("B", [str(tmp_path)])
    workspace_service.set_active(second["id"])

    # 模拟"手工改库把 A 的 active 也写成 true"的脏数据
    dirty = [
        {"id": created["id"], "name": "A", "roots": [str(tmp_path)], "active": True},
        {"id": second["id"], "name": "B", "roots": [str(tmp_path)], "active": False},
    ]
    setting_service.set_setting_value(KEY_WORKSPACES, "json", dirty)

    assert workspace_service.get_active()["id"] == second["id"], "应认 active_id，而不是 profile.active"
    # 读出来的列表里active 标记也会被按 active_id 纠正回来
    assert [p["active"] for p in workspace_service.list_workspaces()] == [False, True]


def test_get_active_falls_back_to_first_when_active_id_dangling(tmp_path: Path):
    """active_id 指向已被删除的工作区（脏数据）时，应回落到列表第一个而不是崩掉。"""
    workspace_service.create_workspace("A", [str(tmp_path)])
    setting_service.set_setting_value(KEY_ACTIVE_ID, "string", "w-999")

    assert workspace_service.get_active()["id"] == "w-1"


# --------------------------------------------------------------------------- #
# 根目录解析
# --------------------------------------------------------------------------- #
def test_get_active_roots_filters_missing_dirs(tmp_path: Path):
    """不存在的目录必须被过滤掉（外接硬盘拔掉、目录被移动等常见场景）。"""
    existing = tmp_path / "real"
    existing.mkdir()
    missing = tmp_path / "gone"
    workspace_service.create_workspace("A", [str(existing), str(missing)])

    assert workspace_service.get_active_roots() == [existing]


def test_resolve_workspace_roots_by_id(tmp_path: Path):
    """resolve_workspace_roots 按 id 解析目录，与「哪个是 active」无关。"""
    first_dir = tmp_path / "a"
    first_dir.mkdir()
    second_dir = tmp_path / "b"
    second_dir.mkdir()
    first = workspace_service.create_workspace("A", [str(first_dir)])
    second = workspace_service.create_workspace("B", [str(second_dir)])
    workspace_service.set_active(first["id"])

    # 解析非 active 的工作区也要能拿到它的根目录
    assert workspace_service.resolve_workspace_roots(second["id"]) == [second_dir]
    # id 不存在时返回空列表（调用方据此判定"没有对应的工作区"）
    assert workspace_service.resolve_workspace_roots("w-999") == []


def test_get_active_roots_triggers_migration(tmp_path: Path):
    """get_active_roots 本身也要触发一次迁移（老库里首次读白名单就该拿到旧目录）。"""
    _write_legacy_roots([str(tmp_path)])

    assert workspace_service.get_active_roots() == [tmp_path]
    # 迁移后 workspaces.list 已经有内容了
    assert len(workspace_service.list_workspaces()) == 1


# --------------------------------------------------------------------------- #
# 旧数据迁移（ARCH-3 验收项）
# --------------------------------------------------------------------------- #
def test_legacy_workspace_roots_migrates_to_default_workspace(tmp_path: Path):
    """旧库里只有 workspace_roots 时，首次读取应自动生成一个默认工作区。"""
    _write_legacy_roots([str(tmp_path)])

    profiles = workspace_service.list_workspaces()

    assert len(profiles) == 1
    assert profiles[0]["id"] == workspace_service.DEFAULT_WORKSPACE_ID
    assert profiles[0]["name"] == workspace_service.DEFAULT_WORKSPACE_NAME
    assert profiles[0]["roots"] == [str(tmp_path)]
    assert profiles[0]["active"] is True


def test_migration_is_read_only_and_runs_once(tmp_path: Path):
    """迁移不得删改旧键，且只发生一次（第二次读取不应再造一个默认工作区）。"""
    _write_legacy_roots([str(tmp_path)])

    workspace_service.list_workspaces()
    # 旧键必须还在（只读迁移，出问题用户可以手工回退）
    assert setting_service.get_setting_value(workspace_service.LEGACY_ROOTS_KEY) == [str(tmp_path)]

    # 迁移后 workspaces.list 已有值，再读不应重复迁移
    workspace_service.list_workspaces()
    assert len(workspace_service.list_workspaces()) == 1


def test_migration_not_triggered_when_profiles_exist(tmp_path: Path):
    """已经有工作区时绝不能被旧键覆盖（否则用户新建的工作区会被莫名冲掉）。"""
    workspace_service.create_workspace("我建的", [str(tmp_path)])
    _write_legacy_roots([str(tmp_path / "legacy")])

    profiles = workspace_service.list_workspaces()

    assert [p["name"] for p in profiles] == ["我建的"]
    assert workspace_service.DEFAULT_WORKSPACE_ID not in {p["id"] for p in profiles}


def test_legacy_key_without_valid_dirs_yields_no_workspace():
    """旧键里的路径全都不存在时，不应该造出一个"看起来有配置、实际全是死路径"的默认工作区。"""
    _write_legacy_roots([r"D:\绝对不存在的目录\aaa"])

    assert workspace_service.list_workspaces() == []


# --------------------------------------------------------------------------- #
# 白名单联动（ARCH-3 核心）
# --------------------------------------------------------------------------- #
def test_refresh_workspace_roots_reads_active_workspace(tmp_path: Path):
    """refresh_workspace_roots 应把「当前 active 工作区的根」写进 WORKSPACE_ROOTS。"""
    first_dir = tmp_path / "a"
    first_dir.mkdir()
    second_dir = tmp_path / "b"
    second_dir.mkdir()
    workspace_service.create_workspace("A", [str(first_dir)])
    second = workspace_service.create_workspace("B", [str(second_dir)])
    workspace_service.set_active(second["id"])

    tool_utils.refresh_workspace_roots()

    assert WORKSPACE_ROOTS == [second_dir]


def test_switch_active_refreshes_roots_automatically(tmp_path: Path):
    """切换 active 后白名单必须**自动**跟着变（靠 workspaces.* 订阅，不靠调用方记得刷新）。"""
    first_dir = tmp_path / "a"
    first_dir.mkdir()
    second_dir = tmp_path / "b"
    second_dir.mkdir()
    first = workspace_service.create_workspace("A", [str(first_dir)])
    second = workspace_service.create_workspace("B", [str(second_dir)])
    workspace_service.set_active(first["id"])
    tool_utils.refresh_workspace_roots()
    assert WORKSPACE_ROOTS == [first_dir]

    # 这一步只调服务层，不手动刷新：验证订阅确实生效了
    workspace_service.set_active(second["id"])

    assert WORKSPACE_ROOTS == [second_dir], "切换 active 后白名单应自动刷新"


def test_path_decision_whitelist_follows_active_workspace(tmp_path: Path):
    """切换 active 后，path_decision 的写操作白名单范围应立刻跟随。"""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    first = workspace_service.create_workspace("A", [str(allowed_dir)])
    second = workspace_service.create_workspace("B", [str(other_dir)])

    # 当前是A：allowed_dir 可写，other_dir 应被拒
    workspace_service.set_active(first["id"])
    tool_utils.refresh_workspace_roots()
    assert path_decision(allowed_dir / "x.txt", OP_WRITE) is None
    assert path_decision(other_dir / "x.txt", OP_WRITE) is not None

    # 切到 B：allowed_dir 立刻不可写，other_dir 变得可写
    workspace_service.set_active(second["id"])
    assert path_decision(other_dir / "x.txt", OP_WRITE) is None
    assert path_decision(allowed_dir / "x.txt", OP_WRITE) is not None


def test_refresh_workspace_roots_clears_when_no_workspace(tmp_path: Path):
    """没有工作区时白名单应被清空（= 不限制），而不是残留上一次的目录。"""
    created = workspace_service.create_workspace("A", [str(tmp_path)])
    tool_utils.refresh_workspace_roots()
    assert WORKSPACE_ROOTS

    workspace_service.delete_workspace(created["id"])
    tool_utils.refresh_workspace_roots()

    assert WORKSPACE_ROOTS == []


def test_current_context_reads_active_workspace_roots(tmp_path: Path):
    """current_context().workspace_roots 应等于当前 active 工作区的根目录并集。"""
    first_dir = tmp_path / "a"
    first_dir.mkdir()
    second_dir = tmp_path / "b"
    second_dir.mkdir()
    first = workspace_service.create_workspace("A", [str(first_dir)])
    second = workspace_service.create_workspace("B", [str(second_dir)])
    workspace_service.set_active(second["id"])

    set_session_id("sess-ws-test")
    assert tuple(current_context().workspace_roots) == (second_dir,)

    # 切回A 后同一轮读取也该立刻变（current_context 每轮都重新解析，不缓存）
    workspace_service.set_active(first["id"])
    assert tuple(current_context().workspace_roots) == (first_dir,)


def test_refresh_survives_unavailable_settings(monkeypatch: pytest.MonkeyPatch):
    """工作区服务整体不可用时，refresh_workspace_roots 应退化成空清单而不抛异常。"""
    def _boom() -> list[Path]:
        """模拟数据库故障：直接抛异常。"""
        raise RuntimeError("模拟数据库不可用")

    monkeypatch.setattr(workspace_service, "get_active_roots", _boom)
    WORKSPACE_ROOTS.append(Path("D:/残留"))

    tool_utils.refresh_workspace_roots()

    assert WORKSPACE_ROOTS == [], "读不到工作区时应清空（=不限制），且不抛异常"