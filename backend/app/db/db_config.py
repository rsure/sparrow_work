"""数据库配置：创建 SQLAlchemy 引擎与会话工厂，并提供会话上下文管理器、建表入口。"""

# 标准库：把「生成器函数」装饰成 with 语句可用的上下文管理器（get_session 用）
from contextlib import contextmanager
# 标准库：路径对象，run_migrations 要用它定位 alembic.ini 与 migrations/ 目录
from pathlib import Path
# SQLAlchemy ORM：sessionmaker 造会话工厂，Session 是会话类型，
# DeclarativeBase 是所有 ORM 实体类的声明式基类
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
# SQLAlchemy 核心：create_engine 创建数据库引擎，event 注册连接级监听（用来执行 PRAGMA）
from sqlalchemy import create_engine, event

class Base(DeclarativeBase):
    """所有 ORM 实体的声明式基类。"""
    pass


# SQLite 数据库文件名（相对当前目录）
# 相对路径意味着库文件会落在进程启动时的工作目录下；LangGraph 的异步检查点
# （AsyncSqliteSaver）也用这个文件名，二者必须指向同一个库，重启后才能恢复对话现场
DATABASE_PATH = "app.db"
# SQLAlchemy 使用的连接串（三斜杠表示 SQLite 相对路径）
DATABASE_URL = f"sqlite:///./{DATABASE_PATH}"

# echo=True 会打印执行的 SQL,方便调试;生产环境设为 False
# 全局唯一的数据库引擎：连接池、方言等配置都集中在这里
engine = create_engine(
    DATABASE_URL,
    echo=False,
    # SQLite 需要这个参数才能在多线程(FastAPI 等)下工作
    connect_args={"check_same_thread": False},
)

@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _):
    """每条 SQLite 连接建立时执行 PRAGMA 调优：开启 WAL、放宽同步、打开外键约束。

    :param dbapi_conn: SQLAlchemy 交过来的底层 sqlite3 连接对象
    :param _: 连接记录（第二个位置参数），本函数用不到，故用下划线占位
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")       # 读写并发更友好
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")        # SQLite 默认关，必须手动开
    cur.close()

# 会话工厂：每次调用生成一个 Session。
# autoflush=False 关闭自动 flush，避免查询时意外触发写库；
# expire_on_commit=False 让 commit 后对象属性仍可读，省得序列化响应时再查一次库
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# 原生 DBAPI 连接（历史遗留，供同步读取/测试使用）：
# 对话检查点现在已经换成异步实现（AsyncSqliteSaver + aiosqlite，见 app/agents/rag_agent.py），
# 不再需要这条连接；但它仍保留给需要"直接摸 sqlite3"的同步调用方（例如回归测试）。
# 这里用 engine.raw_connection() 常驻一条连接：
#   - 单机单用户，读写是串行的，不需要连接池；
#   - check_same_thread=False 与上面 engine 的设置保持一致，允许跨线程访问。
raw_connection = engine.raw_connection()


def get_raw_connection():
    """返回同步 sqlite3 连接（给需要直接访问 DBAPI 的调用方，例如测试里的独立读库）。

    调用方**不要**关闭它——它被整个进程共用。

    :return: DBAPI 层的sqlite3.Connection 对象
    """
    # SQLAlchemy 2.x 推荐用 driver_connection 取底层连接；
    # 老版本没有这个属性，故留一个 getattr 兜底（两者的 warning 行为都比 _ConnectionFairy 好）
    connection = raw_connection
    driver_conn = getattr(connection, "driver_connection", None)
    if driver_conn is not None:
        return driver_conn
    return connection.connection


@contextmanager
def get_session() -> Session:
    """获取 Session 的上下文管理器,自动 commit / rollback / close

    用法：`with get_session() as s: ...`，正常退出时提交，抛异常时回滚并向上抛。
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()



