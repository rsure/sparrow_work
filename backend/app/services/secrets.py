# app/services/secrets.py
"""密钥存储：API Key 等敏感值的唯一出入口（只进不出，永不明文落app_settings）。

为什么单独一个文件（对应 doc/21 ARCH-2 §2.1的决策）：
    - **普通设置**入app_settings 表 —— 便于统一读取、脱敏与备份；
    - **密钥**走系统钥匙串 —— 备份/同步 SQLite 时不会把 API Key 一起带走。

两级后端：
    1. 首选 `keyring`：Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service；
    2. 降级 `Fernet`：无图形环境（如 headless Linux、Docker）下keyring 没有可用后端时，
       用对称加密把密文存进 app_settings（key = "secret:<名称>"），
       Fernet 主密钥文件放在**用户数据目录**（不在仓库内），文件权限 0600。

安全红线：
    - 任何返回值、日志、错误信息里都不得出现完整密钥；
    - 写入 app_settings 的只能是 Fernet 密文，不能是明文；
    - 脱敏只保留前 3 后 4 位，形如 "sk-****ijkl"。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 等新语法
from __future__ import annotations

# 标准库：路径对象，存放 Fernet 主密钥文件
from pathlib import Path
# 标准库：os.chmod 收紧密钥文件权限（0600）；缺了它首次生成密钥时会直接 NameError
import os
# 标准库：JSON 序列化密文负载
import json

# 项目内：用户数据目录的唯一入口（日志、密钥、导出包共用同一套平台判断）
from app.core.paths import data_dir
# 项目内：落库用的会话工厂与设置实体（降级方案要把密文写进 app_settings）
from app.db.db_config import get_session
from app.entity.app_setting import AppSetting


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
# keyring 里使用的服务名：同一台机器上本应用的所有密钥都归在这个服务名下
_KEYRING_SERVICE = "app-backend"

# 降级方案在 app_settings 表里的键前缀（完整键形如 "secret:deepseek.api_key"）
_SECRET_KEY_PREFIX = "secret:"

# 脱敏时保留的头部字符数（如 "sk-" 这类固定前缀，便于用户确认是不是同一把key）
_MASK_PREFIX_LEN = 3
# 脱敏时保留的尾部字符数（用户据此确认末尾几位对不对）
_MASK_SUFFIX_LEN = 4
# 中间固定替换成的星号数量
_MASK_STAR_COUNT = 4
# 短于这个长度的密钥不做脱敏展示（截出来没有任何辨识度），直接显示 "****"
_MASK_MIN_LENGTH = 8

# keyring 不可用时的进程内标记：一旦探测失败就不再重复探测，
# 避免每次读写都去撞一次系统钥匙串（无后端时会抛异常，很慢）
_keyring_usable: bool | None = None


# --------------------------------------------------------------------------- #
# 密钥文件位置
# --------------------------------------------------------------------------- #
def secret_key_file() -> Path:
    """返回 Fernet 主密钥文件所在路径（**用户数据目录**，不是仓库目录）。

    平台判断已抽到 `app/core/paths.py`：日志与诊断导出也走同一处，
    避免"密钥放 APPDATA、日志放别处"这种漂移。

    :return: 主密钥文件的绝对路径；文件本身可能尚不存在（首次调用时才会生成）
    """
    return data_dir() / "secret.key"


def _load_or_create_fernet():
    """读取 Fernet 主密钥；文件不存在时生成一个新的并写入磁盘。

    :return: Fernet 实例，可用于加解密
    """
    # 第三方：cryptography 的 Fernet 对称加密实现（keyring 不可用时的降级方案）
    from cryptography.fernet import Fernet

    path = secret_key_file()
    if path.exists():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)
        _restrict_permissions(path)
    return Fernet(key)


def _restrict_permissions(path: Path) -> None:
    """把密钥文件权限收紧到「仅当前用户可读写」（0600）。

    Windows 上 os.chmod 的语义与 POSIX 不同（只能切换只读属性），
    因此这里对两种系统都做一次调用：能生效就生效，不能生效也不应让整个流程失败。

    :param path: 目标文件路径
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        # 某些文件系统（如 FAT32、容器挂载）不支持改权限：
        # 这不该让密钥功能整体不可用，跳过即可
        pass


# --------------------------------------------------------------------------- #
# keyring 后端探测
# --------------------------------------------------------------------------- #
def _try_keyring() -> bool:
    """探测系统钥匙串是否真的可用（导入成功**且**有可用后端）。

    keyring 在 Linux 上即便安装成功也可能因为没有 D-Bus Secret Service 而无法工作，
    所以不能只看「import 成功」，必须真正调一次 API 才知道。

    :return: True=钥匙串可用，后续读写走它；False=应降级到 Fernet
    """
    global _keyring_usable
    if _keyring_usable is not None:
        return _keyring_usable
    try:
        # 第三方：keyring 提供跨平台凭据存储（Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service）
        import keyring
        # 用「读一个不存在的键」来探测：不会产生任何写入，失败即说明没有可用后端
        keyring.get_password(_KEYRING_SERVICE, "__probe__")
    except Exception:
        # 导入失败 / 没有可用后端 / 无D-Bus 等，一律降级
        _keyring_usable = False
        return False
    _keyring_usable = True
    return True


