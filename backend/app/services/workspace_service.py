# app/services/workspace_service.py
"""工作区（多 profile）的增删改查与「当前生效工作区」解析（ARCH-3）。

改造前后对照（这是理解本文件的唯一钥匙）：
    - 改造前：只有一个扁平键``workspace_roots`` = ["D:\\a", "D:\\b"]，全局唯一一份根目录；
    - 改造后：``workspaces.list`` = [profile, ...]（每个 profile 有 id/name/roots），
      另有一个 ``workspaces.active_id`` 指明当前用哪一个。

"active 决定什么"（ARCH-3 §3.1）：
    1. 文件工具的越界判断（tools/tool_utils.py 的 WORKSPACE_ROOTS，写/执行白名单）；
    2. 前端文件树FileTree 展示的根；
    3. 知识库的默认检索范围。

存储为什么用 app_settings 的 JSON 而不是建表：
    工作区是「整体读、整体写」的少量结构化数据，没有独立查询/排序/分页需求，
    建表反而要多写一份实体 + Alembic 迁移。存 JSON 数组后 CRUD 只需一次读写，
    也天然与 settings_registry 的校验/事件机制对齐（见 services/workspace_settings_defs.py）。

旧数据兼容（ARCH-3 §3.4 验收项）：
    首次读取时若 ``workspaces.list`` 不存在/为空、而旧的 ``workspace_roots`` 有值，
    就自动生成一个默认工作区（id = ``w-default``、name = "默认工作区"）。
    这是**只读迁移**：旧键原样保留不动，出问题可以手工改回去。

权威性约定：
    「当前生效工作区」**以 workspaces.active_id 为准**；profile 里的 ``active`` 字段
    只是给前端渲染用的冗余标记，每次写入时都会按 active_id 重新同步，避免两者不一致。
"""

# 让类型注解延迟求值（PEP 563），便于使用 list[Path]、dict[str, Any] 等新语法
from __future__ import annotations

# 标准库：路径对象，工作区的 roots 在服务层统一用绝对路径字符串存取、用 Path 做存在性过滤
from pathlib import Path
# 标准库：Any 描述 profile 的字典值（结构由本模块自己校验与补全）
from typing import Any

# 项目内：设置声明式注册表（本模块的读写统一走它，从而自动获得校验 + 变更事件）
from app.services.settings_registry import get_setting, put_settings
# 项目内：落库层。get_setting_value 读旧键 workspace_roots 做迁移、set_setting_value 是注册表不可用时的兜底写入
from app.services.setting_service import get_setting_value, set_setting_value
# 项目内：本层的设置键名与声明清单（与 settings_registry 分开，避免动到地基文件）
from app.services.workspace_settings_defs import KEY_ACTIVE_ID, KEY_WORKSPACES

# 迁移前的老键名（存的是"根目录字符串数组"，不是 profile 数组）
LEGACY_ROOTS_KEY = "workspace_roots"

# 迁移生成的默认工作区 id / 名称。id 加"-" 前缀是为了与新建的 w-1 / w-2 明显区分开
DEFAULT_WORKSPACE_ID = "w-default"
DEFAULT_WORKSPACE_NAME = "默认工作区"

# 新建工作区时生成 id 的前缀，形如 w-1、w-2……（与迁移出来的 w-default 区分开）
_ID_PREFIX = "w-"


# --------------------------------------------------------------------------- #
# 内部工具：读写 + 结构归一化
# --------------------------------------------------------------------------- #
def _is_existing_dir(path: Path) -> bool:
    """判断路径是否是一个**当前真实存在**的目录，判断本身出错时按"不存在"处理。

    为什么必须过滤：用户会移动目录、拔掉移动硬盘，这些失效路径留在白名单里
    会让工具层以为还能访问，实际写入时才报错；更糟的是过期路径可能已被系统复用。

    :param path: 待判断的路径
    :return: 是现存目录时为 True
    """
    try:
        return path.is_dir()
    except OSError:
        # 权限异常、断开的网络盘等情况下 is_dir() 本身就可能抛错
        return False


def _get_value(key: str, default: Any) -> Any:
    """读一个设置值，**在设置声明尚未注册时也能工作**。

    正常路径走settings_registry（拿声明默认值 + 容错读库）；
    但注册发生在 main.create_app() 里，而本模块可能被单测或脚本先import，
    此时 get_setting 会抛 KeyError。这里退化为直接读库，读不到就用default。

    :param key: 设置键
    :param default: 读取失败或值为空时的兜底
    :return: 设置值
    """
    try:
        return get_setting(key)
    except KeyError:
        try:
            stored = get_setting_value(key)
        except Exception:
            return default
        return default if stored is None else stored


