# app/llm/factory.py
"""
模型工厂：把「供应商 + 模型名 + 密钥 + 端点」这一组配置装配成一个可用的聊天模型。

这是 ARCH-1 的核心出口——项目里**所有**需要模型的代码都必须经由 build_chat_model()，
不许再自己 new 一个 ChatDeepSeek/ChatOpenAI。否则密钥与参数会散落成两份，改一处漏一处。

密钥优先级（高→低）：
    1. 显式传入的 api_key（仅 probe 连通测试等内部调用会传）
    2. 系统钥匙串里该供应商的密钥（用户在设置页填的，见 services/secrets.py）
    3. .env 里的历史配置（settings.deepseek_api_key，仅 deepseek）——保证老配置继续可用

底座用 LangChain 的 init_chat_model 统一入口：它内部按 provider 名分派到对应的
Chat 类，参数名也基本统一（temperature / api_key / base_url），省掉我们自己维护一张
「参数名映射表」。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、dict[str, Any] 等新语法
from __future__ import annotations

# 标准库：延迟导入服务层，避免包初始化时的循环依赖
from typing import Any

# 项目内：模型注册表（取 ProviderSpec / ModelSpec、解析密钥名）
from app.llm import registry
# 项目内：密钥存储
from app.services import secrets as secrets_service


# LangChain 的 init_chat_model 认识的名字 → 本项目注册表里的 provider id 映射。
# 注意 google 在 LangChain 里叫 google_genai、ollama 叫 ollama，与我们的 id 略有差异。
_LANGCHAIN_PROVIDER_NAME: dict[str, str] = {
    "deepseek": "deepseek",
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google_genai",
    "ollama": "ollama",
}


class ModelConfigError(RuntimeError):
    """模型配置不合法（未知供应商 / 模型不存在 / 缺密钥）。

    单独一个异常类型，是为了让 llm_controller.probe 能把它与网络错误区分开，
    给用户不同的提示文案（"去设置页填密钥" vs "检查网络"）。
    """


def _resolve_api_key(provider_id: str, explicit: str | None) -> str | None:
    """按优先级解析出该供应商可用的 API 密钥。

    :param provider_id: 供应商 id
    :param explicit: 调用方显式传入的密钥（非空时直接用它）
    :return: 密钥字符串；确实没有配置时返回 None（由调用方决定是否报错）
    """
    if explicit:
        return explicit

    # 第2 级：系统钥匙串里用户在设置页填的那把
    secret_name = registry.secret_key_for(provider_id)
    if secret_name:
        try:
            stored = secrets_service.get_secret(secret_name)
        except Exception:
            stored = None
        if stored:
            return stored

    # 第 3 级：.env 的历史配置，仅 deepseek 有（保持向后兼容，老 .env 不用改）
    if provider_id == "deepseek":
        # 延迟导入：config 在应用启动早期才可用，避免包初始化顺序问题
        from app.config import settings

        if settings.deepseek_api_key:
            return settings.deepseek_api_key
    return None


def build_chat_model(
    provider_id: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any:
    """构建一个聊天模型实例（LangChain BaseChatModel）。

    :param provider_id: 供应商 id，如 "deepseek" / "openai" / "custom-myapi"
    :param model: 模型名；为空时取该供应商的默认模型
    :param api_key: 显式密钥；一般不传（走钥匙串/环境变量）
    :param base_url: 显式接口地址；为空时用设置里的 llm.base_url，再为空则用供应商默认地址
    :param temperature: 采样温度；None 表示用设置里的 llm.temperature
    :param max_tokens: 单轮生成上限；None 或 0 表示不传该参数（用供应商默认）
    :return: 可直接喂给 create_agent() 的聊天模型实例
    :raises ModelConfigError: 供应商未知、模型不存在、或缺少必需的密钥
    """
    # ---- 1. 解析供应商与模型规格 ----
    try:
        spec = registry.resolve_model_spec(provider_id, model or None)
        provider = registry.get_provider(provider_id)
    except KeyError as e:
        # 未知供应商/模型属于「配置错了」，不是运行时故障，转成可读的配置错误
        raise ModelConfigError(str(e).strip("'")) from e

    langchain_name = _LANGCHAIN_PROVIDER_NAME.get(provider_id)
    if langchain_name is None:
        # 自定义端点一律按 OpenAI 兼容协议处理（用户自定义 provider 的前提就是这个）
        langchain_name = "openai"

    # ---- 2. 解析密钥 ----
    key = _resolve_api_key(provider_id, api_key)
    if provider.requires_key and not key:
        raise ModelConfigError(
            f"尚未配置 {provider.label} 的 API 密钥，请到设置页的「模型」分区填写"
            f"（对应设置项：{provider.secret_key}）"
        )

    # ---- 3. 解析接口地址：显式参数 > 设置里的 llm.base_url > 供应商默认 ----
    endpoint = base_url
    if endpoint is None:
        endpoint = _configured_base_url(provider_id)
    if not endpoint:
        endpoint = provider.base_url or None

    # ---- 4. 解析采样参数 ----
    if temperature is None:
        temperature = _configured_float("llm.temperature", 0.0)
    if max_tokens is None:
        # 0 表示「不传」，让供应商用自己的默认值（doc/27 §5.2 的约定）
        max_tokens = _configured_int("llm.max_tokens", 0) or None

    # ---- 5. 装配 ----
    kwargs: dict[str, Any] = {"temperature": temperature}
    if key:
        kwargs["api_key"] = key
    if endpoint:
        # Ollama 用 base_url 指向本地服务；OpenAI 兼容端点同理
        kwargs["base_url"] = endpoint
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    # 延迟导入：init_chat_model 会连带探测各 provider 的可选依赖，放到函数内避免拖慢启动
    from langchain.chat_models.base import init_chat_model

    try:
        return init_chat_model(model=spec.model, model_provider=langchain_name, **kwargs)
    except Exception as e:
        # 底座构造失败（常见于「provider 包没装」或「参数名不被支持」），
        # 转成配置错误并带上原始原因，方便前端/日志排查
        raise ModelConfigError(f"构建模型失败（{provider_id}/{spec.model}）：{e}") from e


def _configured_base_url(provider_id: str) -> str:
    """读取设置里的接口地址（llm.base_url）。

    只对 OpenAI 兼容类端点有意义；deepseek/anthropic 等官方端点若被填了地址，
    这里仍然尊重用户配置（有些用户确实走代理），因此不做provider 过滤。

    :param provider_id: 供应商 id（保留形参便于将来按供应商分别配地址）
    :return: 配置的地址字符串；未配置时返回空串
    """
    try:
        from app.services.settings_registry import get_setting

        return str(get_setting("llm.base_url") or "")
    except Exception:
        return ""


def _configured_float(key: str, fallback: float) -> float:
    """读取一个浮点型设置项，读不到或非法时返回兜底值。"""
    try:
        from app.services.settings_registry import get_setting

        return float(get_setting(key))
    except Exception:
        return fallback


def _configured_int(key: str, fallback: int) -> int:
    """读取一个整型设置项，读不到或非法时返回兜底值。"""
    try:
        from app.services.settings_registry import get_setting

        return int(get_setting(key))
    except Exception:
        return fallback


def probe_model(provider_id: str, model: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    """发一次极小的请求，验证「密钥对不对、模型名存不存在、网络通不通」。

    设置页的「测试连接」按钮调的就是它（POST /api/llm/probe）。

    :param provider_id: 要测的供应商
    :param model: 要测的模型名；为空时用该供应商的默认模型
    :param base_url: 要测的端点；为空时用设置里的地址
    :return: {"ok": 是否成功, "latency_ms": 耗时毫秒, "error": 失败原因或 None,
             "error_kind": 失败分类 secret/model/network/unknown（成功时为 None）}
    """
    # 标准库：计时，用于给出"延迟 xx ms"这种用户能直观判断快慢的反馈
    import time

    started = time.perf_counter()
    try:
        chat = build_chat_model(provider_id, model, base_url=base_url)
        # 只让它说一个词，尽量少消耗额度；但必须真的走一次网络才能验证连通性
        chat.invoke("ping")
    except ModelConfigError as e:
        # 配置类错误：密钥没配/ 模型名不存在/ 依赖没装
        kind = "secret" if "密钥" in str(e) else "model"
        return {"ok": False, "latency_ms": _elapsed_ms(started), "error": str(e), "error_kind": kind}
    except Exception as e:
        # 其它错误：绝大多数是网络/鉴权/服务端问题
        text = str(e)
        kind = "secret" if _looks_like_auth_error(text) else "network"
        return {"ok": False, "latency_ms": _elapsed_ms(started), "error": text[:300], "error_kind": kind}
    return {"ok": True, "latency_ms": _elapsed_ms(started), "error": None, "error_kind": None}


#各家 SDK 的鉴权失败文案差异很大，这里用关键字粗判，够用来给用户不同提示即可
_AUTH_ERROR_HINTS = ("api key", "unauthorized", "authentication", "invalid.*key", "401", "403")


def _looks_like_auth_error(text: str) -> bool:
    """粗判一个异常是不是「密钥不对」导致的。

    :param text: 异常字符串
    :return: 命中鉴权相关关键字时返回 True
    """
    lowered = text.lower()
    return any(hint in lowered for hint in _AUTH_ERROR_HINTS)


def _elapsed_ms(started: float) -> int:
    """把 perf_counter 起点换算成毫秒耗时。

    :param started: time.perf_counter() 的起始值
    :return: 耗时毫秒数（整数）
    """
    import time

    return int((time.perf_counter() - started) * 1000)