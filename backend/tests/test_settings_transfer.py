"""OPS-5 配置导入导出的自测：导出必须脱敏、导入必须按白名单写入。

这些用例走"真服务 + 真 HTTP 端点"，与 tests/conftest.py 的约定一致：
会落真实 app.db，所以每个用例在 finally 里把自己改过的键删掉，避免污染开发者本地配置。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：fixture 与 pytest.raises
import pytest
# 测试客户端：进程内调用 FastAPI 应用
from fastapi.testclient import TestClient

# 被测对象：项目根应用实例
from app.main import app
# 被测对象：设置注册表（读当前值、写测试值）
from app.services import settings_registry
# 项目内：设置落库层，测试结束用它删掉自己写的键
from app.services import setting_service
# 被测对象：配置导入导出的服务层（部分用例直接调它，绕开 HTTP 层看返回值）
from app.services import settings_transfer
# 项目内：各模块的设置声明注册入口。本文件依赖"完整注册表"（要用 theme.* / mcp.servers 等键），
# 而 tests/test_settings_registry.py 会调用 reset_for_test() 清空全局注册表，
# 按文件名排序它正好排在本文件前面 —— 所以每个用例前必须自己把声明重新注册一遍
from app.services.mcp_settings_defs import register_mcp_defs
from app.services.memory_settings_defs import register_memory_defs
from app.services.office_settings_defs import register_office_defs
from app.services.ops_settings_defs import register_ops_defs
from app.services.policy_settings_defs import register_policy_defs
from app.services.settings_registry import BUILTIN_DEFS, register_defs
from app.services.skill_settings_defs import register_skill_defs
from app.services.task_settings_defs import register_task_defs
from app.services.ui_settings_defs import register_ui_defs
from app.services.workspace_settings_defs import register_workspace_defs

# 复用同一个测试客户端
client = TestClient(app)

# 本文件会改动的设置键：用例结束后统一删掉，回到"未落库"状态
_TOUCHED_KEYS = ["theme.preset", "theme.mode", "llm.model", "mcp.servers"]


def _register_all_defs() -> None:
    """把应用启动时注册的全部设置声明重新装进注册表（顺序与 app/main.py 一致）。"""
    register_defs(BUILTIN_DEFS)
    register_workspace_defs()
    register_ui_defs()
    register_policy_defs()
    register_skill_defs()
    register_mcp_defs()
    register_ops_defs()
    register_task_defs()
    register_memory_defs()
    register_office_defs()


@pytest.fixture(autouse=True)
def _clean_settings():
    """用例前后都把自己可能写过的设置键删掉，并保证声明都在注册表里。"""
    # 先补声明再清值：若注册表被别的用例清空过，删除/写入都会因为"未声明的设置键"失败
    _register_all_defs()

    def _purge() -> None:
        for key in _TOUCHED_KEYS:
            setting_service.delete_setting_value(key)

    _purge()
    yield
    _purge()


def _export() -> dict:
    """调 GET /api/settings/export 并返回 data 部分。

    :return: 导出字典
    """
    resp = client.get("/api/settings/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    return body["data"]


def test_export_never_contains_secret_namespace() -> None:
    """导出文件里不能出现任何 secrets.* 键，密钥只以「设置过没有」的形式出现。"""
    data = _export()
    assert data["format"] == settings_transfer.EXPORT_FORMAT
    assert data["values"]
    assert not [key for key in data["values"] if key.startswith("secrets.")]
    # 密钥清单只能有 key / set 两个字段：多出 masked 就说明脱敏链路写错了
    for item in data["secrets"]:
        assert set(item) == {"key", "set"}
        assert isinstance(item["set"], bool)


def test_export_redacts_mcp_env_values() -> None:
    """mcp.servers 里 env 的取值属于密钥，导出时必须整键抹掉并记进 redacted_keys。"""
    settings_registry.put_settings({
        "mcp.servers": [
            {"name": "demo", "command": "npx", "env": {"DEMO_TOKEN": "sk-abcdefghijklmnop"}},
        ],
    })

    data = _export()
    # 整份值都不导出，只留占位符（留一半结构反而会让用户以为"没脱敏"）
    assert data["values"]["mcp.servers"] == "***REDACTED***"
    assert "mcp.servers" in data["redacted_keys"]
    # 序列化后再查一遍：导出的 JSON 文本里绝不能出现明文密钥
    assert "sk-abcdefghijklmnop" not in str(data)


def test_import_applies_known_keys_and_reports_the_rest() -> None:
    """合法键写进本机，未声明 / 密钥命名空间 / 已脱敏 / 值非法 的键全部进 skipped。"""
    payload = {
        "format": settings_transfer.EXPORT_FORMAT,
        "values": {
            "theme.preset": "nord",
            "not.a.real.key": 1,
            "secrets.deepseek.api_key": "sk-should-not-be-used",
            "mcp.servers": "***REDACTED***",
            "theme.font_size": "not-a-number",
        },
        "redacted_keys": ["mcp.servers"],
    }

    resp = client.post("/api/settings/import", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["applied"] == ["theme.preset"]
    reasons = {item["key"]: item["reason"] for item in data["skipped"]}
    assert reasons["not.a.real.key"] == "本机未声明的设置键"
    assert "密钥" in reasons["secrets.deepseek.api_key"]
    assert "脱敏" in reasons["mcp.servers"]
    assert reasons["theme.font_size"].startswith("值不合法")
    # 写入后返回的是全量值，前端可以直接拿来刷新设置页
    assert data["values"]["theme.preset"] == "nord"


def test_import_roundtrip_restores_exported_values() -> None:
    """导出 → 改掉 → 导入回来，配置应当恢复成导出时的样子（OPS-5 验收项）。"""
    settings_registry.put_settings({"theme.preset": "nord", "llm.model": "deepseek-reasoner"})
    snapshot = _export()

    # 模拟"换了台机器"：先把这两项改掉
    settings_registry.put_settings({"theme.preset": "paper", "llm.model": "deepseek-chat"})
    assert settings_registry.get_setting("theme.preset") == "paper"

    resp = client.post("/api/settings/import", json={
        "format": snapshot["format"],
        "values": snapshot["values"],
        "redacted_keys": snapshot["redacted_keys"],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["skipped"] == []

    assert settings_registry.get_setting("theme.preset") == "nord"
    assert settings_registry.get_setting("llm.model") == "deepseek-reasoner"


def test_import_rejects_foreign_format() -> None:
    """不是本应用导出的配置文件要明确拒绝，而不是"什么都不做"地返回成功。"""
    resp = client.post("/api/settings/import", json={
        "format": "someone-elses/9",
        "values": {"theme.preset": "nord"},
    })
    assert resp.status_code == 400
    assert "不认识的配置格式" in resp.json()["detail"]


def test_import_rejects_missing_values() -> None:
    """缺少 values 时直接报错：静默成功会让用户以为配置导进去了。

    values 是必填字段，所以由 Pydantic 在校验层拦下（422）；这里只断言"不会被当成成功"。
    """
    resp = client.post("/api/settings/import", json={"format": settings_transfer.EXPORT_FORMAT})
    assert resp.status_code == 422
