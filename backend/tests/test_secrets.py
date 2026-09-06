"""密钥存储（services/secrets.py）的单元测试。

重点覆盖两件事：
    1. 脱敏格式正确（红线：任何出口都不能出现完整密钥）；
    2. **明文密钥绝不出现在 app.db 里**（红线：备份/同步数据库不应泄露密钥）。

为保证两条存储路径都被测到，用例会直接调用带下划线的 Fernet 内部函数
（`_fernet_*`），不依赖操作系统有没有可用钥匙串——这样在无图形环境的
CI 上也能跑通降级路径。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：直接查 SQLite，验证表里没有明文（不经过 SQLAlchemy，断言更直白）
import sqlite3
# 标准库：临时目录，给密钥文件用
from pathlib import Path

# 测试框架：pytest 的夹具与异常断言
import pytest

# 项目内：密钥读写与脱敏
from app.services import secrets as secrets_service


# 测试用密钥名（带 __test__ 前缀，避免与用户真实配置的密钥混在一起）
_TEST_KEY = "__test__.probe.api_key"
# 一段可被grep 出来的假密钥：用于验证「明文不入库」
_FAKE_SECRET = "sk-TESTPLAINTEXT-0123456789abcdef"

# 后端数据库文件的相对路径（与 app/db/db_config.py 的 DATABASE_URL 一致）
_DB_PATH = "app.db"


@pytest.fixture(autouse=True)
def _clean_test_secret():
    """用例前后都把测试密钥删掉，避免残留在系统钥匙串或用户数据库里。"""
    secrets_service.delete_secret(_TEST_KEY)
    yield
    secrets_service.delete_secret(_TEST_KEY)


def _db_contains_plaintext(needle: str) -> bool:
    """在 app.db 全文里搜索一段明文，返回是否命中。

    直接读原始字节搜，而不是解析 JSON：这样即便密钥被塞进某个 JSON 字段里也能查出来，
    断言才够硬。

    :param needle: 要搜索的明文片段
    :return: 数据库文件中出现该明文时返回 True
    """
    path = Path(_DB_PATH)
    if not path.exists():
        return False
    return needle.encode("utf-8") in path.read_bytes()


def test_mask_secret_keeps_prefix_and_suffix():
    """脱敏应保留前 3 后 4 位，中间固定 4 个星号。"""
    assert secrets_service.mask_secret("sk-abcdefghijkl") == "sk-****ijkl"
    assert secrets_service.mask_secret("abcdefghijklmnop") == "abc****mnop"


def test_mask_secret_short_value_is_fully_hidden():
    """太短的密钥（不足 8 位）截出来没有辨识度，应整体隐藏。"""
    assert secrets_service.mask_secret("abc") == "****"
    assert secrets_service.mask_secret("")is None
    assert secrets_service.mask_secret(None) is None


def test_mask_secret_never_returns_full_value():
    """脱敏结果绝不能等于原值（长度足够时前后会重叠，需显式断言）。"""
    value = "sk-abcdefghijkl"
    assert secrets_service.mask_secret(value) != value


def test_fernet_roundtrip():
    """降级路径的读写往返：存进去能原样取回。"""
    secrets_service._fernet_set(_TEST_KEY, _FAKE_SECRET)
    assert secrets_service._fernet_get(_TEST_KEY) == _FAKE_SECRET


def test_fernet_stores_ciphertext_not_plaintext():
    """红线：Fernet 降级方案下，app.db 里存的必须是密文而非明文。"""
    secrets_service._fernet_set(_TEST_KEY, _FAKE_SECRET)
    assert not _db_contains_plaintext(_FAKE_SECRET), "明文密钥被写进了 app.db"
    # 反过来确认确实写了东西（排除「因为没写所以搜不到」的假通过）
    assert secrets_service._fernet_get(_TEST_KEY) == _FAKE_SECRET


def test_fernet_delete_removes_row():
    """删除后应读不到，且确实清掉了表里的那一行。"""
    secrets_service._fernet_set(_TEST_KEY, _FAKE_SECRET)
    assert secrets_service._fernet_delete(_TEST_KEY) is True
    assert secrets_service._fernet_get(_TEST_KEY) is None
    # 再删一次应返回 False（本来就没有）
    assert secrets_service._fernet_delete(_TEST_KEY) is False


def test_fernet_get_missing_key_returns_none():
    """读取一个从未设置过的密钥应返回 None，而不是抛异常。"""
    assert secrets_service._fernet_get("__test__.never.set") is None


def test_public_api_roundtrip_and_status():
    """公开接口的读写往返 + 已设置/未设置状态查询。"""
    assert secrets_service.has_secret(_TEST_KEY) is False
    secrets_service.set_secret(_TEST_KEY, _FAKE_SECRET)
    assert secrets_service.has_secret(_TEST_KEY) is True
    assert secrets_service.get_secret(_TEST_KEY) == _FAKE_SECRET
    #脱敏出口不应包含完整密钥
    masked = secrets_service.masked_secret(_TEST_KEY)
    assert masked is not None and masked.endswith("cdef") and _FAKE_SECRET not in masked


def test_public_api_never_writes_plaintext_to_db():
    """红线：无论走钥匙串还是 Fernet，app.db 里都不应出现明文密钥。"""
    secrets_service.set_secret(_TEST_KEY, _FAKE_SECRET)
    assert not _db_contains_plaintext(_FAKE_SECRET), "明文密钥被写进了 app.db"


def test_set_secret_rejects_empty_values():
    """密钥名为空或值为空应报错，避免写入无意义的空记录。"""
    with pytest.raises(ValueError):
        secrets_service.set_secret("", _FAKE_SECRET)
    with pytest.raises(ValueError):
        secrets_service.set_secret(_TEST_KEY, "")


def test_delete_secret_is_idempotent():
    """删除一个不存在的密钥不应抛异常（前端可能重复点击删除）。"""
    assert secrets_service.delete_secret("__test__.never.set") is False


def test_fernet_key_file_lives_outside_repo(tmp_path, monkeypatch):
    """密钥文件必须落在用户数据目录，不能落在仓库里（否则会被提交进 git）。"""
    #把配置目录指向临时目录，避免真的去动用户的 %APPDATA%
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = secrets_service.secret_key_file()
    assert str(path).startswith(str(tmp_path))
    assert ".git" not in str(path)


def test_db_has_secret_row_prefixed():
    """Fernet 存储的行键必须带 secret: 前缀，与普通设置键隔离。"""
    assert secrets_service._fernet_row_key("deepseek.api_key") == "secret:deepseek.api_key"
    # 确认表里确实按这个前缀存（便于运维排查时一眼认出哪些是密文）
    secrets_service._fernet_set(_TEST_KEY, _FAKE_SECRET)
    con = sqlite3.connect(_DB_PATH)
    try:
        rows = con.execute("SELECT key FROM app_settings WHERE key LIKE 'secret:%'").fetchall()
    finally:
        con.close()
    assert any(row[0].startswith("secret:") for row in rows)