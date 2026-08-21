# app/services/setting_service.py
"""应用设置读写：普通设置落app_settings 表（key → JSON 字符串）。

分两层职责：
    - 本模块是**唯一**直接读写 app_settings 表的地方；
    - 类型校验、默认值、事件发布都在 services/settings_registry.py（本模块的上层）。

工作区相关的老接口（get/set_workspace_roots）暂时保留原地，
供 T04「工作区管理」迁移到新的多profile 模型之前继续使用。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：JSON 序列化设置值（列表/对象/布尔/数字统一按 JSON 文本存）
import json
# 标准库：路径对象
from pathlib import Path

# SQLAlchemy：select 查询
from sqlalchemy import select

# 项目内：数据库会话工厂
from app.db.db_config import get_session
# 项目内：设置实体
from app.entity.app_setting import AppSetting

# 工作区设置在表里的键名（历史遗留，待 T04 迁移为工作区 profile 后废弃）
_KEY_WORKSPACE = "workspace_roots"

# 工具输出续读键的前缀（EXT-5，见 app/tools/output_contract.py）。
# 这些键存的是工具的完整输出，属于临时数据而不是"设置"，批量读取设置时必须跳过，
# 否则一次 GET /api/settings 就会把几百 KB 的工具输出全带回前端。
_TOOL_OUTPUT_PREFIX = "tool-out-"


def get_workspace_roots() -> list[Path]:
    """读取用户配置的工作区根目录列表；未配置时返回空列表。

    :return: 已存在的目录路径列表（不存在的路径会被过滤掉，避免配置过期后误判）
    """
    with get_session() as s:
        row = s.get(AppSetting, _KEY_WORKSPACE)
        if row is None or not row.value:
            return []
        raw = json.loads(row.value)
    return [p for p in (Path(x) for x in raw) if p.is_dir()]


def set_workspace_roots(paths: list[str]) -> list[Path]:
    """保存工作区根目录列表（覆盖式），并返回过滤后真正生效的目录。

    :param paths: 用户选定的目录绝对路径列表
    :return: 过滤掉不存在项之后、实际生效的目录列表
    """
    valid = [Path(p) for p in paths if Path(p).is_dir()]
    with get_session() as s:
        row = s.get(AppSetting, _KEY_WORKSPACE)
        if row is None:
            s.add(AppSetting(key=_KEY_WORKSPACE, value=json.dumps([str(p) for p in valid])))
        else:
            row.value = json.dumps([str(p) for p in valid])
    return valid


# --------------------------------------------------------------------------- #
# 通用设置读写（供 services/settings_registry.py 调用）
# --------------------------------------------------------------------------- #
def get_setting_value(key: str) -> object | None:
    """读取单个设置项已落库的值（不做默认值兜底、不做类型校验）。

    与 settings_registry.get_setting 的分工：那一层负责「没落库就给默认值」的业务语义，
    本函数只负责「把表里那一行读出来」。

    :param key: 设置键，如 "llm.model"
    :return: 反序列化后的值；该键从未落库时返回 None
    """
    with get_session() as s:
        row = s.get(AppSetting, key)
        if row is None or row.value is None:
            return None
        raw = row.value
    # 空串视为「没配过」：历史数据里可能有 key 建了行但 value 是空的情况
    if raw == "":
        return None
    return json.loads(raw)


def set_setting_value(key: str, kind: str, value: object) -> None:
    """写入单个设置项（按 key upsert：有则更新，无则插入）。

    :param key: 设置键
    :param kind: 设置类型字符串（bool/int/float/string/json/select），
                 留作将来做按类型分列或迁移时的判别依据，当前仅记录不用
    :param value: 要保存的值；由调用方（settings_registry）保证已通过类型与范围校验
    """
    # 统一按 JSON 文本存：这样 bool / 数字 / 列表 / 对象都能原样往返，不需要为每种类型建列
    payload = json.dumps(value, ensure_ascii=False)
    with get_session() as s:
        row = s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value=payload))
        else:
            row.value = payload


def get_all_setting_values() -> dict[str, object]:
    """读取全部已落库的设置键值对（只含表里真实存在的行，不含未配置的声明默认值）。

    :return: 键 → 反序列化后的值；空表时返回空字典
    """
    with get_session() as s:
        rows = s.scalars(select(AppSetting)).all()
    result: dict[str, object] = {}
    for row in rows:
        # 工具输出续读键（EXT-5）不属于设置，直接跳过：把大文本当设置回传会拖垮设置接口
        if row.key.startswith(_TOOL_OUTPUT_PREFIX):
            continue
        if row.value is None or row.value == "":
            continue
        try:
            result[row.key] = json.loads(row.value)
        except json.JSONDecodeError:
            # 手工改库写坏的值不应让整次读取失败，跳过即可（该键会回落到声明默认值）
            continue
    return result


def delete_setting_value(key: str) -> bool:
    """删除某个设置项的落库记录，使其回落到声明默认值。

    :param key: 设置键
    :return: True=确实删掉了一行；False=该键本来就没落库过
    """
    with get_session() as s:
        row = s.get(AppSetting, key)
        if row is None:
            return False
        s.delete(row)
    return True