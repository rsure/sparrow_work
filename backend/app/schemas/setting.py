"""设置接口的请求/响应模型（对应 doc/28 §3.1 的接口契约）。

命名约定：沿用后端既有风格，字段名snake_case，前端类型直接沿用不做转换。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 数据校验：BaseModel 作为请求体基类，Field 给字段写说明（会出现在 /docs）
from typing import Any
from pydantic import BaseModel, Field


class SettingsBatchIn(BaseModel):
    """批量保存普通设置的请求体（PUT /api/settings）。"""

    # 要保存的键值对；只需包含要改的键，未出现的键保持原值。
    # 不允许出现 secrets.* 开头的键——密钥必须走专门的 secrets 接口。
    values: dict[str, Any] = Field(
        ...,
        description="设置键值对，如 {\"llm.model\": \"deepseek-chat\"}；"
                    "键必须在 SETTING_DEFS 中声明过，值会按声明做类型与范围校验",
    )


class SettingMetaOut(BaseModel):
    """单个设置项的 schema 描述（GET /api/settings/meta 数组元素）。"""

    # 设置键，形如 "llm.model"
    key: str = Field(..., description="设置键，格式固定为「组.键」，全局唯一")
    # 中文展示名：设置页的标题用它，不再把 key 直接摆给用户看
    label: str = Field("", description="中文展示名；为空时前端回退显示 key")
    # 值类型，前端据此选择渲染控件（开关 / 数字输入 / 文本框 / JSON 编辑 / 下拉）
    type: str = Field(..., description="值类型：bool / int / float / string / json / select")
    # 默认值：用户未配置该项时后端返回它
    default: Any = Field(None, description="默认值；用户没配置过时生效")
    # 数值下界（仅 int / float 有）
    min: float | None = Field(None, description="数值下界；不限时为 null")
    # 数值上界（仅 int / float 有）
    max: float | None = Field(None, description="数值上界；不限时为 null")
    # select 类型的候选值列表；其它类型为 null
    options: list[str] | None = Field(None, description="select 类型的候选值；其它类型为 null")
    # select 候选值的中文标签（与 options 一一对应）；其它类型为 null
    option_labels: list[str] | None = Field(
        None, description="select 候选值的中文标签，与 options 顺序一致；其它类型为 null",
    )
    # 设置页分组，前端按它自动分区渲染
    category: str = Field(..., description="设置页分组：model / tools / context / agent / advanced")
    # 首次引入的里程碑
    since: str = Field("M1", description="该设置项首次引入的里程碑")
    # 面向用户的一句话说明
    description: str = Field("", description="该设置项的用途说明")
    # 是否为密钥项（密钥不会出现在本接口里，此字段恒为 false，保留以便扩展）
    secret: bool = Field(False, description="是否为密钥项；密钥不会出现在本接口里")


class SettingsOut(BaseModel):
    """全量设置值的响应体（GET /api/settings / PUT /api/settings）。"""

    # 键 → 当前生效值；不含任何 secrets.* 键
    values: dict[str, Any] = Field(
        ...,
        description="全部非密钥设置项的当前值（已落库值，未落库则为声明默认值）",
    )


class SecretPointOut(BaseModel):
    """导出文件里的「某个密钥设置过没有」（绝不包含密钥值本身）。"""

    # 密钥名，不带 secrets. 前缀，如 "deepseek.api_key"
    key: str = Field(..., description="密钥名（不带 secrets. 前缀）")
    # 是否已设置；true 表示导入到新机器后需要重新填写这一个
    set: bool = Field(..., description="该密钥在本机是否已设置")


class SettingsExportOut(BaseModel):
    """配置导出的响应体（GET /api/settings/export，OPS-5）。

    这是一份**脱敏**快照：不含任何密钥明文，也不含 secrets.* 命名空间的键。
    """

    # 导出格式标识，形如 "app-settings/1"；导入时用它判断配置文件是否属于本应用
    format: str = Field(..., description="导出格式标识，如 app-settings/1")
    # 导出时间（本机时区，ISO 8601，精确到秒），仅用于用户分辨新旧文件
    exported_at: str = Field(..., description="导出时间（ISO 8601，精确到秒）")
    # 导出时的应用版本号，排查「这份配置是哪一版导出的」时有用
    app_version: str = Field(..., description="导出时的应用版本号，如 0.1.0")
    # 键 → 值；含疑似密钥的键其值被替换成 ***REDACTED***
    values: dict[str, Any] = Field(..., description="全部非密钥设置项的当前值（已脱敏）")
    # 值被脱敏的键名列表；导入时应整键跳过，否则会把占位符写回配置
    redacted_keys: list[str] = Field(
        default_factory=list, description="值被脱敏的键名；导入时跳过这些键",
    )
    # 密钥清单：只报「有没有设置过」，不报任何形式的密钥值
    secrets: list[SecretPointOut] = Field(
        default_factory=list, description="密钥设置状态清单；只有键名与是否设置，没有密钥值",
    )


class SettingsImportIn(BaseModel):
    """配置导入的请求体（POST /api/settings/import，OPS-5）。

    直接把导出的 JSON 原样传回来即可；额外字段（exported_at / app_version 等）会被忽略。
    """

    # 导出格式标识；可选，传了就必须与后端一致
    format: str | None = Field(None, description="导出格式标识；传了就必须是 app-settings/1")
    # 键 → 值；只有本机声明过、值合法、且未被脱敏的键会被真正写入
    values: dict[str, Any] = Field(..., description="要导入的键值对；非法的键会出现在 skipped 里")
    # 导出时被脱敏的键名；这些键的值是占位符，必须跳过
    redacted_keys: list[str] = Field(
        default_factory=list, description="导出时被脱敏的键名；导入时跳过",
    )


class SettingsImportSkippedOut(BaseModel):
    """导入时被跳过的一个键，以及跳过原因（给用户看的中文说明）。"""

    # 被跳过的设置键
    key: str = Field(..., description="被跳过的设置键")
    # 跳过原因（中文，直接展示在设置页的提示里）
    reason: str = Field(..., description="跳过原因，可直接展示给用户")


class SettingsImportOut(BaseModel):
    """配置导入的响应体（POST /api/settings/import，OPS-5）。"""

    # 真正写进本机的键（升序）
    applied: list[str] = Field(default_factory=list, description="本次真正写入的设置键")
    # 被跳过的键及原因；为空表示整份配置都导入了
    skipped: list[SettingsImportSkippedOut] = Field(
        default_factory=list, description="被跳过的键及原因；为空表示全部导入成功",
    )
    # 导入后全部非密钥设置项的当前值，前端用它原地刷新设置页
    values: dict[str, Any] = Field(..., description="导入后全部非密钥设置项的当前值")


class SecretPutIn(BaseModel):
    """保存一个密钥的请求体（PUT /api/settings/secrets/{key}）。"""

    # 密钥明文；只进不出，保存后任何接口都不会再返回它
    value: str = Field(..., min_length=1, description="密钥明文；保存后不再原样返回")


class SecretStatusOut(BaseModel):
    """某个密钥的状态（GET /api/settings/secrets/{key}），只回显脱敏值。"""

    # 是否已设置
    set: bool = Field(..., description="该密钥是否已设置")
    # 脱敏后的展示值（形如 sk-****ijkl）；未设置时为 null
    masked: str | None = Field(None, description="脱敏后的密钥，形如 sk-****ijkl；未设置时为 null")