def _put_values(values: dict[str, Any]) -> None:
    """写一组设置值，**在设置声明尚未注册时也能工作**。

    正常路径走 put_settings（类型校验 + 发布 workspaces.* 变更事件，工具白名单靠这个事件刷新）；
    若声明还没注册（KeyError），退化为直接落库——此时没有事件，调用方需自行刷新白名单。

    :param values: 键 → 新值
    """
    try:
        put_settings(values)
    except KeyError:
        # 退化路径：直接按 key upsert 落库。kind 只作记录（见 set_setting_value 的说明），
        # 这里按值的实际 Python 类型填，避免留下误导性的元信息
        for key, value in values.items():
            kind = "string" if isinstance(value, str) else "json"
            set_setting_value(key, kind, value)


def _load_profiles() -> list[dict[str, Any]]:
    """读取并归一化工作区列表（**不做旧数据迁移**，迁移由_ensure_migrated 负责）。

    归一化做什么（落库的数据可能来自手工改库，这里做防御）：
        - 丢掉非字典元素；
        - 缺 id 的补一个、缺 name 的补默认名、roots 不是列表的补空列表；
        - roots 里去掉空白项与非字符串项，并保持原顺序去重。

    :return: profile 字典列表；未配置过或配置损坏时为空列表
    """
    raw = _get_value(KEY_WORKSPACES, [])
    if not isinstance(raw, list):
        return []

    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        # id：缺失时按位置兜底，保证后续 set_active / update 一定有 id 可用
        ws_id = str(item.get("id") or "").strip() or f"{_ID_PREFIX}{index + 1}"
        if ws_id in used_ids:
            # 出现重复 id 会让"按 id 定位"变得不确定，这里直接跳过后者
            continue
        used_ids.add(ws_id)
        result.append({
            "id": ws_id,
            "name": str(item.get("name") or "").strip() or ws_id,
            "roots": _normalize_roots(item.get("roots")),
            # active 只是冗余标记，落库时统一按 active_id 同步，这里先原样保留
            "active": bool(item.get("active", False)),
        })
    return result


