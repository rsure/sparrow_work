# app/llm/registry.py
"""
模型注册表：描述「有哪些模型供应商、各自有哪些模型、每个模型什么脾气」。

为什么要这张表（对应 doc/21 ARCH-1 §1.5.A）：
    模型清单如果写死在代码里，用户遇到新模型就只能等我们发版；而「上下文窗口」这种
    能力元数据更是无处可取——ARCH-5 决定何时压缩对话时，需要知道当前模型能吃下多少 token。
    所以把「模型」当成**数据**来声明：本文件放内置的，用户可通过 `llm.custom_models`
    追加自定义的，同provider+model 时自定义覆盖内置（用来修正单价、上下文窗口等）。

三层数据：
    ProviderSpec —— 一家供应商：id / 展示名 / 默认 base_url / 密钥名/ 协议类
    ModelSpec    —— 一个模型：名字 / 展示名 / 上下文窗口 / 是否支持工具与图片 / 单价
    「自定义供应商」—— 用户的 OpenAI 兼容中转站，在 ProviderSpec 层追加
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、dict[str, Any] 等新语法
from __future__ import annotations

# 标准库：dataclass 描述 ProviderSpec / ModelSpec（不可变声明）
from dataclasses import dataclass, field
# 标准库：Any 标注自定义模型的额外字段
from typing import Any

# 项目内：设置注册表，读llm.custom_models / llm.custom_providers 两个用户自定义项
from app.services.settings_registry import get_setting


# --------------------------------------------------------------------------- #
# 1. 声明结构
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelSpec:
    """一个模型的静态描述：调用时需要的信息 + 影响上层决策的能力元数据。"""

    # API 调用用的模型名（如 "deepseek-chat"）
    model: str
    # 展示给用户看的名字（如 "DeepSeek Chat"）
    label: str
    # 上下文窗口上限（单位：token）——ARCH-5 压缩阈值的分母来源。
    # 用户自定义模型必须提供，否则压缩策略只能保守按 32k 处理。
    context_window: int
    # 是否支持工具调用（function calling）。为 False 的模型不出现在对话默认候选里
    supports_tools: bool = True
    # 是否支持图片输入（预留字段：首版 UI 只展示，不启用多模态）
    supports_vision: bool = False
    # 每百万输入 token 的价格（单位：元），用于 UX-5 成本统计
    price_in: float = 0.0
    # 每百万输出 token 的价格（单位：元）
    price_out: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转成接口下发的字典形状（供 GET /api/llm/models 返回给前端）。"""
        return {
            "model": self.model,
            "label": self.label,
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "price_in": self.price_in,
            "price_out": self.price_out,
        }


@dataclass(frozen=True)
class ProviderSpec:
    """一家模型供应商的静态描述。"""

    # 供应商 id，全局唯一；内置为 deepseek/openai/anthropic/google/ollama，
    # 用户自定义的以 "custom-" 开头（见 §4 冲突消解）
    id: str
    # 展示名（设置页下拉里显示）
    label: str
    # 默认接口地址；空串表示用该供应商的官方默认地址
    base_url: str = ""
    # 密钥在钥匙串里的名字（**不带 "secrets." 前缀**），如 "deepseek.api_key"
    secret_key: str = ""
    # 是否需要密钥：Ollama 跑在本地，不需要
    requires_key: bool = True
    # 该供应商的模型清单
    models: tuple[ModelSpec, ...] = field(default_factory=tuple)
    # 是否为用户自定义的供应商（前端展示时加以区分，如"自定义"标签）
    is_custom: bool = False


