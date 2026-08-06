"""应用级公共常量。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库：读取进程环境变量，用来判断当前是否运行在 Electron 打包后的环境里
import os

# Electron 打包成 exe 时，前端资源以 file:// 加载，Origin 为 "null"，
# 因此生产环境默认放开跨域（仅监听 127.0.0.1，不对外网暴露）。
# 取值：环境变量 APP_PACKAGED 为 "1" 时是 True（打包运行），否则为 False（开发/直接运行）
IS_PACKAGED: bool = os.environ.get("APP_PACKAGED") == "1"
