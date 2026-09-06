"""OPS-6 事件契约 + M2 界面设置声明的回归测试。

为什么这两件事要写测试：
    1. **事件契约**是"一改就炸历史回放"的地方：字段一旦被删，前端读不到却不会报错，
       表现是"统计面板突然全空"。测试把字段名钉住，删字段必须显式改测试。
    2. **界面设置**（theme.* / input.*）是 meta 驱动的，前端不做任何硬编码；
       一旦忘记在 create_app() 里注册，设置页会静默少一整块（不报错），只能靠测试发现。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试客户端：进程内调用 FastAPI 应用
from fastapi.testclient import TestClient

# 被测应用：已装配全部路由与设置声明
from app.main import app

# 全局复用的测试客户端
client = TestClient(app)


def test_chat_event_contract_is_frozen() -> None:
    """`GET /api/chat/events` 必须包含 OPS-6 冻结的全部字段。"""
    resp = client.get("/api/chat/events")
    assert resp.status_code == 200
    spec = resp.json()

    # EXT-5：工具输出治理字段
    tool_end = " ".join(spec["tool_end"]["fields"])
    for field in ("total_chars", "truncated", "continuation_ref"):
        assert field in tool_end, f"tool_end 缺少契约字段 {field}"

    # OPS-6：done 的统计字段
    done = " ".join(spec["done"]["fields"])
    for field in ("usage", "subtasks", "steer_count", "model", "files"):
        assert field in done, f"done 缺少契约字段 {field}"

    # ARCH-6 / UX-9：对应事件必须出现在协议说明里，且带前端 resume 需要的字段
    assert "steer_accepted" in spec
    assert "steer_injected" in spec
    assert "budget_exceeded" in spec
    budget_fields = " ".join(spec["budget_exceeded"]["fields"])
    assert "interrupt_id" in budget_fields, "预算弹窗要靠 interrupt_id 恢复执行"
    confirm_fields = " ".join(spec["confirm_required"]["fields"])
    assert "can_remember" in confirm_fields, "workspace 模式要靠 can_remember 决定是否显示勾选框"


def test_theme_and_input_settings_registered() -> None:
    """主题与输入设置必须已注册，且 meta 里带正确的类型与候选值。"""
    resp = client.get("/api/settings/meta")
    assert resp.status_code == 200
    body = resp.json()
    # 统一外壳：{ code, message, data }
    definitions = {item["key"]: item for item in body["data"]}

    assert definitions["theme.mode"]["type"] == "select"
    assert set(definitions["theme.mode"]["options"]) == {"dark", "light", "system"}
    assert definitions["theme.mode"]["category"] == "theme"

    # 预设候选必须覆盖前端 themes/presets.ts 里的全部 id
    assert set(definitions["theme.preset"]["options"]) >= {"slate", "midnight", "paper", "nord"}

    # 高级覆盖项是 JSON，默认必须是对象（前端按对象合并 token）
    assert definitions["theme.custom"]["type"] == "json"
    assert definitions["theme.custom"]["default"] == {}

    # UX-6：Enter 行为开关
    assert definitions["input.enter_to_send"]["type"] == "bool"
    assert definitions["input.enter_to_send"]["default"] is True

    # UX-7 / UX-9：权限三档与预算熔断的键必须已注册（否则设置页会静默少一整块）
    assert set(definitions["permission.mode"]["options"]) == {"ask", "workspace", "allow"}
    assert definitions["permission.mode"]["default"] == "ask"
    for key in ("cost.guard_enabled", "cost.max_tokens_per_task", "cost.max_cost_per_task", "cost.max_duration_minutes"):
        assert key in definitions, f"缺少设置键 {key}"


def test_theme_setting_write_and_readback() -> None:
    """主题设置写入后能读回（走统一设置接口，不需要专用端点）。"""
    # 先记下原值，用例结束恢复，避免污染开发者本地设置
    values = client.get("/api/settings").json()["data"]["values"]
    original = values["theme.preset"]
    try:
        put = client.put("/api/settings", json={"values": {"theme.preset": "nord"}})
        assert put.status_code == 200
        assert client.get("/api/settings").json()["data"]["values"]["theme.preset"] == "nord"
    finally:
        client.put("/api/settings", json={"values": {"theme.preset": original}})


def test_all_settings_have_chinese_labels() -> None:
    """每个设置项都必须有中文名与（select 的）中文候选值。

    为什么值得钉住：设置页是 meta 驱动的，后端漏一个 label，用户界面上就会出现
    `theme.mode` 这种内部名——不报错、不显眼，只能靠人肉发现。这条用例把"漏了"变成红灯。
    """
    meta = client.get("/api/settings/meta").json()["data"]

    missing_label = [item["key"] for item in meta if not item.get("label")]
    assert missing_label == [], f"这些设置项缺少中文名：{missing_label}"

    bad_labels = [
        item["key"]
        for item in meta
        if item["type"] == "select"
        and (not item.get("option_labels") or len(item["option_labels"]) != len(item.get("options") or []))
    ]
    assert bad_labels == [], f"这些 select 设置项的候选值中文标签缺失或数量不一致：{bad_labels}"


def test_option_labels_must_align_with_options() -> None:
    """声明期自检：候选值标签数量与候选值不一致时必须直接抛错（错误越早暴露越好）。"""
    import pytest

    from app.services.settings_registry import SettingDef, SettingKind

    with pytest.raises(ValueError):
        SettingDef(
            key="test.bad_labels", kind=SettingKind.SELECT, default="a",
            options=("a", "b"), option_labels=("只有一个",),
        )
