# backend/scripts/check_migrations.py
"""
迁移漂移检查的命令行入口（提交流程用）。

做三件事：
    1. 在临时库上把迁移链跑到 head（顺带验证迁移链本身可执行）；
    2. 对比 ORM 实体声明的结构，发现差异就打印中文说明并以 1 退出；
    3. 一切正常时打一行 OK，退出码 0。

怎么用：
    pnpm run check:migrations            # 在仓库根目录（推荐，git 钩子用的就是它）
    uv run --directory backend python scripts/check_migrations.py

为什么要用脚本而不是直接 `alembic check`：
    直接跑会对着开发者本机的 app.db 比对，历史版本 / 手工改库都会变成噪音；
    这里换成临时库，检查的是"一份干净的迁移链是否与实体一致"，结果可复现。
    逻辑本身仍是 Alembic 的 `command.check`（等价于 `alembic check`）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：把 backend/ 加进 sys.path，这样直接用 `python scripts/xxx.py` 也能 import app
import sys
# 标准库：路径对象，定位后端根目录
from pathlib import Path

# 后端工程根目录（backend/）：本文件在 backend/scripts/ 下，向上一级即 backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# 项目内：真正的检查逻辑（放在 app/ 下，便于测试直接 import）
from app.db.migration_check import check_for_drift  # noqa: E402  （必须在 sys.path 调整之后导入）


def main() -> int:
    """执行漂移检查并把结果打印到终端。

    :return: 进程退出码：0=无漂移，1=发现漂移
    """
    print("[check:migrations] 正在用临时库重建迁移链并比对实体声明…")
    try:
        diffs = check_for_drift()
    except Exception as exc:
        # 迁移链本身跑不通（语法错、依赖缺失）也算校验失败，需要提交者修
        print(f"[check:migrations] 迁移链执行失败：{exc}")
        return 1

    if not diffs:
        print("[check:migrations] OK：实体与迁移一致，未发现漂移")
        return 0

    print("[check:migrations] 发现实体与迁移的漂移：")
    for line in diffs:
        print(f"  - {line}")
    print(
        "\n修复方式：cd backend && uv run alembic revision --autogenerate -m \"描述\"，"
        "然后人工审阅生成的迁移（确认没有 DROP checkpoints/writes）再提交。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
