# app/core/paths.py
"""用户数据目录的唯一入口：日志、密钥、导出包都往这里放。

为什么要有这个文件：
    "用户数据放哪"是一个跨平台的判断题（Windows 用 %APPDATA%、macOS 用
    Application Support、Linux 用 XDG_CONFIG_HOME）。原先这段逻辑只写在
    `services/secrets.py` 里，日志与诊断导出如果各抄一遍，三个地方迟早会漂。
    因此把它抽成一处，其它模块只调 `data_dir()` / `logs_dir()`。

注意：**不要**把它指向仓库目录或打包目录。
    打包后 exe 所在目录可能只读（Program Files），写日志会直接失败。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：读取环境变量（APPDATA / XDG_CONFIG_HOME）并判断平台
import os
import sys
# 标准库：路径对象
from pathlib import Path


# 应用数据目录名：与 keyring 的 service 名保持一致，方便用户在一个地方找到全部数据
APP_DIR_NAME = "app-backend"


def data_dir() -> Path:
    """返回本应用的用户数据目录（不存在时自动创建）。

    :return: 绝对路径，如 `C:/Users/x/AppData/Roaming/app-backend`
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    directory = base / APP_DIR_NAME
    # 创建失败（极端只读环境）不抛：调用方拿到路径后自己决定要不要写
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return directory


def logs_dir() -> Path:
    """返回日志目录（不存在时自动创建）。

    :return: 绝对路径，如 `.../app-backend/logs`
    """
    directory = data_dir() / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return directory


def log_file() -> Path:
    """返回主日志文件路径。

    :return: 绝对路径，如 `.../app-backend/logs/app.log`
    """
    return logs_dir() / "app.log"
