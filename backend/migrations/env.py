# migrations/env.py —— Alembic 运行环境（对应 doc/24 OPS-1）。
"""
本文件是 Alembic 与本项目「现有代码」的桥，负责三件事：

    1. 让 Alembic 复用app/db/db_config.py 里的 engine 与两个 Base；
    2. autogenerate 时能对照**真实的实体**生成迁移，而不是猜；
    3. 把SQLite 的几处方言差异（外键开关、批量 ALTER 不支持）处理掉。

**为什么要两个 Base**（本项目的特殊性）：
    app/db/db_config.Base —— 业务表：app_settings / chat_* / audit_logs / task_info
    app/entity/models.Base —— RAG 表：documents / chunks / index_meta（历史上单独声明）
    两套Base 不在同一个 metadata 里，Alembic 的 autogenerate 必须两个都挂上，
    否则会漏掉一半的表。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：读取 APP_ALEMBIC_URL（只在「迁移漂移检查」时设置，见 app/db/migration_check.py）
import os

# Alembic 核心：context 提供连接与迁移配置
from alembic import context

# SQLAlchemy：需要 pool 用来给自增列做 alter 时的特殊处理
from sqlalchemy import engine_from_config, pool

# 项目内：业务表的 ORM 基类与数据库引擎（直接复用，不在 ini 里另配一套地址）
from app.db.db_config import Base as AppBase
from app.db.db_config import engine
# 项目内：RAG 表的 ORM 基类（历史上单独声明，与业务 Base 不是同一个）
from app.entity.models import Base as RagBase


# 把两个 Base 合并成一份"目标结构"，autogenerate 才知道完整 schema 是什么样。
# target_metadata 同时接受两个对象是 Alembic 支持的用法（内部会遍历各自的 metadata）。
target_metadata = [AppBase.metadata, RagBase.metadata]

# Alembic 注入的迁移配置对象（内容来自 alembic.ini 的 [alembic] 段）
config = context.config

# 环境变量名：设了它就改用该地址（迁移漂移检查用临时库），否则用业务引擎。
# 为什么需要这个开关：`alembic check` / `upgrade` 要一个"干净库"才能比对出真实差异，
# 直接对着开发者本机 app.db 跑，结果会被手工改库与历史版本污染。
URL_ENV_VAR = "APP_ALEMBIC_URL"

# LangGraph 自己建、自己管的表：不归 ORM 管（见 app/agents/rag_agent.py 的 SqliteSaver）。
# 若参与比对，autogenerate 会认为"库里多出来的表该删"，进而生成 DROP TABLE（毁对话历史）。
_LANGGRAPH_MANAGED_TABLES = frozenset(
    {"checkpoints", "writes", "checkpoint_blobs", "checkpoint_writes"}
)


def _target_url() -> str:
    """返回本次迁移要连的数据库地址。

    :return: APP_ALEMBIC_URL 的值；未设置时用业务引擎的地址
    """
    return os.environ.get(URL_ENV_VAR) or str(engine.url)


def _is_sqlite_int_pk_noise(meta_col, db_col) -> bool:
    """判断「这一列的可空性差异」是不是 SQLite 的固有噪声，而不是真的漂移。

    SQLite 的 `INTEGER PRIMARY KEY` 是 rowid 的别名，建表时不会写 NOT NULL，
    反射回来 nullable 恒为 True；而 SQLAlchemy 的 metadata 里主键列是 nullable=False。
    于是 `alembic check` 每次都会报这三列（documents.id / chunks.id / index_meta.key）要改可空性，
    属于永远修不掉的假阳性，只能按"主键 + 整型"这个组合放过。

    放过的是**整列比较**（类型变化也会一起跳过），这是有意的取舍：
    主键类型在 SQLite 里几乎不会变，换来的是 `alembic check` 可用。

    :param meta_col: metadata 里的列（nullable=False）
    :param db_col: 数据库反射出来的列（nullable=True）
    :return: True 表示应当跳过这一列的比较
    """
    # 延迟导入：避免影响 alembic 正常的模块加载路径
    from sqlalchemy import Integer

    if db_col is None:
        return False
    if not getattr(meta_col, "primary_key", False):
        return False
    # 只有"metadata NOT NULL + 库里可空"这个方向才是 SQLite 噪声
    if getattr(meta_col, "nullable", True) or not getattr(db_col, "nullable", False):
        return False
    return isinstance(meta_col.type, Integer)


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """告诉 Alembic 哪些对象不参与 autogenerate / check 的比对。

    :param obj: 待判断对象（表 / 列 / 索引 / 约束）
    :param name: 对象名
    :param type_: 对象类型字符串："table" / "column" / "index" / "unique_constraint" …
    :param reflected: 是否来自数据库反射（True=库里的，False=metadata 里的）
    :param compare_to: 对比目标（列比较时有值）
    :return: False 表示跳过该对象
    """
    if type_ == "table" and name in _LANGGRAPH_MANAGED_TABLES:
        return False
    if type_ == "column" and _is_sqlite_int_pk_noise(obj, compare_to):
        return False
    return True


def _include_app_tables() -> None:
    """把所有 ORM 实体导入一遍，确保它们都注册到各自 Base 的 metadata 上。

    为什么需要：实体类是"被 import 才会注册"的延迟加载风格
    （见 db_config.init_db 里的延迟导入）。若这里不导入，
    autogenerate 会认为项目里一张表都没有，生成的迁移是空的。
    """
    # 业务表实体
    from app.entity.app_setting import AppSetting  # noqa: F401
    # 工作区级授权表（UX-7）：不导入的话 alembic check 会把 approvals 当成"该删掉的表"
    from app.entity.approval import Approval  # noqa: F401
    from app.entity.audit_log import AuditLog  # noqa: F401
    from app.entity.chat_record import ChatMessage, ChatSession  # noqa: F401
    from app.entity.scan_task import TaskInfo  # noqa: F401
    # OPS-6 的执行轨迹表：不导入的话 alembic check 会认为 trace_events 是"该删掉的表"
    from app.entity.trace import TraceEvent  # noqa: F401
    # MEM 的工作空间记忆表：同上，不导入会被当成"库里多出来的表"
    from app.entity.memory import Memory  # noqa: F401
    # RAG 表实体定义在 app/entity/models.py 里，import 即注册
    from app.entity import models  # noqa: F401


def run_migrations_offline() -> None:
    """离线模式：不连数据库，只把 SQL 打到标准输出（用于生成/审阅脚本）。"""
    _include_app_tables()
    # url 从 _target_url() 取：平时等于业务引擎地址，跑漂移检查时等于临时库
    url = _target_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        # compare_type 让 autogenerate 能发现字段类型变化（本项目字符串字段较多，值得开）
        compare_type=True,
        # SQLite 不支持大部分 ALTER，用 batch 模式把改表翻译成"建新表+拷贝"
        render_as_batch=True,
        # 过滤掉 LangGraph 自管表与 SQLite 主键可空性噪声（见 _include_object）
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连上真实数据库执行迁移。"""
    _include_app_tables()
    # 关键：默认直接用项目自己的 engine，而不是 alembic.ini 里的地址——
    # 这样迁移用的就是业务同款连接（含 WAL / foreign_keys 等 PRAGMA 调优），
    # 不会出现"迁移库和业务库其实是两个文件"这种难查的问题。
    # 例外：设置了 APP_ALEMBIC_URL（漂移检查用临时库）时按该地址另开一个引擎。
    override = os.environ.get(URL_ENV_VAR)
    if override:
        # SQLAlchemy：按临时库地址建引擎（不挂业务库的 PRAGMA，避免在临时文件上留 WAL）
        from sqlalchemy import create_engine

        connectable = create_engine(override, connect_args={"check_same_thread": False})
    else:
        connectable = engine

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
                # 过滤掉 LangGraph 自管表与 SQLite 主键可空性噪声（见 _include_object）
                include_object=_include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # 临时库引擎必须显式释放：Windows 上连接池只要还握着文件句柄，
        # 调用方删除临时目录就会报 WinError 32（文件被占用）。
        if override:
            connectable.dispose()


# Alembic 会把该模块当成普通脚本导入执行，因此按 __name__ 分派运行模式：
# 直接 `python migrations/env.py` 跑的是 offline，交给 alembic 命令时跑的是 online。
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()