def _current_revision() -> str:
    """读取数据库当前记录的迁移版本号。

    :return: 版本号字符串；没有 alembic_version 表或表里没记录时返回空串
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if not inspector.has_table("alembic_version"):
            return ""
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        return str(rows[0][0]) if rows and rows[0][0] else ""
    except Exception:
        # 读不到就当作"没记录"，让调用方走 stamp 分支
        return ""


def run_migrations() -> None:
    """把数据库升级到最新版本（对应 doc/24 OPS-1）。

    与 init_db 的分工：
        - init_db 用裸 create_all 建表，**只保证"表在"**，不管字段对不对；
        - run_migrations 走 Alembic，保证"结构与实体声明一致"，加字段/改字段都靠它。

    为什么不直接用迁移替代 init_db（稳妥起见先并存）：
        存量用户的库里表是 create_all 建的，没有 alembic_version 记录，
        直接 upgrade 会认为这些表不存在而重复创建。稳妥策略是：
        首次运行时先 stamp（只登记版本号、不动表结构），此后的真实变更才由迁移执行。

    任何一步失败都只记警告、不阻断启动：
        数据库结构问题应该由测试与运维暴露，而不是让桌面端起不来。
    """
    # 标准库：记录异常信息（本项目尚未统一日志组件，先用标准 logging）
    import logging

    logger = logging.getLogger(__name__)

    # 后端工程根目录（backend/）：alembic.ini 与 migrations/ 都在它下面。
    # 注意用绝对路径：打包成 PyInstaller 单文件后，工作目录不一定是 backend/。
    backend_root = Path(__file__).resolve().parents[2]
    ini_path = backend_root / "alembic.ini"
    if not ini_path.exists():
        # 没带迁移文件（例如裁剪过的发行版）：退回 create_all 即可，不算错误
        logger.warning("未找到 alembic.ini（%s），本次仅用 create_all 建表", ini_path)
        return

    try:
        # 延迟导入：alembic 是较重的依赖，只在真的要跑迁移时才加载
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect

        config = Config(str(ini_path))
        config.set_main_option("script_location", str(backend_root / "migrations"))

        # 已建过表的旧库没有版本记录（或版本记录是空的），先 stamp 到基线，
        # 避免 upgrade 认为这些表不存在而重复创建、报 "table already exists"。
        inspector = inspect(engine)
        has_tables = bool(inspector.get_table_names())
        if has_tables:
            current = _current_revision()
            if not current:
                logger.info("检测到存量数据库，标记为迁移基线 0001_initial")
                command.stamp(config, "0001_initial")

        command.upgrade(config, "head")
        logger.info("数据库已升级到最新版本")
    except Exception as e:
        # 迁移失败不阻断启动：让应用先跑起来，问题由开发者从日志里看到
        logger.warning("数据库迁移未成功（%s），已退回 create_all 结果继续启动", e)


def init_db() -> None:
    """创建所有表(如果不存在)

    应用启动时调用一次（见 main.py 的 create_app），已存在的表会跳过，不会丢数据。
    """
    # 延迟导入：实体类只有被导入过才会注册到 Base.metadata，这里导入保证建表时带上它
    from app.entity.scan_task import TaskInfo  # noqa: F401  延迟导入,确保实体注册到 Base
    # 对话记录实体：ChatSession=一次会话（前端「最近会话」列表的数据源），
    # ChatMessage=一条可见消息（提问/回答、工具轨迹、结束原因），同样挂在上面这个 Base 上
    from app.entity.chat_record import ChatMessage, ChatSession  # noqa: F401  延迟导入,确保实体注册到 Base
    # 审计与设置实体同样挂在 app.entity.models.Base 上，必须导入后才被下面的 RagBase.create_all 建表
    from app.entity.audit_log import AuditLog  # noqa: F401  延迟导入,确保实体注册到 Base
    from app.entity.app_setting import AppSetting  # noqa: F401  延迟导入,确保实体注册到 Base
    # 工作区级授权（UX-7 workspace 模式）：同样是业务表，必须 import 才会被 create_all 建出来
    from app.entity.approval import Approval  # noqa: F401  延迟导入,确保实体注册到 Base
    # Agent 执行轨迹（OPS-6）：诊断导出与历史回放都靠它
    from app.entity.trace import TraceEvent  # noqa: F401  延迟导入,确保实体注册到 Base
    # 工作空间记忆（MEM）：按工作区隔离的一句话结论，新对话开场时注入
    from app.entity.memory import Memory  # noqa: F401  延迟导入,确保实体注册到 Base
    # RAG 的 documents / chunks / index_meta 定义在 models.py 里，用的是那边自己的 Base，
    # 不在本文件 Base.metadata 中，必须单独 create_all，否则全新数据库里没有这三张表
    from app.entity.models import Base as RagBase
    Base.metadata.create_all(bind=engine)
    RagBase.metadata.create_all(bind=engine)
