# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 FastAPI 后端打成单目录可执行文件。

用法（在 backend/ 目录下）：
    uv run pyinstaller --noconfirm --clean app-backend.spec

产物：backend/dist/app-backend/app-backend.exe（Windows）
把该目录整体复制到 electron/resources/backend/ 后，Electron 打包会带进安装包。
"""

# 路径工具：定位 run.py 与打包输出目录
from pathlib import Path

# PyInstaller 官方钩子工具：自动收集某个包下的全部子模块，避免动态导入在冻结后失败
from PyInstaller.utils.hooks import collect_submodules

# PyInstaller 通过 exec 执行本文件，__file__ 可能缺失，这里做兼容
# SPECPATH 是 PyInstaller 注入的变量，指向 .spec 文件所在目录
SPEC_DIR = Path(globals().get("SPECPATH", Path.cwd()))

# app 包内部是静态 import，但 uvicorn/路由聚合等场景可能出现动态导入，
# 这里显式收集整个包，避免冻结后 import 失败。
app_submodules = collect_submodules("app")

# Analysis：第一阶段。负责分析入口脚本，找出所有需要的模块、二进制与数据文件
a = Analysis(
    # 打包入口脚本（后端启动文件），PyInstaller 从它开始追踪依赖
    [str(SPEC_DIR / "run.py")],
    # 模块搜索路径，保证能 import 到同级目录下的 app 包
    pathex=[str(SPEC_DIR)],
    # 需要额外打包的动态库（这里没有）
    binaries=[],
    # 需要额外打包的数据文件（这里没有，静态资源由 Electron 侧提供）
    datas=[],
    # 隐藏导入：这些模块是运行时才被 import 的，静态分析发现不了，必须手工列出
    hiddenimports=app_submodules
    + [
        "app",
        "uvicorn.logging",  # uvicorn 日志格式
        "uvicorn.loops.auto",  # 事件循环自动选择（asyncio/uvloop）
        "uvicorn.protocols.http.auto",  # HTTP 协议实现自动选择
        "uvicorn.protocols.http.h11_impl",  # 纯 Python 的 HTTP/1.1 实现，作为兜底
        "uvicorn.protocols.websockets.auto",  # WebSocket 协议自动选择
        "uvicorn.lifespan.on",  # 支持 startup/shutdown 生命周期钩子
        # Excel 解析（EXT-4）：openpyxl 内部按名字动态导入子模块，静态分析抓不到
        "openpyxl",
        "openpyxl.cell._writer",
        "openpyxl.styles",
        # MCP 客户端（EXT-2）：三条传输实现分散在 mcp.client 下的不同模块里，
        # 且适配器内部按字符串动态选择，静态分析抓不到
        "mcp",
        "mcp.client.stdio",
        "mcp.client.sse",
        "mcp.client.streamable_http",
        "langchain_mcp_adapters",
        "langchain_mcp_adapters.client",
        "langchain_mcp_adapters.tools",
        "langchain_mcp_adapters.sessions",
    ],
    # 额外的 hook 搜索目录（用默认值即可）
    hookspath=[],
    # 传给 hook 的配置（用默认值即可）
    hooksconfig={},
    # 运行时 hook 脚本（用默认值即可）
    runtime_hooks=[],
    # 明确排除用不到的重量级包，缩小产物体积
    excludes=["tkinter", "pytest"],
    # False = 生成压缩过的 .pyz 归档，体积更小
    noarchive=False,
)

# PYZ：把纯 Python 模块编译压缩成一个归档文件
pyz = PYZ(a.pure)

# EXE：生成可执行文件本体（这里只是引导程序，真正的依赖在 COLLECT 阶段平铺）
exe = EXE(
    pyz,
    a.scripts,
    [],
    # True = 依赖不塞进 exe，而是放到 COLLECT 产物目录里（单目录模式，启动更快）
    exclude_binaries=True,
    # 产物名：app-backend.exe
    name="app-backend",
    # False = 不生成调试版引导程序
    debug=False,
    # True = 忽略 Ctrl+C 等信号（后端要能被 Electron 正常终止，故为 False）
    bootloader_ignore_signals=False,
    # 是否 strip 符号表（Windows 上无效，保持 False）
    strip=False,
    # 是否用 UPX 进一步压缩（可能被杀软误报，关闭）
    upx=False,
    # True = 保留控制台窗口，方便开发期看后端日志
    console=True,
    # 无窗口模式下是否弹错误框（console=True 时无意义）
    disable_windowed_traceback=False,
)

# COLLECT：把 exe、依赖库、数据文件平铺收集到 dist/app-backend/ 目录
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    # 同上：不做 strip / UPX
    strip=False,
    upx=False,
    # 输出目录名：backend/dist/app-backend/
    name="app-backend",
)
