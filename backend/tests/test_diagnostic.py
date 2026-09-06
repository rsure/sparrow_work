# tests/test_diagnostic.py
"""OPS-3 诊断导出的测试。

这个模块最要紧的断言只有一条：**包里不能出现密钥**。
其余（结构、可解压、字段齐全）都是次要的，但也都写上了——
诊断包在用户手里打不开，比"多打了几行日志"更让人困惑。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：解析 zip
import io
import json
import zipfile

# 测试框架
import pytest
# 测试客户端：进程内调用应用
from fastapi.testclient import TestClient

# 项目内：被测服务
from app.main import app
from app.services import diagnostic_service, settings_registry

client = TestClient(app)

# 一个用于验证"必须被脱敏"的假密钥
_FAKE_KEY = "sk-thisIsAFakeKey1234567890"


def test_redact_by_key_name() -> None:
    """键名含 api_key / token / secret 的值必须被抹掉。"""
    value = {
        "api_key": _FAKE_KEY,
        "llm": {"base_url": "https://example.com", "token": "abc"},
        "nested": [{"secret": "x"}],
    }
    result = diagnostic_service.redact(value, "")

    assert result["api_key"] == diagnostic_service._REDACTED
    assert result["llm"]["token"] == diagnostic_service._REDACTED
    # 非密钥字段要保留（否则诊断包就没用了）
    assert result["llm"]["base_url"] == "https://example.com"
    assert result["nested"][0]["secret"] == diagnostic_service._REDACTED


def test_redact_container_keys() -> None:
    """env / headers 下的值一律脱敏：里面的键名是用户自定义的，靠名字判断不可靠。"""
    value = {"headers": {"X-Whatever": "a-secret-value"}, "env": {"FOO": "bar"}}
    result = diagnostic_service.redact(value, "")

    assert result["headers"] == {"X-Whatever": diagnostic_service._REDACTED}
    assert result["env"] == {"FOO": diagnostic_service._REDACTED}


def test_scrub_catches_key_shapes() -> None:
    """即使键名判断漏了，文本里形如 sk-xxx 的长串也要被擦掉（第二道防线）。"""
    text = f'{{"k": "{_FAKE_KEY}"}}'
    assert _FAKE_KEY not in diagnostic_service._scrub(text)


def test_package_structure_and_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """诊断包应包含 meta/settings/schema/日志/轨迹，且不含任何密钥。"""
    # 造一份"带密钥"的设置：自定义 provider 的 api_key + MCP 的 headers
    original = settings_registry.get_setting("llm.custom_providers")
    settings_registry.put_settings({
        "llm.custom_providers": [
            {"name": "x", "api_key": _FAKE_KEY, "base_url": "https://example.com"},
        ],
    })
    try:
        filename, payload = diagnostic_service.build_package()
    finally:
        settings_registry.put_settings({"llm.custom_providers": original})

    assert filename.startswith("diagnostic-") and filename.endswith(".zip")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert {"meta.json", "settings.json", "schema.json", "README.txt"} <= names
        assert "trace/recent.jsonl" in names
        assert "logs/app.log" in names

        settings_text = archive.read("settings.json").decode("utf-8")
        meta_text = archive.read("meta.json").decode("utf-8")

    # 核心断言：假密钥不能出现在包里
    assert _FAKE_KEY not in settings_text
    assert _FAKE_KEY not in meta_text
    # 但"这个 provider 存在"要能看到，否则诊断包就没意义了
    assert "https://example.com" in settings_text
    # meta 里要有版本与迁移版本（排查"是不是没迁移"靠它）
    meta = json.loads(meta_text)
    assert "app_version" in meta and "db_revision" in meta


def test_summary_endpoint() -> None:
    """概要接口应返回版本、库版本与日志规模。"""
    resp = client.get("/api/diagnostic/summary")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("version", "python", "platform", "db_revision", "log_file", "log_bytes", "tables"):
        assert key in data


def test_export_endpoint_returns_zip() -> None:
    """导出接口必须真的返回一个能打开的 zip（不是半截流）。"""
    resp = client.get("/api/diagnostic/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        assert "meta.json" in archive.namelist()


def test_log_file_is_written() -> None:
    """日志必须真的落盘：打包后没有控制台，日志文件是唯一现场。"""
    # 触发一条日志
    import logging

    logging.getLogger("diagnostic-test").warning("这是一条测试日志")

    from app.core.paths import log_file

    path = log_file()
    assert path.exists()
    assert "diagnostic-test" in path.read_text(encoding="utf-8", errors="replace")