# --------------------------------------------------------------------------- #
# 2. 内置供应商与模型清单
# --------------------------------------------------------------------------- #
# 说明：context_window 与单价取各厂商公开文档的量级值，仅用于「何时压缩」与「大概花多少钱」
# 的估算，不用于计费——真实计费以供应商返回的 usage 为准（见 doc/21 ARCH-1 §1.5.D）。
_BUILTIN_PROVIDERS: tuple[ProviderSpec, ...] = (
    # ---- DeepSeek：默认供应商 ----
    # 清单按官方「模型 & 价格」页维护（https://api-docs.deepseek.com/zh-cn/quick_start/pricing）。
    # 官方改名/停用模型时**只需要改这里**：设置页的模型下拉、顶栏模型 chip、上下文压缩阈值
    # 全都从这里读，不用再去前端改任何硬编码的模型名。
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        secret_key="deepseek.api_key",
        models=(
            # 官方现行主力模型（2026-09 发布，2026-10 更新到 -1017）：1M 上下文、原生支持图像理解
            ModelSpec(model="deepseek-flash", label="DeepSeek V4.1 Flash", context_window=1000000,
                      supports_vision=True, price_in=2.0, price_out=8.0),
            # 官方现行旗舰：推理与 Agent 能力更强，不支持图像理解，单价约为 Flash 的 4.5 倍
            ModelSpec(model="deepseek-v4-pro", label="DeepSeek V4 Pro", context_window=1000000,
                      price_in=9.0, price_out=27.0),
            # 兼容名：V4-Flash 本体已下线，官方把这两个名字临时路由到 V4.1-Flash，按 Flash 计费
            ModelSpec(model="deepseek-v4-flash", label="DeepSeek V4 Flash（兼容名，指向 V4.1）",
                      context_window=1000000, supports_vision=True, price_in=2.0, price_out=8.0),
            # 已停用名：deepseek-chat / deepseek-reasoner 官方已于 2026-07-24 停止服务。
            # 仍然留在清单里，只为了让「以前存过的 llm.model」不至于直接报 KeyError，
            # label 里写明该换成哪个新名字，设置页一眼能看到。
            ModelSpec(model="deepseek-chat", label="DeepSeek Chat（已停用，请改用 deepseek-flash）",
                      context_window=1000000, supports_vision=True, price_in=2.0, price_out=8.0),
            ModelSpec(model="deepseek-reasoner", label="DeepSeek Reasoner（已停用，请改用 deepseek-flash）",
                      context_window=1000000, price_in=2.0, price_out=8.0),
        ),
    ),
    # ---- OpenAI：base_url 可配，天然覆盖各类中转站与本地兼容端点 ----
    ProviderSpec(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        secret_key="openai.api_key",
        models=(
            ModelSpec(model="gpt-4o", label="GPT-4o", context_window=128000,
                      supports_vision=True, price_in=18.0, price_out=72.0),
            ModelSpec(model="gpt-4o-mini", label="GPT-4o mini", context_window=128000,
                      supports_vision=True, price_in=1.1, price_out=4.3),
        ),
    ),
    # ---- Anthropic Claude ----
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        base_url="https://api.anthropic.com",
        secret_key="anthropic.api_key",
        models=(
            ModelSpec(model="claude-sonnet-4-20250514", label="Claude Sonnet 4", context_window=200000,
                      supports_vision=True, price_in=22.0, price_out=110.0),
            ModelSpec(model="claude-3-5-haiku-20241022", label="Claude Haiku 3.5", context_window=200000,
                      price_in=6.0, price_out=30.0),
        ),
    ),
    # ---- Google Gemini ----
    ProviderSpec(
        id="google",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com",
        secret_key="google.api_key",
        models=(
            ModelSpec(model="gemini-2.0-flash", label="Gemini 2.0 Flash", context_window=1000000,
                      supports_vision=True, price_in=5.0, price_out=15.0),
        ),
    ),
    # ---- Ollama：本地模型，不需要密钥 ----
    ProviderSpec(
        id="ollama",
        label="Ollama（本地）",
        base_url="http://127.0.0.1:11434",
        secret_key="",
        requires_key=False,
        models=(
            ModelSpec(model="qwen2.5:7b", label="Qwen2.5 7B", context_window=32768),
            ModelSpec(model="llama3.1:8b", label="Llama 3.1 8B", context_window=131072),
        ),
    ),
)

# 内置供应商按 id 索引，list_providers/list_models 遍历用
_BUILTIN_BY_ID: dict[str, ProviderSpec] = {p.id: p for p in _BUILTIN_PROVIDERS}

# 上下文窗口未知时的保守兜底值（单位：token）：
# 用户自定义模型若没填 context_window，就按这个值算压缩阈值，宁可早压缩也不要撑爆上下文。
DEFAULT_CONTEXT_WINDOW = 32000


