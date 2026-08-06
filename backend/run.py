"""uv 项目入口：`uv run app-backend` 或 `uv run python run.py` 启动后端。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库：解析命令行参数（--host / --port / --reload）
import argparse
# 标准库：sys.frozen 用来判断是否运行在 PyInstaller 冻结环境里；sys.exit 把退出码返回给调用方
import sys


def main() -> None:
    """启动 uvicorn；参数可覆盖环境变量（Electron 主进程会用到 --port）。"""
    # uvicorn 放在函数内部导入：只有真正要起服务时才加载，import 本模块的测试不会被它拖慢
    import uvicorn

    # 项目内：全局配置对象（读 .env / 环境变量），作为 --host / --port 的默认值
    from app.config import settings
    # 项目内：父子进程守卫，Electron 主进程退出后自动结束本后端，避免留下孤儿进程
    from app.parent_guard import start_parent_guard

    parser = argparse.ArgumentParser(description="启动 FastAPI 后端服务")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    # 由 Electron 拉起时：父进程退出后自动结束本进程（防止强杀应用留下孤儿后端）
    start_parent_guard()

    # 冻结环境（PyInstaller）里不能用 "app.main:app" 字符串导入：
    # 冻结后 sys.path 上没有可导入的包路径，uvicorn 的动态 import 会失败。
    if getattr(sys, "frozen", False):
        from app.main import app

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    sys.exit(main())