def _normalize_roots(roots: Any) -> list[str]:
    """把 roots 归一化成「去空白、去重、保持原顺序」的字符串列表。

    :param roots: 任意值（字符串、列表、None 都能安全处理）
    :return: 归一化后的绝对路径字符串列表
    """
    if not isinstance(roots, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in roots:
        text = str(item).strip() if isinstance(item, (str, Path)) else ""
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _read_active_id() -> str:
    """读取当前生效工作区的 id 字符串；未配置时为空串。"""
    value = _get_value(KEY_ACTIVE_ID, "")
    return str(value or "").strip()


def _save(profiles: list[dict[str, Any]], active_id: str) -> None:
    """把工作区列表与当前 id 一起落库（一次 put_settings 原子写入两个键）。

    写入前会把每个 profile 的 ``active`` 字段按 active_id 重新同步，
    这样「冗余标记」永远不会和权威值打架。

    :param profiles: 完整的工作区列表（函数内会先按 active_id 同步 active 字段）
    :param active_id: 当前生效工作区的 id；空串表示当前没有生效的工作区
    """
    normalized = [
        {
            "id": str(p.get("id") or ""),
            "name": str(p.get("name") or ""),
            "roots": _normalize_roots(p.get("roots")),
            "active": bool(active_id) and str(p.get("id") or "") == active_id,
        }
        for p in profiles
    ]
    # 走 settings_registry 而不是直接落库：这样类型校验与「workspaces.*变更事件」都自动生效，
    # 订阅者（工具层白名单刷新）才能在切换 active 后立刻跟上
    _put_values({KEY_WORKSPACES: normalized, KEY_ACTIVE_ID: active_id})


def _ensure_migrated() -> list[dict[str, Any]]:
    """保证「工作区列表」存在：必要时把旧的workspace_roots 迁移成一个默认工作区。

    迁移条件（三者同时满足才做，避免覆盖用户已有配置）：
        1. 当前的 workspaces.list 为空（从未配置过，或被清空过）；
        2. 旧的 workspace_roots 键有值；
        3. 迁移只在第一次发生（写出 workspaces.list 后条件1 就不再满足）。

    只读迁移：旧键 ``workspace_roots`` **不删不改**，用户仍可手工回退。

    :return: 迁移后（或原本就有的）工作区列表
    """
    profiles = _load_profiles()
    if profiles:
        return profiles

    # 读旧键：这一层只读，绝不写；读失败（表不存在等）就当作"没有旧数据"
    try:
        legacy_raw = get_setting_value(LEGACY_ROOTS_KEY)
    except Exception:
        return []
    # 只迁移**当前真实存在**的目录：旧接口 get_workspace_roots 当年也是这么过滤的，
    # 全是死路径时宁可当作"没有旧数据"，也不要造出一个看着有配置、实际全是死路径的工作区
    legacy_roots = [
        text for text in _normalize_roots(legacy_raw)
        if _is_existing_dir(Path(text))
    ]
    if not legacy_roots:
        return []

    profiles = [{
        "id": DEFAULT_WORKSPACE_ID,
        "name": DEFAULT_WORKSPACE_NAME,
        "roots": legacy_roots,
        "active": True,
    }]
    _save(profiles, DEFAULT_WORKSPACE_ID)
    return profiles


def _next_id(profiles: list[dict[str, Any]]) -> str:
    """给新建的工作区分配一个不与现有 id 冲突的编号（形如 w-1、w-2……）。

    :param profiles: 现有工作区列表（用于查已占用的编号）
    :return: 新id 字符串
    """
    used = {str(p.get("id") or "") for p in profiles}
    index = 1
    while f"{_ID_PREFIX}{index}" in used:
        index += 1
    return f"{_ID_PREFIX}{index}"


# --------------------------------------------------------------------------- #
# 对外接口：查询
# --------------------------------------------------------------------------- #
def list_workspaces() -> list[dict[str, Any]]:
    """返回全部工作区 profile（含旧数据自动迁移）。

    每次调用都会先做一次迁移检查，因此**首次调用**即会把旧的 workspace_roots
    转成一个默认工作区，调用方不需要关心"这是不是第一次启动"。

    :return: profile 字典列表，元素形如
        {"id": "w-1", "name": "主项目", "roots": ["D:\\work\\app"], "active": True}；
        一个工作区都没有时返回空列表
    """
    profiles = _ensure_migrated()
    active_id = _read_active_id()
    return [
        {**p, "active": bool(active_id) and p["id"] == active_id}
        for p in profiles
    ]


def get_active() -> dict[str, Any] | None:
    """返回当前生效的工作区 profile。

    回落规则（保证调用方永远拿得到一个可用的工作区）：
        1. active_id 指向的工作区存在 → 返回它；
        2. active_id 为空或指向已被删除的工作区 → 返回列表里的第一个。

    :return: profile 字典；一个工作区都没有时返回 None
    """
    profiles = _ensure_migrated()
    if not profiles:
        return None
    active_id = _read_active_id()
    for profile in profiles:
        if profile["id"] == active_id:
            return {**profile, "active": True}
    # 没有明确 active（或 active 悬空）时回落到第一个，active 标记相应置 True
    return {**profiles[0], "active": True}


def get_active_roots() -> list[Path]:
    """返回当前生效工作区的根目录并集（工具层白名单的数据来源）。

    与 profile 里存的字符串不同，这里只返回**当前真实存在**的目录：
    用户移动/删除了目录、或插拔移动硬盘后，配置里留下的失效路径不会让工具层误判。

    :return: 已存在的根目录 Path 列表（保持配置里的顺序）；没有 active 工作区或目录全失效时返回空列表
    """
    active = get_active()
    if active is None:
        return []
    roots: list[Path] = []
    for text in _normalize_roots(active.get("roots")):
        path = Path(text)
        if _is_existing_dir(path):
            roots.append(path)
    return roots


def resolve_workspace_roots(workspace_id: str) -> list[Path]:
    """按工作区 id 解析它的根目录（供 verify.commands 这类"工作区级设置"使用）。

    与 get_active_roots 的区别：这里**不关心哪个是 active**，只看传入的 id，
    因此可以对"非当前工作区"做只读的范围判断（例如校验某条命令配置属于哪个工作区）。

    :param workspace_id: 目标工作区 id
    :return: 该工作区里当前真实存在的根目录列表；id 不存在时返回空列表
    """
    profiles = _ensure_migrated()
    for profile in profiles:
        if profile["id"] == workspace_id:
            return [
                path for path in (Path(t) for t in _normalize_roots(profile.get("roots")))
                if _is_existing_dir(path)
            ]
    return []


# --------------------------------------------------------------------------- #
# 对外接口：写入
# --------------------------------------------------------------------------- #
def create_workspace(name: str, roots: list[str] | None = None) -> dict[str, Any]:
    """新建一个工作区 profile。

    :param name: 工作区名称；去掉首尾空格后不能为空（否则用占位名）
    :param roots: 根目录绝对路径列表；None 或空列表都表示"先不配根目录"
    :return: 新建出的 profile 字典（**active 标记为 False**：新建不会抢走当前工作区，
        但如果这是第一个工作区，它会同时成为当前工作区）
    :raises ValueError: 传入的 roots 不是列表
    """
    profiles = _ensure_migrated()
    if roots is not None and not isinstance(roots, list):
        raise ValueError(f"工作区根目录必须是路径列表，收到 {type(roots).__name__}")

    profile = {
        "id": _next_id(profiles),
        "name": str(name or "").strip() or DEFAULT_WORKSPACE_NAME,
        "roots": _normalize_roots(roots),
        "active": False,
    }
    profiles.append(profile)

    active_id = _read_active_id()
    if not active_id:
        # 第一个工作区自动成为当前工作区：否则用户新建完还得手动切一次，体验断档
        active_id = profile["id"]
    _save(profiles, active_id)
    return {**profile, "active": profile["id"] == active_id}


def update_workspace(
    workspace_id: str,
    name: str | None = None,
    roots: list[str] | None = None,
) -> dict[str, Any]:
    """更新一个工作区的名称和/或根目录（两个字段都可省略，省略即保持原值）。

    :param workspace_id: 目标工作区 id
    :param name: 新名称；None 表示只改根目录
    :param roots: 新根目录列表；None 表示只改名（注意传 [] 表示"清空根目录"，与None 语义不同）
    :return: 更新后的 profile 字典
    :raises ValueError: workspace_id 不存在，或 roots 不是列表
    """
    profiles = _ensure_migrated()
    if roots is not None and not isinstance(roots, list):
        raise ValueError(f"工作区根目录必须是路径列表，收到 {type(roots).__name__}")

    target = next((p for p in profiles if p["id"] == workspace_id), None)
    if target is None:
        raise ValueError(f"工作区不存在：{workspace_id}")

    if name is not None:
        text = str(name).strip()
        if text:
            target["name"] = text
    if roots is not None:
        target["roots"] = _normalize_roots(roots)

    active_id = _read_active_id()
    # 兜底：active_id 悬空（例如历史数据坏了）时顺手修正为第一个，避免"没有当前工作区"
    if active_id and not any(p["id"] == active_id for p in profiles):
        active_id = profiles[0]["id"]
    _save(profiles, active_id)
    return {**target, "active": target["id"] == active_id}


def delete_workspace(workspace_id: str) -> bool:
    """删除一个工作区；若删掉的是当前工作区，会把 active 顺延到剩下的第一个。

    顺延而不是置空，是为了避免"删掉当前工作区后所有工具突然失去白名单"这种突变
    （白名单为空在工具层表示"不限制"，对用户是危险的方向）。

    :param workspace_id: 要删除的工作区 id
    :return: True=确实删掉了；False=该 id 本来就不存在
    """
    profiles = _ensure_migrated()
    remaining = [p for p in profiles if p["id"] != workspace_id]
    if len(remaining) == len(profiles):
        return False

    active_id = _read_active_id()
    if active_id == workspace_id or not any(p["id"] == active_id for p in remaining):
        # 删掉的是当前工作区，或 active 本来就悬空：顺延到剩下的第一个；一个不剩则置空
        active_id = remaining[0]["id"] if remaining else ""
    _save(remaining, active_id)
    return True


def set_active(workspace_id: str) -> dict[str, Any]:
    """切换当前生效的工作区（写 workspaces.active_id，并发布变更事件刷新工具白名单）。

    :param workspace_id: 目标工作区 id
    :return: 被设为当前工作区的 profile 字典（active=True）
    :raises ValueError: workspace_id 不存在
    """
    profiles = _ensure_migrated()
    target = next((p for p in profiles if p["id"] == workspace_id), None)
    if target is None:
        raise ValueError(f"工作区不存在：{workspace_id}")
    _save(profiles, workspace_id)
    return {**target, "active": True}