# --------------------------------------------------------------------------- #
# 3. 供应商查询
# --------------------------------------------------------------------------- #
def _custom_providers() -> list[dict[str, Any]]:
    """读取用户配置的自定义 OpenAI 兼容端点（llm.custom_providers）。

    :return: 每项形如 {"id": "myapi", "label": "我的中转", "base_url": "https://..."}；
             未配置或配置损坏时返回空列表（不让一个坏设置拖垮整个模型列表）
    """
    try:
        raw = get_setting("llm.custom_providers")
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("id")]


def list_providers() -> list[ProviderSpec]:
    """列出全部可用供应商：内置 5 家 + 用户自定义的 OpenAI 兼容端点。

    :return: ProviderSpec 列表（自定义的 is_custom=True）
    """
    providers = list(_BUILTIN_PROVIDERS)
    for item in _custom_providers():
        raw_id = str(item.get("id") or "").strip()
        if not raw_id:
            continue
        # 自定义供应商统一加 "custom-" 前缀，避免与内置 id 撞名（见 §4）
        provider_id = raw_id if raw_id.startswith("custom-") else f"custom-{raw_id}"
        base_url = str(item.get("base_url") or "").strip()
        providers.append(ProviderSpec(
            id=provider_id,
            label=str(item.get("label") or provider_id),
            base_url=base_url,
            # 各端点密钥独立存放，名字形如 custom-myapi.api_key（见 doc/21 ARCH-1 §1.5.B）
            secret_key=f"{provider_id}.api_key",
            requires_key=True,
            models=(),
            is_custom=True,
        ))
    return providers


def get_provider(provider_id: str) -> ProviderSpec:
    """按 id 取一个供应商的描述。

    :param provider_id: 供应商 id，如 "deepseek" 或 "custom-myapi"
    :return: ProviderSpec
    :raises KeyError: id 未内置也未配置为自定义端点（调用方应转成明确的中文错误）
    """
    if provider_id in _BUILTIN_BY_ID:
        return _BUILTIN_BY_ID[provider_id]
    for provider in list_providers():
        if provider.id == provider_id:
            return provider
    known = "、".join(p.id for p in list_providers())
    raise KeyError(f"未知的模型供应商 {provider_id!r}；当前可选：{known}")


def secret_key_for(provider_id: str) -> str:
    """取某个供应商的密钥名（不带 secrets. 前缀，如 "deepseek.api_key"）。

    :param provider_id: 供应商 id
    :return: 钥匙串里的键名；该供应商不需要密钥时返回空串
    """
    return get_provider(provider_id).secret_key


def _is_custom_endpoint(provider_id: str) -> bool:
    """判断某个 id 是不是用户自定义的端点（而不是内置供应商）。

    :param provider_id: 供应商 id
    :return: True 表示是自定义端点；id 未注册时返回 False（由调用方另行报错）
    """
    try:
        return get_provider(provider_id).is_custom
    except KeyError:
        return False


# --------------------------------------------------------------------------- #
# 4. 模型查询
# --------------------------------------------------------------------------- #
def _custom_models() -> list[dict[str, Any]]:
    """读取用户配置的自定义模型列表（llm.custom_models）。

    :return: 每项形如 {"provider":"openai","model":"xxx","label":"...","context_window":128000,
             "supports_tools":true,"price_in":..,"price_out":..}；配置损坏时返回空列表
    """
    try:
        raw = get_setting("llm.custom_models")
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("model")]


def _parse_custom_model(item: dict[str, Any]) -> ModelSpec | None:
    """把一条用户自定义模型配置解析成 ModelSpec。

    必填项缺失（比如没有 context_window）时返回 None 并被调用方跳过——
    宁可少一个候选，也不要拿一个"不知道能吃多少 token"的模型去跑对话。

    :param item: 用户配置的一行（已确认是 dict）
    :return: 解析成功的 ModelSpec；字段不合法时为 None
    """
    model = str(item.get("model") or "").strip()
    if not model:
        return None
    # 自定义模型必须给上下文窗口：ARCH-5 的压缩阈值完全依赖它，缺了就无法安全压缩
    try:
        context_window = int(item.get("context_window") or 0)
    except (TypeError, ValueError):
        return None
    if context_window <= 0:
        return None
    return ModelSpec(
        model=model,
        label=str(item.get("label") or model),
        context_window=context_window,
        supports_tools=bool(item.get("supports_tools", True)),
        supports_vision=bool(item.get("supports_vision", False)),
        price_in=float(item.get("price_in") or 0.0),
        price_out=float(item.get("price_out") or 0.0),
    )


