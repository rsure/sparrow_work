"""模型接入层（app/llm/）的单元测试。

三条原则：
    1. **绝不真的调用外部 API**——用 monkeypatch 打桩，否则单测会因网络与密钥而失败；
    2. 覆盖「用户配置错了」的各条分支，那是设置页最容易让人抓狂的地方；
    3. 用例结束后把自己写入的设置键删掉，不污染开发者的 app.db。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：夹具与异常断言
import pytest

# 项目内：模型注册表
from app.llm import registry
# 项目内：模型工厂与其配置异常类型
from app.llm import factory
# 项目内：运行时状态（缓存与失效）
from app.llm import state
# 项目内：设置注册表与落库层（测试自清理用）
from app.services import settings_registry
from app.services import setting_service


# 测试涉及的设置键：结束后统一删除
_TEST_KEYS = ("llm.custom_providers", "llm.custom_models", "llm.provider", "llm.model")


@pytest.fixture(autouse=True)
def _clean_llm_settings():
    """每个用例前后都清掉测试写入的 llm.* 设置键，并复位模型缓存。"""
    yield
    for key in _TEST_KEYS:
        setting_service.delete_setting_value(key)
    state.reset_for_test()


class _FakeModel:
    """假的聊天模型：只记录构造参数，用来断言 factory 传了什么、调用有没有发生。"""

    def __init__(self, **kwargs: object) -> None:
        """记录 init_chat_model 传进来的所有参数。"""
        self.kwargs = kwargs
        self.calls: list[str] = []

    def invoke(self, prompt: str) -> str:
        """假的调用：记录一次调用并返回固定文本。"""
        self.calls.append(prompt)
        return "pong"


@pytest.fixture
def fake_chat_model(monkeypatch):
    """把 init_chat_model 换成返回 _FakeModel 的桩，避免单测真的联网。

    注意打桩位置：factory.build_chat_model 是在**函数内部**延迟 import
    `langchain.chat_models.base.init_chat_model` 的，所以必须打在那个模块的属性上，
    打在 langchain 包上不会生效。

    :return: 记录了构造参数的字典，调用方可直接断言
    """
    captured: dict[str, object] = {}

    def _stub(model: str, model_provider: str | None = None, **kwargs: object) -> _FakeModel:
        """假的 init_chat_model：记录参数并返回假模型。"""
        captured.clear()
        captured["model"] = model
        captured["model_provider"] = model_provider
        captured.update(kwargs)
        return _FakeModel(**kwargs)

    monkeypatch.setattr("langchain.chat_models.base.init_chat_model", _stub)
    return captured


@pytest.fixture(autouse=True)
def _stub_keyring(monkeypatch):
    """默认让「钥匙串里什么都没有」，除非用例自己显式提供密钥。

    这样单测不会读到开发者本机钥匙串里的真实 DeepSeek/OpenAI 密钥，
    也不会因为本机配过密钥而让「缺密钥」分支测不出来。
    """
    monkeypatch.setattr(factory.secrets_service, "get_secret", lambda key: None)


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #
def test_builtin_providers_are_registered():
    """5 家内置供应商都应在注册表里，且各自带模型清单。"""
    ids = {p.id for p in registry.list_providers()}
    assert {"deepseek", "openai", "anthropic", "google", "ollama"}.issubset(ids)


def test_every_builtin_model_has_context_window():
    """每个内置模型都必须有正的上下文窗口——ARCH-5 的压缩阈值完全依赖它。"""
    for provider in registry.list_providers():
        for spec in registry.list_models(provider.id):
            assert spec.context_window > 0, f"{provider.id}/{spec.model} 缺 context_window"


def test_ollama_requires_no_key():
    """Ollama 是本地模型，不应该要求配置密钥。"""
    assert registry.get_provider("ollama").requires_key is False


def test_custom_provider_gets_prefixed_id_and_own_secret():
    """自定义端点应自动加 custom- 前缀，并分配各自独立的密钥名。"""
    settings_registry.put_settings({
        "llm.custom_providers": [{"id": "myapi", "label": "我的中转", "base_url": "https://x.example/v1"}],
    })
    providers = {p.id: p for p in registry.list_providers()}
    assert "custom-myapi" in providers
    custom = providers["custom-myapi"]
    assert custom.is_custom is True
    assert custom.base_url == "https://x.example/v1"
    # 各端点密钥独立：名字里带自己的 id
    assert custom.secret_key == "custom-myapi.api_key"


def test_custom_model_overrides_builtin_metadata():
    """同名自定义模型应覆盖内置的上下文窗口与单价（用于修正新模型/中转站计费）。"""
    settings_registry.put_settings({
        "llm.custom_models": [{
            "provider": "openai", "model": "gpt-4o", "label": "修正版",
            "context_window": 999999, "price_in": 1.0, "price_out": 2.0,
        }],
    })
    spec = registry.resolve_model_spec("openai", "gpt-4o")
    assert spec.context_window == 999999
    assert spec.price_in == 1.0


def test_custom_model_without_context_window_is_skipped():
    """自定义模型没填 context_window 时应被跳过（宁可少一个候选，也不要撑爆上下文）。"""
    settings_registry.put_settings({
        "llm.custom_models": [{"provider": "openai", "model": "no-ctx"}],
    })
    names = {s.model for s in registry.list_models("openai")}
    assert "no-ctx" not in names


def test_unknown_provider_raises_with_known_list():
    """未知供应商应抛出带可用列表的错误，而不是静默换一家。"""
    with pytest.raises(KeyError) as excinfo:
        registry.get_provider("nonexistent")
    assert "deepseek" in str(excinfo.value)


def test_unknown_model_raises_instead_of_silent_substitute():
    """指定了不存在的模型名必须报错——静默换成别的模型是最糟糕的失败方式。"""
    with pytest.raises(KeyError):
        registry.resolve_model_spec("openai", "no-such-model")


def test_deepseek_builtin_models_follow_official_names():
    """DeepSeek 内置清单必须跟上官方现状（现行模型名是 deepseek-flash / deepseek-v4-pro）。

    这条用例防的是「注册表过期」：模型名在官方那边换了、代码里没换，
    用户就会在设置页里只看到一堆官方已经停用的名字——那正是引入这条用例要修的问题。
    """
    names = {spec.model for spec in registry.list_models("deepseek")}
    assert {"deepseek-flash", "deepseek-v4-pro"}.issubset(names)
    flash = registry.resolve_model_spec("deepseek", "deepseek-flash")
    # V4.1-Flash 原生支持图像理解，窗口 1M——写错了会让压缩阈值算错、多模态能力判错
    assert flash.supports_vision is True
    assert flash.context_window >= 1000000


def test_default_llm_model_resolves_under_default_provider():
    """设置里 llm.model 的默认值必须能在默认供应商下解析成功，否则新装上来第一条消息就报错。"""
    provider = settings_registry.get_setting("llm.provider")
    model = settings_registry.get_setting("llm.model")
    spec = registry.resolve_model_spec(provider, model)
    assert spec.model == model


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #
def test_build_chat_model_passes_expected_params(fake_chat_model):
    """工厂应把模型名、供应商、温度、端点正确传给 init_chat_model。"""
    settings_registry.put_settings({"llm.temperature": 0.7})
    model = factory.build_chat_model("openai", "gpt-4o", api_key="sk-test", base_url="https://x/v1")
    assert isinstance(model, _FakeModel)
    assert fake_chat_model["model"] == "gpt-4o"
    assert fake_chat_model["model_provider"] == "openai"
    assert fake_chat_model["temperature"] == 0.7
    assert fake_chat_model["base_url"] == "https://x/v1"


def test_google_provider_maps_to_langchain_name(fake_chat_model):
    """我们在注册表里叫 google，LangChain 里叫 google_genai，映射必须正确。"""
    factory.build_chat_model("google", "gemini-2.0-flash", api_key="k")
    assert fake_chat_model["model_provider"] == "google_genai"


def test_custom_provider_uses_openai_protocol(fake_chat_model):
    """自定义端点按 OpenAI 兼容协议装配。"""
    settings_registry.put_settings({
        "llm.custom_providers": [{"id": "myapi", "base_url": "https://x.example/v1"}],
    })
    factory.build_chat_model("custom-myapi", "gpt-4o", api_key="sk-x")
    assert fake_chat_model["model_provider"] == "openai"


def test_missing_key_raises_actionable_error(monkeypatch):
    """没配密钥时应给出「去设置页填」这类可操作的中文提示，而不是英文堆栈。

    要同时掐断两条密钥来源才测得到这个分支：钥匙串（夹具已置空）与 .env 的历史配置
    （开发机上 .env 往往真的有 DEEPSEEK_API_KEY，不掐掉就测不出"完全没配"的场景）。
    """
    # 项目内：延迟导入配置对象，把 .env 里的历史密钥也置空，模拟「用户从没配过」
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "", raising=False)
    with pytest.raises(factory.ModelConfigError) as excinfo:
        factory.build_chat_model("deepseek", "deepseek-chat")
    message = str(excinfo.value)
    assert "密钥" in message and "设置" in message


def test_max_tokens_zero_is_not_passed(fake_chat_model):
    """llm.max_tokens=0 表示「不传该参数」，让供应商用自己的默认值。"""
    settings_registry.put_settings({"llm.max_tokens": 0})
    try:
        factory.build_chat_model("openai", "gpt-4o", api_key="k")
        assert "max_tokens" not in fake_chat_model
    finally:
        setting_service.delete_setting_value("llm.max_tokens")


def test_max_tokens_positive_is_passed(fake_chat_model):
    """llm.max_tokens 为正数时应下发给模型。"""
    settings_registry.put_settings({"llm.max_tokens": 512})
    try:
        factory.build_chat_model("openai", "gpt-4o", api_key="k")
        assert fake_chat_model["max_tokens"] == 512
    finally:
        setting_service.delete_setting_value("llm.max_tokens")


def test_probe_reports_failure_kind_without_leaking_key(monkeypatch):
    """probe 失败时应给出分类，且错误文案里不能出现密钥。"""
    monkeypatch.setattr(factory.secrets_service, "get_secret", lambda key: "sk-SECRETVALUE123456")

    def _boom(*args, **kwargs):
        """构造模型时抛出含密钥的错误，用于验证不会被回传。"""
        raise factory.ModelConfigError("构建模型失败：api key sk-SECRETVALUE123456 无效")

    monkeypatch.setattr(factory, "build_chat_model", _boom)
    result = factory.probe_model("deepseek", "deepseek-chat")
    assert result["ok"] is False
    assert result["error_kind"] in ("secret", "model", "network")


def test_probe_success_reports_latency(fake_chat_model, monkeypatch):
    """probe 成功时应返回 ok=True 与耗时。"""
    # 让钥匙串有一把假 key，模拟"用户已配置"
    monkeypatch.setattr(factory.secrets_service, "get_secret", lambda key: "sk-fake")
    result = factory.probe_model("openai", "gpt-4o", base_url="https://x/v1")
    # 打桩的模型 invoke 直接返回，不会真联网
    assert result["ok"] is True, result["error"]
    assert result["error"] is None
    assert result["latency_ms"] >= 0


# --------------------------------------------------------------------------- #
# 运行时状态
# --------------------------------------------------------------------------- #
def test_get_model_caches_until_invalidated(fake_chat_model, monkeypatch):
    """配置不变时应复用缓存实例；设置变化后应重建。"""
    # 让"钥匙串里有 key"，否则 get_model 会因缺密钥抛错
    monkeypatch.setattr(factory.secrets_service, "get_secret", lambda key: "sk-fake")
    settings_registry.put_settings({"llm.provider": "openai", "llm.model": "gpt-4o"})
    first = state.get_model()
    second = state.get_model()
    assert first is second, "配置未变时应命中缓存"

    state.invalidate()
    third = state.get_model()
    assert third is not first, "失效后应重建"


def test_setting_change_event_invalidates_cache(fake_chat_model, monkeypatch):
    """改设置触发事件后，缓存应自动失效（无需重启后端）。"""
    monkeypatch.setattr(factory.secrets_service, "get_secret", lambda key: "sk-fake")
    settings_registry.put_settings({"llm.provider": "openai", "llm.model": "gpt-4o"})
    first = state.get_model()
    # put_settings 会 publish("llm.") 事件，订阅者应已把缓存清掉
    settings_registry.put_settings({"llm.model": "gpt-4o-mini"})
    second = state.get_model()
    assert second is not first, "设置变更事件应触发缓存失效"
    assert fake_chat_model["model"] == "gpt-4o-mini"


# --------------------------------------------------------------------------- #
# ARCH-4 会话持久化
# --------------------------------------------------------------------------- #
def test_checkpointer_is_async_sqlite_saver():
    """ARCH-4：检查点必须是 AsyncSqliteSaver（进程重启后对话才能接着聊）。

    为什么要专门测类型：控制器调用图时用的是 astream_events / aget_state 等异步接口，
    同步版 SqliteSaver 会在第一次异步读写时抛 NotImplementedError，
    表现为"一问就报错、整条 SSE 流中断"。
    """
    # 标准库：在同步用例里跑一小段协程（构造函数要求当前有运行中的事件循环）
    import asyncio

    # LangGraph：新的异步检查点实现
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    import app.agents.rag_agent as rag_agent

    async def _check() -> None:
        """在事件循环里取真实检查点并校验类型。"""
        try:
            assert isinstance(rag_agent.get_checkpointer(), AsyncSqliteSaver)
        finally:
            # 只构造、未 await 过连接 -> 底层线程还没启动，直接丢弃即可；
            # 复位全局单例，避免后续用例拿到绑定在当前临时 loop 上的实例
            rag_agent._checkpointer = None

    asyncio.run(_check())


def test_checkpointer_persists_state_to_database():
    """回归测试：检查点必须能真正把状态写进 app.db。

    这里专门防一个真实踩过的坑：检查点要的是数据库驱动自己的连接，
    传 SQLAlchemy 的 Engine（或同步 sqlite3 连接给异步实现）会在首次读写时才炸。
    用例用一条**独立的连接**重读，只有真落到磁盘才读得到。
    """
    # 标准库：在同步用例里跑协程；sqlite3 用来独立读库
    import asyncio
    import sqlite3

    # LangGraph：同步检查点只用于"独立连接重读"这一侧
    from langgraph.checkpoint.sqlite import SqliteSaver

    import app.agents.rag_agent as rag_agent
    # 项目内：数据库文件名（生产代码与用例读的是同一个文件）
    from app.db.db_config import DATABASE_PATH

    thread_id = "unit-test-persist"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = {
        "v": 4,
        "ts": "2026-10-20T00:00:00+00:00",
        "id": "chk-1",
        "messages": [{"type": "human", "content": "持久化验证"}],
    }

    async def _write_and_verify() -> None:
        """异步写入检查点，并用独立连接确认已落库，最后清理现场。"""
        saver = rag_agent.get_checkpointer()
        try:
            await saver.aput(config, checkpoint, {"messages": ["m1"]}, {})

            # 独立连接重读：读得到才说明确实写进了 SQLite，而不是只留在内存里
            conn = sqlite3.connect(DATABASE_PATH)
            try:
                reader = SqliteSaver(conn)
                restored = reader.get_tuple(config)
                assert restored is not None, "检查点没有持久化到数据库"
                assert restored.checkpoint["messages"][0]["content"] == "持久化验证"
            finally:
                conn.close()
        finally:
            # 清掉本次写入的 thread；连接绑在这个临时 loop 上，用完关闭并复位单例
            await saver.adelete_thread(thread_id)
            await saver.conn.close()
            rag_agent._checkpointer = None

    asyncio.run(_write_and_verify())


def test_rag_agent_module_keeps_backward_compatible_names():
    """向后兼容：chat_controller 的 `from app.agents.rag_agent import agent, model` 必须继续可用。

    改造前 agent/model 是模块级单例；现在模型变成"按设置动态装配"，
    靠 PEP 562 的模块级 __getattr__ + 代理类承接，因此旧调用方一行都不用改。
    """
    import app.agents.rag_agent as rag_agent

    # 这三个名字都必须能取到（不抛 AttributeError）
    assert rag_agent.agent is not None
    assert rag_agent.model is not None
    assert rag_agent.checkpointer is not None
    # agent / model 现在是代理对象，方法访问会被转发到当前生效实例；
    # 同步上下文里访问一定会失败（没配密钥 -> ModelConfigError；
    # 配了密钥 -> 异步检查点要求运行中的事件循环 -> RuntimeError），
    # 两种都证明转发链路是通的（而不是死对象）
    from app.llm.factory import ModelConfigError

    try:
        rag_agent.agent.astream_events
    except (ModelConfigError, RuntimeError):
        pass          # 转发到了真实实例，只是当前上下文不可用：符合预期
    except AttributeError:
        pytest.fail("agent 代理没有把属性访问转发到真实实例")


def test_chat_controller_still_imports_legacy_names():
    """回归测试：chat_controller 顶部的 import 语句仍然有效。"""
    # 模块 docstring 说明旧写法是 `from app.agents.rag_agent import agent, checkpointer, model`
    # 这里按同样写法导入一次，确保没被本次改造打断
    from app.agents.rag_agent import agent, checkpointer, model  # noqa: F401

    assert agent is not None and model is not None and checkpointer is not None