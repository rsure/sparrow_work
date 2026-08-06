# migrations/script.py.mako —— 新建迁移文件时的模板（Alembic 默认模板，保留 rev/long/ 类型注释）
"""${message}

修订 ID: ${up_revision}
修订时间: ${down_revision | comma,n}
创建时间: ${create_date}
"""
# 让类型注解延迟求值（PEP 563），迁移脚本里大量使用 X | None 语法
from __future__ import annotations

# typing：Sequence 标注 upgrade/downgrade 的参数类型
from typing import Sequence, Union

# Alembic 核心：op 是执行 DDL 的操作对象，context 提供迁移配置
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# 本次迁移的版本号（由 Alembic 维护，不要手工改）
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """升级到新版本：写这里要做的 DDL。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回退到旧版本：写这里的反向 DDL（保证迁移可逆）。"""
    ${downgrades if downgrades else "pass"}