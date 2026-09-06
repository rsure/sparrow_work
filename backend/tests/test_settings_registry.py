"""设置声明式注册表（services/settings_registry.py）的单元测试。

与 tests/conftest.py 的约定一致：本文件用例会写真实 app.db，
因此每个会写库的用例都用 `_clean_keys` fixture 在结束后把自己写的键删掉，
避免污染开发者的本地设置。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：pytest.fixture 定义夹具，pytest.raises 断言异常
import pytest

# 项目内：注册表与声明类型、注册表重置
from app.services.settings_registry import (
    BUILTIN_DEFS,
    SettingDef,
    SettingKind,
    SettingsChangeEvent,
    get_all_settings,
    get_setting,
    list_defs,
    publish,
    put_settings,
    register_defs,
    reset_for_test,
    subscribe,
    unsubscribe,
)
# 项目内：落库层，测试用它做清理
from app.services import setting_service


# 测试专用键名：用 __test__ 前缀，避免与真实设置键冲突
_TEST_KEY = "__test__.flag"
_TEST_INT = "__test__.count"
_TEST_FLOAT = "__test__.ratio"
_TEST_SELECT = "__test__.mode"
_TEST_JSON = "__test__.items"

# 本文件用到的全部测试键：夹具结束后统一删除
_ALL_TEST_KEYS = [_TEST_KEY, _TEST_INT, _TEST_FLOAT, _TEST_SELECT, _TEST_JSON]


@pytest.fixture(autouse=True)
def _isolate_registry():
    """每个用例前后都重建注册表，保证用例之间互不影响。

    会做的事：
        1. 用例前：注册一份只含测试键的最小注册表（不依赖应用启动时的注册）；
        2. 用例后：删掉本用例可能写入的键 + 重置注册表与订阅表。
    """
    reset_for_test()
    register_defs([
        SettingDef(key=_TEST_KEY, kind=SettingKind.BOOL, default=False, category="advanced", description="测试开关"),
        SettingDef(key=_TEST_INT, kind=SettingKind.INT, default=7, min=1, max=100, category="advanced"),
        SettingDef(key=_TEST_FLOAT, kind=SettingKind.FLOAT, default=0.5, min=0.0, max=1.0, category="advanced"),
        SettingDef(key=_TEST_SELECT, kind=SettingKind.SELECT, default="a", options=("a", "b"), category="advanced"),
        SettingDef(key=_TEST_JSON, kind=SettingKind.JSON, default=[], category="advanced"),
    ])
    yield
    for key in _ALL_TEST_KEYS:
        setting_service.delete_setting_value(key)
    reset_for_test()


def test_get_setting_falls_back_to_declared_default():
    """未落库的键应返回声明默认值，而不是 None（调用方无需写 if-else 兜底）。"""
    assert get_setting(_TEST_KEY) is False
    assert get_setting(_TEST_INT) == 7
    assert get_setting(_TEST_JSON) == []


def test_get_setting_unknown_key_raises():
    """读一个没声明的键必须抛 KeyError，而不是静默返回 None。"""
    with pytest.raises(KeyError):
        get_setting("__test__.not_declared")


def test_put_settings_validates_type_and_range():
    """类型不符或越界的值应被拒绝，且不落库。"""
    with pytest.raises(ValueError):
        put_settings({_TEST_KEY: "yes"})       # bool 位不接受字符串
    with pytest.raises(ValueError):
        put_settings({_TEST_INT: 500})         # 超过 max=100
    with pytest.raises(ValueError):
        put_settings({_TEST_INT: 0})           # 小于 min=1
    with pytest.raises(ValueError):
        put_settings({_TEST_SELECT: "z"})      # 不在 options 候选内
    # 全部失败后，值不应被写进库里
    assert get_setting(_TEST_INT) == 7


def test_put_settings_rejects_bool_for_numeric():
    """bool 是 int 的子类，但 true 不应被当成整数 1 存下来（几乎一定是前端 bug）。"""
    with pytest.raises(ValueError):
        put_settings({_TEST_INT: True})
    with pytest.raises(ValueError):
        put_settings({_TEST_FLOAT: False})


def test_put_settings_persists_and_returns_all():
    """写入成功后应能从库里读回，且返回全量设置值。"""
    put_settings({_TEST_INT: 42, _TEST_KEY: True})
    assert get_setting(_TEST_INT) == 42
    assert get_setting(_TEST_KEY) is True
    values = get_all_settings()
    assert values[_TEST_INT] == 42
    assert set(_ALL_TEST_KEYS).issubset(values.keys())


def test_put_settings_rejects_unknown_key_atomically():
    """批量写入里只要有一个键非法，整批都不应落库（避免写一半）。"""
    with pytest.raises(KeyError):
        put_settings({_TEST_INT: 11, "__test__.nope": 1})
    assert get_setting(_TEST_INT) == 7


def test_put_settings_rejects_secret_namespace():
    """密钥不能通过普通设置接口批量写入（必须走 /settings/secrets）。"""
    with pytest.raises(ValueError) as excinfo:
        put_settings({"secrets.deepseek.api_key": "sk-should-not-be-here"})
    assert "密钥" in str(excinfo.value)


def test_publish_notifies_prefix_subscribers():
    """按前缀订阅：写 llm.* 之类的键时，只通知前缀匹配的订阅者。"""
    received: list[SettingsChangeEvent] = []

    def on_change(event: SettingsChangeEvent) -> None:
        """收集变更事件，供断言使用。"""
        received.append(event)

    subscribe("__test__.", on_change)
    put_settings({_TEST_INT: 33})
    # 前缀 "__test__." 能匹配 "__test__.count"
    assert len(received) == 1
    assert received[0].key == _TEST_INT
    assert received[0].value == 33
    unsubscribe("__test__.", on_change)


def test_publish_skips_non_matching_prefix():
    """前缀不匹配的订阅者不应收到事件。"""
    received: list[SettingsChangeEvent] = []
    subscribe("other.", received.append)
    put_settings({_TEST_INT: 34})
    assert received == []


def test_wildcard_prefix_receives_all_events():
    """空前缀是通配：应收到全部设置变更。"""
    received: list[SettingsChangeEvent] = []
    subscribe("", received.append)
    put_settings({_TEST_INT: 35})
    assert len(received) == 1


def test_unsubscribe_stops_notifications():
    """取消订阅后不应再收到事件，且空前订阅列表会被清理掉。"""
    received: list[SettingsChangeEvent] = []
    subscribe("__test__.", received.append)
    unsubscribe("__test__.", received.append)
    put_settings({_TEST_INT: 36})
    assert received == []


def test_subscriber_exception_does_not_break_persistence():
    """某个订阅者抛异常时，设置仍应成功落库，其它订阅者仍应收到事件。"""
    good: list[SettingsChangeEvent] = []

    def bad(event: SettingsChangeEvent) -> None:
        """故意抛异常的订阅者，用来验证容错。"""
        raise RuntimeError("订阅者内部错误")

    subscribe("__test__.", bad)
    subscribe("__test__.", good.append)
    put_settings({_TEST_INT: 37})   # 不应抛异常
    assert get_setting(_TEST_INT) == 37
    assert len(good) == 1


def test_builtin_defs_are_wellformed():
    """内置声明本身必须全部通过自检（键格式、select 有候选、默认值合法）。"""
    reset_for_test()
    register_defs(BUILTIN_DEFS)
    definitions = list_defs()
    assert len(definitions) >= 15
    for definition in definitions:
        assert "." in definition.key
        assert definition.category
        assert definition.description, f"{definition.key} 缺少说明"
        if definition.kind is SettingKind.SELECT:
            assert definition.options
    # 抽查几个关键键确实存在
    keys = {d.key for d in definitions}
    for expected in ("llm.provider", "llm.model", "agent.max_iterations", "context.max_tool_output_chars"):
        assert expected in keys
    reset_for_test()
    register_defs(BUILTIN_DEFS)


def test_setting_def_rejects_malformed_declarations():
    """写错的声明应在注册时就报错，而不是等用户写入时才暴露。"""
    with pytest.raises(ValueError):
        SettingDef(key="no_dot", kind=SettingKind.BOOL, default=False)          # 键缺少命名空间
    with pytest.raises(ValueError):
        SettingDef(key="a.select", kind=SettingKind.SELECT, default="x")        # select 缺 options
    with pytest.raises(ValueError):
        SettingDef(key="a.range", kind=SettingKind.INT, default=5, min=10, max=1)  # min > max
    with pytest.raises(ValueError):
        SettingDef(key="a.bad_default", kind=SettingKind.INT, default=999, max=10)  # 默认值越界