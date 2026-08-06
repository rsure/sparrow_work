"""父进程守护：Electron 被强杀（不触发 will-quit）时，避免后端变成孤儿进程。

原理：Electron 用 stdin 管道拉起本进程（并把 APP_PARENT_GUARD=1 传下来）。
父进程消失后管道写端关闭，本进程从 stdin 读到 EOF，随即主动退出、释放端口。
父进程存活期间会周期性写入心跳字节，所以这里的阻塞读只用于「感知 EOF」，
不会因为长时间无数据而误判。

独立运行时（`uv run python run.py`、控制台启动、双击 exe）不会设置该变量，
守护线程不启动，stdin 仍归终端/其它用途使用。
"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库：读取 APP_PARENT_GUARD 环境变量，判断是否由 Electron 以管道方式拉起
import os
# 标准库：取得 stdin 流，读不到数据（EOF）即说明父进程已经退出
import sys
# 标准库：把阻塞式的 stdin 读取放到后台线程，避免挡住 uvicorn 的主线程
import threading


def guard_enabled() -> bool:
    """判断是否启用父进程守护：Electron 拉起后端时会带上 APP_PARENT_GUARD=1。"""
    return os.environ.get("APP_PARENT_GUARD") == "1"


def _watch_stdin() -> None:
    """守护线程主体：循环从 stdin 读取数据，读到 EOF（父进程关闭管道）就立即结束本进程。

    读到字节说明父进程还活着，丢弃即可；读不到则调用 os._exit 硬退出，
    不等待 uvicorn 优雅关闭，因为此时端口能尽快释放比优雅更重要。
    """
    stream = sys.stdin
    if stream is None:
        return

    while True:
        try:
            # 每次只读 1 字节：这里只关心「还有没有数据」，不解析内容
            chunk = stream.read(1)
        except ValueError:
            # 流已关闭
            chunk = ""

        if chunk == "":
            print("[parent-guard] 父进程已退出，后端自行关闭", flush=True)
            # 立即结束进程：uvicorn 的优雅关闭在这里没有必要
            os._exit(0)


def start_parent_guard() -> bool:
    """启动守护线程；未启用时返回 False。

    在服务启动时调用一次；返回 True 表示守护线程已在后台运行，
    之后父进程一退出，本进程就会跟着自动关闭。

    :return: True=已启动守护线程，False=当前不是 Electron 托管场景，未启动
    """
    if not guard_enabled():
        return False

    threading.Thread(target=_watch_stdin, name="parent-guard", daemon=True).start()
    print("[parent-guard] 已启用：父进程退出后本进程自动关闭", flush=True)
    return True
