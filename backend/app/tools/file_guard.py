# app/tools/file_guard.py
"""写前校验：防止"读了旧内容、整份回写覆盖掉别人的修改"（TASK §5.3 L2）。

要解决的问题（多子任务场景最容易踩）：
    A 子任务读了 `x.py`；B 子任务改了 `x.py`；A 再按自己记忆里的旧内容整份 write_file，
    B 的改动就静默消失了。串行执行并不能避免这个——它只是把并发问题变成了"顺序覆盖"。

做法（乐观锁）：
    - `read_file` 成功后登记 `(会话, 路径) → 内容 hash`；
    - `write_file` / `edit_file` 写入前比对磁盘当前 hash：
        * 没有登记过 → **放行**（不强制"必须先读"，见下）；
        * 与登记一致 → 放行；
        * 不一致 → 拒绝，并提示重新读取；
    - 写入成功后把登记更新成新内容的 hash。

为什么**不**强制"未读先写一律拒绝"（与 doc/26 原文的差异）：
    模型经常在几轮前读过文件、中间做过别的操作，强制要求"每次写前必须重读"会产生大量
    无意义的往返，而且无法区分"没读过"和"读过但登记被淘汰了"。这里只拦真正危险的情况
    ——**读之后磁盘内容变了**——收益最高、误伤最小。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：hashlib 算内容指纹；threading 保证并发写登记表安全
import hashlib
import threading
from pathlib import Path

# 登记表最多保留多少条（单会话大型重构最多也就几十个文件，留足余量后淘汰最旧的）
_MAX_ENTRIES = 500

# (session_id, 规范化的绝对路径) → 内容 sha256
_snapshots: dict[tuple[str, str], str] = {}
# 插入顺序（用于超限时淘汰最旧的）
_order: list[tuple[str, str]] = []
_lock = threading.Lock()


def _enabled() -> bool:
    """是否开启写前校验（设置键 `task.write_stale_guard`，读不到按关闭处理）。

    :return: True=开启
    """
    try:
        # 项目内：延迟导入，避免工具层导入期依赖设置库
        from app.services.settings_registry import get_setting

        return bool(get_setting("task.write_stale_guard"))
    except Exception:
        return False


def _key(session_id: str, path: Path) -> tuple[str, str]:
    """生成登记表的键（路径统一成绝对路径字符串）。

    :param session_id: 会话 id
    :param path: 文件路径
    :return: (session_id, 绝对路径)
    """
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return session_id, resolved


def content_hash(path: Path) -> str | None:
    """算文件的 sha256；读不到（不存在/无权限）时返回 None。

    :param path: 文件路径
    :return: 十六进制摘要或 None
    """
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            # 分块读：大文件也不至于把内存打满
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _remember(key: tuple[str, str], value: str) -> None:
    """写入登记表并维护淘汰顺序（调用方需持锁）。

    :param key: 登记键
    :param value: 内容 hash
    """
    _snapshots[key] = value
    if key in _order:
        _order.remove(key)
    _order.append(key)
    while len(_order) > _MAX_ENTRIES:
        oldest = _order.pop(0)
        _snapshots.pop(oldest, None)


def record_read(session_id: str, path: Path) -> None:
    """登记"这个会话读过这个文件（当时的内容指纹）"。

    失败静默：登记不上最多是少一层保护，不能让读文件失败。

    :param session_id: 会话 id
    :param path: 文件路径
    """
    if not session_id:
        return
    value = content_hash(path)
    if value is None:
        return
    with _lock:
        _remember(_key(session_id, path), value)


def check_write(session_id: str, path: Path) -> str | None:
    """写入前校验：磁盘内容是否在本会话读取之后被改过。

    :param session_id: 会话 id
    :param path: 目标文件
    :return: None=可以写；字符串=拒绝原因（直接作为 FAIL 文案）
    """
    if not session_id or not _enabled():
        return None
    if not path.exists():
        # 新建文件不存在"覆盖别人改动"的问题
        return None

    key = _key(session_id, path)
    with _lock:
        known = _snapshots.get(key)
    if known is None:
        # 没读过：不做"未读先写"的强制（见模块说明），放行
        return None

    current = content_hash(path)
    if current is None:
        return None
    if current == known:
        return None
    return (
        f"文件在读取之后已被修改：{path}。为避免覆盖别人的改动，本次写入已拒绝。"
        "请先用 read_file 重新读取最新内容，再决定怎么写。"
    )


def record_write(session_id: str, path: Path) -> None:
    """写入成功后更新登记（这样紧接着的第二次写入不会被自己误判为"被改过"）。

    :param session_id: 会话 id
    :param path: 目标文件
    """
    if not session_id:
        return
    value = content_hash(path)
    if value is None:
        return
    with _lock:
        _remember(_key(session_id, path), value)


def reset_for_test() -> None:
    """清空登记表（用例隔离用）。"""
    with _lock:
        _snapshots.clear()
        _order.clear()