# --------------------------------------------------------------------------- #
# 读写
# --------------------------------------------------------------------------- #
def get_secret(key: str) -> str | None:
    """读取一个密钥的明文。

    这是本模块少数几个返回明文的函数之一，调用方仅限「真正要拿key 去调模型接口」的场景
    （如 llm/factory.py），**禁止**把返回值写进日志或接口响应。

    :param key: 密钥名，如 "deepseek.api_key"、"custom-myapi.api_key"
    :return: 密钥明文；未设置时返回 None
    """
    if _try_keyring():
        try:
            import keyring
            return keyring.get_password(_KEYRING_SERVICE, key)
        except Exception:
            # 钥匙串中途出问题（例如被用户注销），退回 Fernet 读，避免功能直接瘫掉
            pass
    return _fernet_get(key)


def set_secret(key: str, value: str) -> None:
    """保存一个密钥（覆盖式写入）。

    :param key: 密钥名，如 "deepseek.api_key"
    :param value: 密钥明文
    :raises ValueError: 密钥名为空或明文为空
    """
    if not key or not key.strip():
        raise ValueError("密钥名不能为空")
    if not value:
        raise ValueError("密钥值不能为空（如需清空请用删除接口）")

    if _try_keyring():
        try:
            import keyring
            keyring.set_password(_KEYRING_SERVICE, key, value)
            return
        except Exception:
            pass
    _fernet_set(key, value)


def delete_secret(key: str) -> bool:
    """删除一个密钥。

    :param key: 密钥名
    :return: True=确实删掉了一个已存在的密钥；False=本来就没有设置过
    """
    deleted = False
    if _try_keyring():
        try:
            import keyring
            import keyring.errors

            keyring.delete_password(_KEYRING_SERVICE, key)
            deleted = True
        except keyring.errors.PasswordDeleteError:
            # 本来就没设置过，不算错误
            deleted = False
        except Exception:
            deleted = False
    # 降级存储里也清一遍：可能之前在无钥匙串环境下存进去过
    if _fernet_delete(key):
        deleted = True
    return deleted


def has_secret(key: str) -> bool:
    """判断某个密钥是否已设置（不读取明文，用于前端显示「已设置 / 未设置」）。

    :param key: 密钥名
    :return: True=已设置且非空
    """
    return bool(get_secret(key))


def masked_secret(key: str) -> str | None:
    """返回某个密钥的**脱敏**展示值（形如 "sk-****ijkl"），供设置页回显。

    :param key: 密钥名
    :return: 脱敏后的字符串；未设置时返回 None（前端据此显示「未设置」）
    """
    value = get_secret(key)
    if not value:
        return None
    return mask_secret(value)


# --------------------------------------------------------------------------- #
# Fernet 降级存储
# --------------------------------------------------------------------------- #
def _fernet_row_key(key: str) -> str:
    """把密钥名映射成 app_settings 表里的行键（加 "secret:" 前缀与普通设置隔离）。

    :param key: 密钥名
    :return: 表中的主键，形如 "secret:deepseek.api_key"
    """
    return f"{_SECRET_KEY_PREFIX}{key}"


def _fernet_get(key: str) -> str | None:
    """从 app_settings 读 Fernet 密文并解密。

    :param key: 密钥名
    :return: 密钥明文；未设置或解密失败时返回 None
    """
    with get_session() as s:
        row = s.get(AppSetting, _fernet_row_key(key))
        raw = row.value if row is not None else None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return _load_or_create_fernet().decrypt(payload["cipher"].encode()).decode("utf-8")
    except Exception:
        # 密文损坏 / 主密钥文件被换掉 / 历史遗留的其它格式：
        # 一律当作「读不到」，绝不把异常抛给调用方（设置页应显示未设置，而不是整页报错）
        return None


def _fernet_set(key: str, value: str) -> None:
    """把密钥加密后写入 app_settings（存的是密文，不是明文）。

    :param key: 密钥名
    :param value: 密钥明文
    """
    cipher = _load_or_create_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    row_key = _fernet_row_key(key)
    payload = json.dumps({"cipher": cipher}, ensure_ascii=False)
    with get_session() as s:
        row = s.get(AppSetting, row_key)
        if row is None:
            s.add(AppSetting(key=row_key, value=payload))
        else:
            row.value = payload


def _fernet_delete(key: str) -> bool:
    """删除 app_settings 里对应的密文行。

    :param key: 密钥名
    :return: True=确实删掉了一行；False=本来就没有
    """
    with get_session() as s:
        row = s.get(AppSetting, _fernet_row_key(key))
        if row is None:
            return False
        s.delete(row)
    return True


# --------------------------------------------------------------------------- #
# 脱敏
# --------------------------------------------------------------------------- #
def mask_secret(value: str | None) -> str | None:
    """把密钥脱敏成「前 3 + 星号 + 后 4」的形式，用于前端回显与日志。

    :param value: 密钥明文
    :return: 脱敏字符串；入参为空时返回 None；长度不足 8 位时只返回 "****"
    """
    if not value:
        return None
    if len(value) < _MASK_MIN_LENGTH:
        # 太短的话前 3 后 4 会把整个密钥暴露出来，没有脱敏意义
        return "****"
    head = value[:_MASK_PREFIX_LEN]
    tail = value[-_MASK_SUFFIX_LEN:]
    return f"{head}{'*' * _MASK_STAR_COUNT}{tail}"