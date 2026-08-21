# app/services/memory_settings_defs.py
"""工作空间记忆（MEM）的设置声明。

四个键的分工：
    memory.enabled          总开关。关掉后**读写两个 hook 都直接 return**，行为与加本模块前一致
    memory.extract_enabled  只关"写"：不再自动抽取（省一次 LLM 调用），已有记忆仍可检索
    memory.inject_enabled   只关"读"：不再往新对话里注入记忆（不影响抽取与接口查询）
    memory.top_k            注入条数
    memory.min_importance   检索时的重要度门槛（1~5）；调高可以少注入噪声
    memory.dedup_threshold  相似度去重阈值；调高会存下更多"近似重复"的记忆

MEM 增强（M6，2026-10-23）新增的 6 个键：
    memory.merge_enabled       近似重复时合并进已有记忆（而不是丢弃）
    memory.embedding_backend   向量化后端：local（本地哈希）/ remote（OpenAI 兼容 /embeddings）
    memory.embedding_provider  远端用哪个供应商的地址与密钥；留空=当前对话供应商
    memory.embedding_model     远端 embedding 模型名
    memory.ttl_days            低重要度记忆的保留天数（0=不按时间淘汰）
    memory.max_per_workspace   单工作区条数上限（0=不限制）

为什么"向量化"要拆成三个键而不是一个开关：
    后端（local/remote）、供应商（谁的地址与密钥）、模型名是三件独立的事——
    "我想用远端但走公司中转站的 bge-m3" 需要同时改后两者，而"我只想换模型"只需要改最后一个。
    合成一个 "memory.embedding" 字符串会逼用户记语法，也会让校验与设置页无法复用现成的控件。

为什么要拆成三个开关而不是一个：
    "抽取"要花一次模型调用，"注入"只花几百 token。用户可能想省钱但保留检索，
    也可能觉得注入干扰回答但愿意继续攒记忆。一个开关表达不了这两种诉求。

注意：`memory.enabled` / `memory.top_k` 原本声明在内置的 `advanced` 分区（M1 占位），
这里**重新声明**到 `memory` 分区。`register_defs` 明确允许后注册者覆盖，是有意的用法。
"""

# 项目内：设置声明与类型枚举
from app.services.settings_registry import SettingDef, SettingKind

# 本模块声明的全部设置项
MEMORY_DEFS: list[SettingDef] = [
    SettingDef(
        key="memory.enabled",
        label="工作空间记忆",
        kind=SettingKind.BOOL,
        default=True,
        category="memory",
        since="M4.5",
        description="记忆总开关。关闭后不再抽取也不再注入，对话行为与没有这个功能时完全一致",
    ),
    SettingDef(
        key="memory.extract_enabled",
        label="自动抽取记忆",
        kind=SettingKind.BOOL,
        default=True,
        category="memory",
        since="M4.5",
        description="每轮对话结束后自动抽取值得记住的信息（会多花一次模型调用，失败不影响对话）",
    ),
    SettingDef(
        key="memory.inject_enabled",
        label="新对话注入记忆",
        kind=SettingKind.BOOL,
        default=True,
        category="memory",
        since="M4.5",
        description="新对话的第一条消息会把本工作区的相关记忆附给模型（只给模型看，不会出现在回答里）",
    ),
    SettingDef(
        key="memory.top_k",
        label="注入记忆条数",
        kind=SettingKind.INT,
        default=5,
        min=1,
        max=20,
        category="memory",
        since="M4.5",
        description="每条新对话最多注入几条记忆；调小可以省 token",
    ),
    SettingDef(
        key="memory.min_importance",
        label="记忆重要度门槛",
        kind=SettingKind.INT,
        default=1,
        min=1,
        max=5,
        category="memory",
        since="M4.5",
        description="检索时只保留重要度不低于此值的记忆；设为 3 以上可以明显减少噪声",
    ),
    SettingDef(
        key="memory.dedup_threshold",
        label="记忆去重阈值",
        kind=SettingKind.FLOAT,
        default=0.85,
        min=0.5,
        max=1.0,
        category="memory",
        since="M4.5",
        description="相似度超过此值就判为重复、不再保存（默认 0.85 按实际相似度分布校准过）；调高会存下更多近似重复项",
    ),
    # ---- 以下 6 个键是 MEM 增强（2026-10-23）：合并 / 真 embedding / 过期淘汰 ----
    SettingDef(
        key="memory.merge_enabled",
        label="合并近似记忆",
        kind=SettingKind.BOOL,
        default=True,
        category="memory",
        since="M6",
        description="相似度超过去重阈值时不丢弃，而是合并进已有记忆（保留更完整的正文、重要度取大）；关闭则退回「直接跳过」",
    ),
    SettingDef(
        key="memory.embedding_backend",
        label="向量化后端",
        kind=SettingKind.SELECT,
        default="local",
        options=("local", "remote"),
        option_labels=("本地哈希（快、免费、只认字面）", "远端 embedding（懂语义，需要密钥与网络）"),
        category="memory",
        since="M6",
        description="本地哈希零依赖但不懂语义；远端走 OpenAI 兼容的 /embeddings 接口，失败时自动降级本地",
    ),
    SettingDef(
        key="memory.embedding_provider",
        label="远端向量化供应商",
        kind=SettingKind.STRING,
        default="",
        category="memory",
        since="M6",
        description="用哪个已配置的供应商调 embedding（如 openai / custom-xxx）；留空表示当前对话供应商",
    ),
    SettingDef(
        key="memory.embedding_model",
        label="远端向量模型",
        kind=SettingKind.STRING,
        default="text-embedding-3-small",
        category="memory",
        since="M6",
        description="OpenAI 兼容端点的 embedding 模型名（如 text-embedding-3-small / bge-m3）",
    ),
    SettingDef(
        key="memory.ttl_days",
        label="低价值记忆保留天数",
        kind=SettingKind.INT,
        default=180,
        min=0,
        max=3650,
        category="memory",
        since="M6",
        description="重要度 ≤2 且这么久没被检索命中的记忆会被清理；0 表示不按时间淘汰（重要度 3 以上永不因过期删除）",
    ),
    SettingDef(
        key="memory.max_per_workspace",
        label="单工作区记忆上限",
        kind=SettingKind.INT,
        default=500,
        min=0,
        max=5000,
        category="memory",
        since="M6",
        description="超过上限时按「重要度低、最久没用、最早创建」的顺序清理；0 表示不限制",
    ),
]


def register_memory_defs() -> None:
    """把记忆的设置声明注册进全局注册表（重复调用安全）。"""
    # 项目内：注册表入口
    from app.services.settings_registry import register_defs

    register_defs(MEMORY_DEFS)
