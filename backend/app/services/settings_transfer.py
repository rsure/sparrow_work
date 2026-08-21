# app/services/settings_transfer.py
"""配置导入导出（OPS-5）：把设置中心的配置导出成一份可读 JSON，再从 JSON 导回去。

为什么需要这个模块（而不是让前端自己拼 JSON）：
    配置里有两类东西：普通设置项（可以随便给人看）和密钥（绝对不能给人看）。
    "哪些算密钥" 这个判断只有后端知道（密封在 secrets 服务里，键名还散落在各供应商声明中），
    前端拿不到这份知识，自己拼很容易把 env / headers 里的 token 一起导出去。
    所以把"导出什么、怎么脱敏、导入时跳过什么"全部收在后端，前端只负责下载与上传。

三条安全红线：
    1. 导出**永远不含** secrets.* 命名空间的键，也不含任何密钥明文；
    2. 设置了密钥只导出一个布尔 in_secrets 列表（让用户知道"这里还有东西要单独配"）；
    3. 值里疑似密钥的部分（MCP 的 env / headers）替换成占位符，并把该键记进
       ``redacted_keys``——导入时整键跳过，避免把占位符写回真实配置。

导出格式（稳定契约，前端与文档都依赖它）::

    {
      "format": "app-settings/1",
      "exported_at": "2026-10-23T12:00:00",
      "app_version": "0.1.0",
      "values": {"theme.preset": "dark", ...},
      "redacted_keys": ["mcp.servers"],
      "secrets": [{"key": "deepseek.api_key", "set": true}]
    }
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：取当前时间作为导出的时间戳
from datetime import datetime
# 标准库：Any 标注
from typing import Any

# 项目内：应用版本号（写进导出文件，方便排查"这份配置是哪一版导出的"）
from app.config import settings as app_settings
# 项目内：脱敏工具（键名命中 api_key/token/secret 等词就抹值，env/headers 容器整段抹值）
from app.services.diagnostic_service import redact
# 项目内：设置声明式注册表（get_all_settings / get_def / put_settings / SECRET_KEY_PREFIX）
from app.services import settings_registry
# 项目内：密钥存储（只查"有没有设置过"，绝不取值）
from app.services import secrets as secrets_service
# 项目内：内置供应商清单（每家供应商的 secret_key 名字只能从这里问）
from app.llm.registry import list_providers

# 导出格式标识：导入时用它判断"这是不是本应用的配置文件"
EXPORT_FORMAT = "app-settings/1"

# 脱敏占位符：与 diagnostic_service 里的写法保持一致，便于用户对照
_PLACEHOLDER = "***REDACTED***"


def _secret_keys() -> list[str]:
    """列出本应用可能用到的全部密钥名（不含 ``secrets.`` 前缀）。

    :return: 密钥名列表，如 ["deepseek.api_key", ...]；去重并保持供应商顺序
    """
    names: list[str] = []
    for provider in list_providers():
        # secret_key 为空表示这家供应商不需要密钥（例如本地 Ollama）
        if provider.secret_key and provider.secret_key not in names:
            names.append(provider.secret_key)
    return names


def build_export() -> dict[str, Any]:
    """组装一份可下载的配置快照（已脱敏）。

    做的事分三步：
        1. 取全部**非密钥**设置项（get_all_settings 本身就会拒绝任何 secrets.* 键）；
        2. 逐个值跑一遍 redact：命中密钥特征的键换成占位符，并记进 redacted_keys；
        3. 追加"哪些密钥设置过"的清单——只报 set 布尔值，不碰密文/明文/脱敏值。

    :return: 导出字典（结构见模块 docstring）
    """
    raw = settings_registry.get_all_settings()

    values: dict[str, Any] = {}
    redacted_keys: list[str] = []
    for key, value in raw.items():
        cleaned = redact(value, key)
        if cleaned != value:
            # 这个键的值里含疑似密钥（典型是 mcp.servers 的 env / headers）：
            # 整份值都不导出，只留占位提示，避免"看着像脱敏了其实结构还在"的误判
            values[key] = _PLACEHOLDER
            redacted_keys.append(key)
        else:
            values[key] = value

    secrets_info = [
        {"key": name, "set": secrets_service.has_secret(name)}
        for name in _secret_keys()
    ]

    return {
        "format": EXPORT_FORMAT,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": app_settings.version,
        "values": values,
        "redacted_keys": redacted_keys,
        "secrets": secrets_info,
    }


def apply_import(payload: dict[str, Any]) -> dict[str, Any]:
    """把一份导出的配置写回本机（只写合法、可写的那些键）。

    跳过规则（全部记进返回值的 skipped，前端可以如实告诉用户"哪几项没导"）：
        - 键名不在本机声明表里 → "未声明的设置键"（可能是更高版本的应用导出的）；
        - 键名以 ``secrets.`` 开头 → 密钥不走这个通道，必须用 /api/settings/secrets；
        - 键名属于 secret 声明 → 同上，防止未来有人把密钥声明成普通设置；
        - 出现在 payload.redacted_keys 里 / 值是占位符 → 导出时已脱敏，写回去只会污染配置；
        - 值类型或范围不合法 → 交给 put_settings 的校验，这里先按单键试算，
          只把合法的键交给 put_settings，避免"一个坏键拖垮整份配置"。

    :param payload: 导出字典（至少要有 values；format 若存在则必须匹配）
    :return: ``{"applied": [键...], "skipped": [{"key":..., "reason":...}], "values": 写后全量设置}``
    :raises ValueError: payload 不是字典、format 不匹配、values 缺失或不是字典
    """
    if not isinstance(payload, dict):
        raise ValueError("配置内容必须是一个 JSON 对象")
    fmt = payload.get("format")
    if fmt is not None and fmt != EXPORT_FORMAT:
        raise ValueError(f"不认识的配置格式：{fmt}（本机只支持 {EXPORT_FORMAT}）")

    candidate = payload.get("values")
    if not isinstance(candidate, dict):
        raise ValueError("配置内容缺少 values 字段（或它不是对象）")

    payload_redacted = set(payload.get("redacted_keys") or [])

    accepted: dict[str, Any] = {}
    skipped: list[dict[str, str]] = []
    for key, value in candidate.items():
        if not isinstance(key, str):
            skipped.append({"key": str(key), "reason": "键名不是字符串"})
            continue
        # 密钥命名空间先判：secrets.* 根本没有声明，走 get_def 只会得到
        # "未声明的设置键"这个误导性的原因，用户就不知道该去填写密钥了
        if key.startswith(settings_registry.SECRET_KEY_PREFIX):
            skipped.append({"key": key, "reason": "密钥不随配置导入，请到设置页单独填写"})
            continue
        try:
            definition = settings_registry.get_def(key)
        except KeyError:
            skipped.append({"key": key, "reason": "本机未声明的设置键"})
            continue
        if definition.secret:
            skipped.append({"key": key, "reason": "密钥不随配置导入，请到设置页单独填写"})
            continue
        if key in payload_redacted or value == _PLACEHOLDER:
            skipped.append({"key": key, "reason": "导出时已脱敏，导入会污染配置"})
            continue
        try:
            definition.coerce(value)
        except (TypeError, ValueError) as exc:
            skipped.append({"key": key, "reason": f"值不合法：{exc}"})
            continue
        accepted[key] = value

    if accepted:
        # put_settings 内部还会再校验一次（双保险），并逐键发布变更事件，
        # 所以导入后主题、模型、工作区白名单都会像手动改设置一样立即生效
        settings_registry.put_settings(accepted)

    return {
        "applied": sorted(accepted),
        "skipped": skipped,
        "values": settings_registry.get_all_settings(),
    }
