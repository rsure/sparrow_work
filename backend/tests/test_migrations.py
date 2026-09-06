"""数据库迁移基线（OPS-1）的回归测试。

为什么这些用例重要（本项目踩过的坑）：
    1. 对着**已建好表**的库跑 `alembic revision --autogenerate`，它会认为
       "库里多出来的表应该删掉"，生成 DROP TABLE 的反向迁移——
       本项目会连 LangGraph 的 checkpoints / writes（对话历史）一起删掉。
    2. 索引只在 ORM 的 `Index(...)` 里声明，若基线迁移漏写，
       "迁移建出来的新库"会缺索引而"老库"有，同一份代码在新老库上表现不一致。
    3. 存量库没有 alembic_version 记录，直接 upgrade 会因 "table already exists" 失败。

所以这里用**临时库**跑真实迁移，而不是只检查文件存在。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：临时目录，用于放隔离的测试数据库
from pathlib import Path

# 测试框架：临时目录 fixture 与断言
import pytest

# 项目内：数据库引擎与迁移入口
from app.db import db_config


# 本项目自有、应纳入版本管理的表（checkpoints / writes 由 LangGraph 自管，不在此列）
_MANAGED_TABLES = {
    "app_settings",
    "approvals",
    "audit_logs",
    "chat_message",
    "chat_session",
    "chunks",
    "documents",
    "index_meta",
    "task_info",
}


def _head_revision() -> str:
    """读出当前迁移链的最新版本号（而不是写死字符串）。

    为什么写活：每加一条迁移都要改测试的话，这条断言迟早会被"顺手改成新值"而失去意义。
    这里直接问 Alembic"head 是哪个版本"，迁移链前进时测试自动跟上。

    :return: 最新 revision id
    """
    # Alembic：ScriptDirectory 能遍历 versions 目录并算出 head
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(db_config.__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(db_config.__file__).resolve().parents[2] / "migrations"),
    )
    return ScriptDirectory.from_config(config).get_current_head()


def _run_migrations_against(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 db_config 的引擎指向临时库后跑一次完整迁移。

    :param db_path: 目标数据库文件路径
    :param monkeypatch: pytest 的替换工具（用来换掉全局 engine）
    """
    # SQLAlchemy：造一个指向临时文件的引擎
    from sqlalchemy import create_engine

    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_config, "engine", temp_engine)
    db_config.run_migrations()


def _table_names(db_path: Path) -> set[str]:
    """读出数据库里所有表名（不含 sqlite 内部表）。

    :param db_path: 数据库文件路径
    :return: 表名集合
    """
    # 标准库：直接用 sqlite3 读，不经过 ORM，断言更直白
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        con.close()
    return {r[0] for r in rows} - {"sqlite_sequence"}


def test_migration_builds_all_tables_on_fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """全新库执行 upgrade 后应建出全部自有表，并打上版本标记。"""
    db_path = tmp_path / "fresh.db"
    _run_migrations_against(db_path, monkeypatch)

    tables = _table_names(db_path)
    assert _MANAGED_TABLES.issubset(tables), f"缺少表：{_MANAGED_TABLES - tables}"
    assert "alembic_version" in tables

    # 版本应被记录成基线号
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        con.close()
    assert version == _head_revision()


def test_migration_creates_indexes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """基线必须建出实体类里声明的索引，否则新库与老库性能表现不一致。"""
    db_path = tmp_path / "fresh.db"
    _run_migrations_against(db_path, monkeypatch)

    # 标准库：sqlite3 读索引
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        def indexes(table: str) -> set[str]:
            """取某张表的自定义索引名（跳过 SQLite 自动建的）。"""
            rows = con.execute(f"PRAGMA index_list({table})").fetchall()
            return {r[1] for r in rows if not r[1].startswith("sqlite_autoindex")}

        assert "idx_chat_message_session" in indexes("chat_message")
        assert {"ix_audit_logs_session_id", "ix_audit_logs_tool", "ix_audit_logs_created_at"} <= indexes("audit_logs")
        assert {"idx_chunks_doc", "idx_chunks_hash", "idx_chunks_embedded", "idx_chunks_model"} <= indexes("chunks")
    finally:
        con.close()


def test_migration_is_reversible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """downgrade 到 base 应把自有表全部删掉（迁移必须可逆）。"""
    db_path = tmp_path / "fresh.db"
    _run_migrations_against(db_path, monkeypatch)
    assert _MANAGED_TABLES <= _table_names(db_path)

    # Alembic：执行回退
    from alembic import command
    from alembic.config import Config

    backend_root = Path(db_config.__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    command.downgrade(config, "base")

    remaining = _table_names(db_path)
    assert not (_MANAGED_TABLES & remaining), f"回退后仍残留表：{_MANAGED_TABLES & remaining}"


def test_migration_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复跑迁移不应报错（应用每次启动都会调用）。"""
    db_path = tmp_path / "fresh.db"
    _run_migrations_against(db_path, monkeypatch)
    first = _table_names(db_path)
    _run_migrations_against(db_path, monkeypatch)   # 第二次：应无任何动作
    assert _table_names(db_path) == first


def test_existing_database_gets_stamped_not_recreated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """存量库（表已建好、无版本记录）应被 stamp，而不是重复建表报错。

    这是升级路径最容易出问题的一环：直接 upgrade 会撞上 "table already exists"。
    """
    # 标准库：先用 create_all 的方式手工造一张"存量表"，模拟老用户数据库
    import sqlite3

    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(str(db_path))
    try:
        con.execute('CREATE TABLE app_settings ("key" VARCHAR(64) NOT NULL, value TEXT NOT NULL, PRIMARY KEY ("key"))')
        con.execute("INSERT INTO app_settings (key, value) VALUES ('legacy.key', 'legacy-value')")
        con.commit()
    finally:
        con.close()

    _run_migrations_against(db_path, monkeypatch)

    # 版本应被标到基线
    con = sqlite3.connect(str(db_path))
    try:
        version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        # 关键：老数据必须还在
        row = con.execute("SELECT value FROM app_settings WHERE key='legacy.key'").fetchone()
    finally:
        con.close()
    assert version == _head_revision()
    assert row is not None and row[0] == "legacy-value", "迁移把存量数据弄丢了"


def test_langgraph_tables_not_touched_by_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """基线不得创建/删除 LangGraph 自管的 checkpoints / writes（那是对话历史）。"""
    db_path = tmp_path / "fresh.db"
    _run_migrations_against(db_path, monkeypatch)
    tables = _table_names(db_path)
    # 迁移**不创建**它们（它们由 SqliteSaver 运行时自己建）
    assert "checkpoints" not in tables
    assert "writes" not in tables


def test_entities_match_migrations() -> None:
    """实体声明与迁移脚本必须零漂移（`alembic check` 的等价校验）。

    这是提交流程 `pnpm run check:migrations` 的测试版：改了实体却忘了写迁移时，
    这条用例会失败，并且失败信息里会直接给出缺了哪个字段。

    检查跑在临时库上（见 app/db/migration_check.py），不会碰开发者的 app.db。
    """
    # 项目内：临时库上重建迁移链 + 与 ORM 元数据比对
    from app.db.migration_check import check_for_drift

    diffs = check_for_drift()
    assert diffs == [], f"实体与迁移存在漂移，请补一条迁移：{diffs}"