def list_models(provider_id: str) -> list[ModelSpec]:
    """列出某个供应商下可选的模型：内置清单 ∪ 自定义清单。

    同一 provider+model 时**自定义覆盖内置**——用户加一个同名模型通常是为了修正
    上下文窗口或单价（新模型发布但我们还没更新注册表、或中转站改了计费）。

    :param provider_id: 供应商 id
    :return: ModelSpec 列表；未知供应商时抛 KeyError
    """
    provider = get_provider(provider_id)
    merged: dict[str, ModelSpec] = {m.model: m for m in provider.models}
    # 自定义模型可以挂在任何供应商下（包括 custom-* 端点），按 provider 字段过滤
    for item in _custom_models():
        owner = str(item.get("provider") or "").strip()
        if owner != provider_id:
            continue
        spec = _parse_custom_model(item)
        if spec is not None:
            merged[spec.model] = spec   # 覆盖内置同名项
    return list(merged.values())


def resolve_model_spec(provider_id: str, model_name: str | None = None) -> ModelSpec:
    """解析出「当前该用哪个模型」的描述（拿不到精确匹配时给出可用模型的第一个）。

    调用方（llm/factory.py）拿这个结果来取上下文窗口与温度等参数。

    自定义端点的特殊处理（重要）：
        一个自定义 OpenAI 兼容端点背后可能挂着任意模型（中转站经常同时代理几十个模型），
        我们不可能预置清单。如果用户显式给了模型名，就直接按"临时规格"接受它，
        上下文窗口保守取 DEFAULT_CONTEXT_WINDOW——**而不是**报"没有这个模型"。
        否则用户每次接一个新中转站都得先去设置页手工登记一遍模型名才能用，非常反直觉。
        只有在连模型名都没给时，才因为"无从选择"而报错。

    :param provider_id: 供应商 id
    :param model_name: 指定的模型名；为空或None 时取该供应商的第一个模型
    :return: ModelSpec
    :raises KeyError: 供应商未知，或既没给模型名、该供应商也没有任何可选模型
    """
    candidates = list_models(provider_id)
    if model_name:
        for spec in candidates:
            if spec.model == model_name:
                return spec
        # 精确匹配到了就返回（上面的循环）；走到这里说明清单里没有这个名字
        if _is_custom_endpoint(provider_id):
            # 自定义端点：接受用户给的任意模型名，按保守元数据构造
            return ModelSpec(
                model=model_name,
                label=model_name,
                context_window=DEFAULT_CONTEXT_WINDOW,
                price_in=0.0,   # 未知单价：成本统计里按 0 算，比猜一个数字更诚实
                price_out=0.0,
            )
        # 内置供应商：指定了但清单里没有。不静默换模型（用户以为在用 A 实际跑了 B 最糟），
        # 直接报错，让上层提示"该供应商下没有这个模型"
        known = "、".join(m.model for m in candidates) or "（该供应商暂无预置模型）"
        raise KeyError(f"供应商 {provider_id} 下没有模型 {model_name!r}；可选：{known}")
    if not candidates:
        raise KeyError(f"供应商 {provider_id} 下没有任何可选模型，请在设置里补充自定义模型")
    return candidates[0]


def current_provider_and_model() -> tuple[str, str]:
    """读取「当前生效的供应商与模型」（来自设置，未配置时用注册表第一个）。

    这是 llm/state.py 构建 agent 时的入口。

    :return: (provider_id, model_name) 二元组
    """
    try:
        provider_id = str(get_setting("llm.provider") or "deepseek")
    except Exception:
        provider_id = "deepseek"
    try:
        # 模型名为空时留空，交给 resolve_model_spec 取该供应商的默认模型
        model_name = str(get_setting("llm.model") or "")
    except Exception:
        model_name = ""
    return provider_id, model_name