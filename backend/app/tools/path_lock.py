# app/tools/path_lock.py
"""按文件路径加互斥锁（TASK Phase 2 §5.3 L3 的最后一道保险）。

为什么需要它：并行车道（lane）在计划期已经保证"两条道不写同一个文件"，
但计划是模型给的，`files` 声明可能漏、也可能有工具绕过声明去写别的文件。
再加一把按路径的锁，即使真撞上了，也只会串行发生，不会出现两个线程同时
"读原文件 → 拼接 → 整份写回"而互相覆盖。

为什么不用 `asyncio.Lock`：
    工具是**同步函数**，LangGraph 会把它们丢到线程池里执行（`on_tool_start` 与
    `on_tool_end` 之间其实换了线程）。在那种线程里拿不到事件循环，`asyncio.Lock`
    根本锁不住东西。所以这里用 `threading.RLock`，它对线程池天然有效。

为什么用 `RLock` 而不是 `Lock`：同一个工具函数内部可能对同一路径两次取锁
（例如先备份再写入的辅助函数也包了一层），用可重入锁才不会自己把自己锁死。

锁表用引用计数：路径数量在工作区里可以到十万级，只加不删会一直涨；
最后一个使用者退出时就把这一项删掉。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：路径规范化（同一文件的不同写法要落到同一把锁上）
import os
# 标准库：线程锁（工具在 LangGraph 的线程池里执行，必须用线程级原语）
import threading
# 标准库：上下文管理器（`with path_lock(p):` 的写法）
from contextlib import contextmanager
# 标准库：路径类型
from pathlib import Path
# 标准库：迭代器类型（给 contextmanager 标注返回值）
from collections.abc import Iterator

# 锁表：{规范化路径: [可重入锁, 引用计数]}。
# 计数用 list 包装是为了在闭包里原地修改（tuple 改不了，dict 会丢锁对象）。
_LOCKS: dict[str, list] = {}
# 保护锁表本身的锁：并发取锁时不能同时改动 _LOCKS
_GUARD = threading.Lock()
# 等锁的最长秒数：真死锁时宁愿报错让用户看到，也不要把对话卡死在这里
_LOCK_TIMEOUT = 30.0


def lock_key(path: str | Path) -> str:
    """把路径规范成锁表里的键。

    `D:/W/a.py`、`D:\\W\\a.py`、`./a.py` 在 Windows 上可能指向同一文件，
    不统一的话两把锁各锁各的，等于没锁。

    :param path: 原始路径（字符串或 Path）
    :return: 规范化后的键（统一分隔符、统一大小写）
    """
    return os.path.normcase(os.path.normpath(str(path).strip()))


def _acquire_entry(key: str) -> list:
    """取出（必要时创建）某个路径的锁条目，并给它 +1 引用。

    :param key: `lock_key` 的结果
    :return: 锁条目 [RLock, 引用计数]
    """
    with _GUARD:
        entry = _LOCKS.get(key)
        if entry is None:
            entry = [threading.RLock(), 0]
            _LOCKS[key] = entry
        entry[1] += 1
        return entry


def _release_entry(key: str, entry: list) -> None:
    """释放一次引用，引用归零时把该路径的锁从表里删掉。

    :param key: `lock_key` 的结果
    :param entry: 之前 `_acquire_entry` 返回的条目
    """
    with _GUARD:
        entry[1] -= 1
        if entry[1] <= 0 and _LOCKS.get(key) is entry:
            _LOCKS.pop(key, None)


@contextmanager
def path_lock(path: str | Path) -> Iterator[None]:
    """独占某个文件路径，退出 `with` 时自动释放。

    用法：`with path_lock(p): ...读改写...`

    :param path: 要独占的路径（文件或目录都可以，锁粒度只到"这个路径字符串"）
    :raises TimeoutError: 等锁超过 `_LOCK_TIMEOUT` 秒（说明有别的写操作卡住了）
    """
    key = lock_key(path)
    entry = _acquire_entry(key)
    lock: threading.RLock = entry[0]
    try:
        acquired = lock.acquire(timeout=_LOCK_TIMEOUT)
        if not acquired:
            raise TimeoutError(f"等待文件锁超时（{_LOCK_TIMEOUT:.0f}s）：{path}")
        try:
            yield
        finally:
            lock.release()
    finally:
        _release_entry(key, entry)


def locked_count() -> int:
    """当前锁表里有多少个路径（仅用于测试与诊断，不参与业务判断）。"""
    with _GUARD:
        return len(_LOCKS)


def reset_for_test() -> None:
    """清空锁表（只给测试用：用例之间不能互相继承锁状态）。"""
    with _GUARD:
        _LOCKS.clear()
