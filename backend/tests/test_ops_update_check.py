"""OPS-4 自动更新的设置项自测：`ops.auto_update_check` 必须声明正确、能导出又能导入。

为什么单独一个文件：
    自动更新本身在 Electron 主进程里（本仓库没有主进程单测基建），
    但"桌面壳启动时读哪个键"这件事是跨进程契约 —— 键名、类型、默认值、
    以及它能否随配置导入导出搬走，都是后端可以独立验证的部分。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：fixture
import pytest
# 测试客户端：进程内调用 FastAPI 应用
from fastapi.testclient import TestClient

# 被测对象：项目根应用实例（导入即完成各模块的设置声明注册）
from app.main import app
# 项目内：运维设置声明注册入口 —— 本文件可能排在 test_settings_registry 之后，
# 那个用例会 reset_for_test() 清空全局注册表，所以每个用例前重新注册一次
from app.services.ops_settings_defs import register_ops_defs
# 项目内：设置注册表（读声明）与落库层（用完删掉测试值）
from app.services import setting_service, settings_registry

# 复用同一个测试客户端
client = TestClient(app)

# 被测键名：桌面壳 updater.ts 里硬编码的同一个字符串，两侧必须一致
KEY = "ops.auto_update_check"


@pytest.fixture(autouse=True)
def _register_and_clean():
    """用例前确保声明存在，前后都把这个键从库里删掉（保持"未落库"状态）。"""
    register_ops_defs()
    setting_service.delete_setting_value(KEY)
    yield
    setting_service.delete_setting_value(KEY)


def test_auto_update_check_is_a_bool_in_diagnostic_category() -> None:
    """声明的类型/默认值/分区必须与桌面壳的假设一致（缺一个都会读错值）。"""
    definition = settings_registry.get_def(KEY)
    assert definition.kind is settings_registry.SettingKind.BOOL
    # 默认开着：用户没动过设置时，安装版启动就会自动检查更新
    assert definition.default is True
    # 放在「诊断与维护」分区里，和日志级别、轨迹开关待在一起
    assert definition.category == "diagnostic"
    # 前端要显示中文标签，空标签会让设置页出现一个没有标题的开关
    assert definition.label


def test_auto_update_check_roundtrips_through_export_and_import() -> None:
    """把开关关掉 → 导出里能看到 false → 导入一份"开着"的配置能把它改回 true。"""
    # 先落库为"关"
    resp = client.put("/api/settings", json={"values": {KEY: False}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["values"][KEY] is False

    # 导出：非密钥项要原样带上，否则换机器后用户还得手动关一次
    exported = client.get("/api/settings/export").json()["data"]
    assert exported["values"][KEY] is False

    # 导入：写回 true，返回值里应该有这个键
    payload = {"format": exported["format"], "values": {KEY: True}, "redacted_keys": []}
    imported = client.post("/api/settings/import", json=payload)
    assert imported.status_code == 200, imported.text
    data = imported.json()["data"]
    assert data["skipped"] == []
    assert data["values"][KEY] is True
