# app/skills/registry.py
"""技能注册表：进程内缓存 + 启停开关 + 系统提示词摘要。

为什么要有注册表而不是每次现扫：
    1. 系统提示词在**建 agent 时**就要用到技能清单，每个请求扫一遍目录太浪费；
    2. 扫描结果要能被接口查询、被 `/api/skills/reload` 主动刷新；
    3. 启停开关（`skill.disabled`）需要与"已发现的技能"合并后统一对外表达。

刷新时机（只在这三处，避免"什么时候生效"说不清）：
    - 应用启动（create_app 里注册完设置声明之后）；
    - `POST /api/skills/reload`（用户装了新技能后点刷新）；
    - 设置里改了 `skill.dirs` / `skill.disabled` —— 下一次读注册表时惰性刷新。

安全边界：
    技能只是**提示词**，不是可执行代码；它带来的风险是"让模型去做危险操作"，
    而所有工具调用仍然要走 `tools/policy.py` 的裁决，所以技能无法绕过确认与 DENY 护栏。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：线程锁（工具层可能在 worker 线程里读注册表）、路径
import threading
from pathlib import Path

# 项目内：解析与发现
from app.skills.loader import (
    SkillLoadError,
    SkillSpec,
    default_skills_dir,
    discover,
)

# 系统提示词里最多列出多少个技能：太多会把提示词撑长，而且模型也记不住
_PROMPT_MAX_SKILLS = 20

# 提示词里每条描述最多多少字符（防止一句超长 description 占满提示词）
_PROMPT_MAX_DESC_CHARS = 160

# 注册表状态：发现结果 + 错误 + 生效目录 + 上次刷新时的开关快照
_lock = threading.RLock()
_specs: dict[str, SkillSpec] = {}
_errors: list[SkillLoadError] = []
_dirs: list[Path] = []
# 上次刷新时的 `skill.dirs` / `skill.disabled` 快照：用于惰性判断"设置是否变了"
_snapshot_signature: tuple = ()


def _read_json_setting(key: str, default):
    """读一个 JSON 设置项；读不到时返回默认值（注册表不能因为设置库没就绪就崩）。

    :param key: 设置键
    :param default: 默认值
    :return: 设置值
    """
    try:
        # 项目内：延迟导入，避免模块导入期就依赖数据库
        from app.services.settings_registry import get_setting

        value = get_setting(key)
    except Exception:
        return default
    return default if value is None else value


def resolve_dirs() -> list[Path]:
    """算出本次要扫描的目录列表（用户目录优先 + 设置里的额外目录）。

    :return: 去重后的目录列表
    """
    dirs: list[Path] = [default_skills_dir()]
    extra = _read_json_setting("skill.dirs", [])
    if isinstance(extra, list):
        for item in extra:
            text = str(item or "").strip()
            if not text:
                continue
            # expanduser 让用户能写 "~/my-skills"
            dirs.append(Path(text).expanduser())
    # 去重（保持顺序）：同一目录写两次不该扫两遍
    seen: set[str] = set()
    unique: list[Path] = []
    for path in dirs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _disabled_names() -> set[str]:
    """读出被禁用的技能名集合（设置键 `skill.disabled`）。"""
    raw = _read_json_setting("skill.disabled", [])
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _current_signature() -> tuple:
    """当前影响技能集合的设置指纹（目录 + 禁用名单）。

    :return: 可比较的元组
    """
    return (tuple(str(p) for p in resolve_dirs()), tuple(sorted(_disabled_names())))


def reload(force: bool = True) -> dict:
    """重新扫描目录，刷新注册表。

    :param force: True=无条件重扫；False=仅当目录/禁用名单变化时才重扫（惰性刷新用）
    :return: 快照（见 snapshot）
    """
    global _specs, _errors, _dirs, _snapshot_signature

    signature = _current_signature()
    with _lock:
        if not force and signature == _snapshot_signature and _specs:
            return snapshot()
        # 用户级目录不存在时自动创建：让"把技能放进去"这件事有明确落点
        try:
            default_skills_dir().mkdir(parents=True, exist_ok=True)
        except OSError:
            # 没有写权限也不该让功能崩掉：只是这个目录扫不到而已
            pass
        dirs = list(signature[0])
        _dirs = [Path(item) for item in dirs]
        specs, errors = discover(_dirs)
        _specs = {spec.name: spec for spec in specs}
        _errors = errors
        _snapshot_signature = signature
        return snapshot()


def ensure_loaded() -> None:
    """确保注册表已填充（惰性刷新：设置变化后自动重扫）。

    工具调用与建 agent 都会先走这里，所以"用户改了设置但没点重载"也能生效。
    """
    with _lock:
        if not _specs and not _snapshot_signature:
            reload(force=True)
            return
    # 锁外比较签名：reload 内部会再取锁
    if _current_signature() != _snapshot_signature:
        reload(force=True)


def is_globally_enabled() -> bool:
    """技能系统总开关（设置键 `skill.enabled`），默认开启。"""
    return bool(_read_json_setting("skill.enabled", True))


def is_disabled(name: str) -> bool:
    """某个技能是否被单独禁用。

    :param name: 技能名
    :return: 被禁用返回 True
    """
    return name in _disabled_names()


def list_specs(*, include_disabled: bool = True) -> list[SkillSpec]:
    """列出已发现的技能。

    :param include_disabled: 是否包含被单独禁用的技能
    :return: 按名字排序的 SkillSpec 列表
    """
    ensure_loaded()
    disabled = _disabled_names()
    with _lock:
        items = list(_specs.values())
    if not include_disabled:
        items = [item for item in items if item.name not in disabled]
    return sorted(items, key=lambda item: item.name)


def get_skill(name: str) -> SkillSpec | None:
    """按名字取技能；不存在返回 None。

    :param name: 技能名
    :return: SkillSpec 或 None
    """
    ensure_loaded()
    with _lock:
        return _specs.get(name)


def usable(name: str) -> SkillSpec | None:
    """取"当前真的能用的技能"（总开关关闭或被禁用时返回 None）。

    :param name: 技能名
    :return: SkillSpec 或 None
    """
    if not is_globally_enabled():
        return None
    spec = get_skill(name)
    if spec is None or is_disabled(name):
        return None
    return spec


def snapshot() -> dict:
    """注册表的可下发状态（列表接口与前端设置页用）。

    :return: {skills, errors, dirs, enabled, disabled}
    """
    disabled = sorted(_disabled_names())
    with _lock:
        specs = sorted(_specs.values(), key=lambda item: item.name)
        errors = list(_errors)
        dirs = list(_dirs)
    return {
        "skills": [spec.to_dict(enabled=spec.name not in disabled) for spec in specs],
        "errors": [error.to_dict() for error in errors],
        "dirs": [str(path) for path in dirs],
        "enabled": is_globally_enabled(),
        "disabled": disabled,
    }


def build_prompt() -> str:
    """生成注入系统提示词的技能摘要（**只含名字 + 描述**，不含正文）。

    为什么不在提示词里塞正文：技能正文可能很长，而一轮对话往往只用到其中一个。
    正确姿势是让模型看到清单 → 需要时用 `read_skill` 工具按需读取（见 tools/skill_tool.py）。

    :return: 提示词片段；没有可用技能时返回空串（调用方据此决定是否追加）
    """
    if not is_globally_enabled():
        return ""
    specs = list_specs(include_disabled=False)
    if not specs:
        return ""

    lines = [
        "【可用技能】（用户通过 `/技能名 参数` 调用，你也可以在匹配场景下主动用 read_skill 读取其正文后执行）",
    ]
    for spec in specs[:_PROMPT_MAX_SKILLS]:
        desc = spec.description
        if len(desc) > _PROMPT_MAX_DESC_CHARS:
            desc = desc[:_PROMPT_MAX_DESC_CHARS] + "…"
        lines.append(f"- {spec.name}：{desc}")
    if len(specs) > _PROMPT_MAX_SKILLS:
        lines.append(f"（还有 {len(specs) - _PROMPT_MAX_SKILLS} 个技能未列出，用 list_skills 查看全部）")
    lines.append("提示：执行前先 read_skill(名字) 拿到完整操作说明，不要凭名字猜步骤。")
    return "\n".join(lines)


def reset_for_test() -> None:
    """清空注册表状态，供用例之间隔离（不会删磁盘上的技能目录）。"""
    global _specs, _errors, _dirs, _snapshot_signature
    with _lock:
        _specs = {}
        _errors = []
        _dirs = []
        _snapshot_signature = ()
