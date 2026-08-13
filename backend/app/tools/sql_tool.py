# app/tools/sql_tool.py
"""
SQLite 查询工具：sql_query（只读地查本地 .db / .sqlite 文件）。

为什么只读、而且只允许 SELECT：
    数据库文件常常就是"用户的全部业务数据"。一旦允许 UPDATE / DELETE / DROP，
    一次误判就是不可恢复的损失。所以本工具在三个层次上都只做读：
        1. SQL 语法层：只接受 SELECT / WITH / EXPLAIN 开头，出现分号（多语句）直接拒；
        2. 连接层：以 `mode=ro` 的只读 URI 打开，就算语法检查漏了，SQLite 也会报错；
        3. 权限层：在 policy.py 里登记为 Kind.READ，并按 db_path 做路径范围校验
           （与 read_file 同级：系统目录、工作区外的敏感位置都会被拦）。
    三层任一层单独都不够：光靠正则挡不住 `WITH ... DELETE`，光靠只读连接挡不住
    "查一张敏感表然后原样返回"。所以要多层叠加——这就是"纵深防御"。

输出格式：
    首行 `列: a | b | c`，之后每行一条记录，便于模型直接阅读；
    行数超上限会显式标注"已截断"，而不是静默少给数据。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：sqlite3 直接读 .db 文件（项目里已有依赖，不需要新装包）
import sqlite3
# 标准库：monotonic 计时，用于给长查询装一个"超时中断"
import time
# 标准库：urlquote 把 Windows 盘符路径安全地拼进 sqlite 的 file: URI
from urllib.parse import quote
# 标准库：Path 处理用户给的数据库路径
from pathlib import Path

# LangChain 工具装饰器
from langchain_core.tools import tool

# 项目内：权限模型
from app.tools.policy import POLICIES, Action, Kind, make_tool
# 项目内：统一返回格式 + 读操作的路径范围校验
from app.tools.tool_utils import OP_READ, fmt, resolve_abs_path

# 默认返回多少行（模型看几十行足够判断数据结构）
_DEFAULT_ROWS = 50

# 一次最多取多少行：防止 `SELECT * FROM 大表` 把几十万行灌进上下文
_MAX_ROWS = 200

# 单条查询的执行时限（单位：秒）：SQLite 是同步库，只能靠 progress_handler 中断
_QUERY_DEADLINE = 5.0

# 结果文本的字符上限（模型侧的硬预算，超了会写"已截断"）
_MAX_OUTPUT_CHARS = 8_000

# 允许的语句开头（忽略大小写与开头的注释后仍需命中其中之一）
_ALLOWED_PREFIXES = ("select", "with", "explain")

# 尽管白名单已经限定了开头，仍把"写操作关键词"列出来做二次检查：
# 例如 `WITH t AS (SELECT 1) DELETE FROM x` 也是以 WITH 开头的
_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "truncate",
)


def _strip_leading_comments(sql: str) -> str:
    """去掉字符串最前面的 `--` 行注释与 `/* */` 块注释。

    为什么要去掉：模型很喜欢写 `-- 看看用户表\\nSELECT ...`，
    如果直接取前 6 个字符判断开头，就会把这种合法查询误判成"不支持"。

    :param sql: 原始 SQL
    :return: 去掉前导注释与空白后的 SQL
    """
    text = sql.lstrip()
    while True:
        if text.startswith("--"):
            # 行注释：跳到这一行结束
            newline = text.find("\n")
            text = "" if newline < 0 else text[newline + 1:].lstrip()
            continue
        if text.startswith("/*"):
            end = text.find("*/")
            text = "" if end < 0 else text[end + 2:].lstrip()
            continue
        return text


def check_readonly_sql(query: str) -> str | None:
    """校验一条 SQL 是否"只读且单条"。

    :param query: 用户/模型给的 SQL
    :return: 允许时返回 None；不允许时返回原因（直接作为 FAIL 文案）
    """
    text = _strip_leading_comments(query or "")
    if not text:
        return "SQL 不能为空"

    # 分号：只在**末尾**允许一个（很多人习惯写在结尾）。
    # 中间还有分号就是多语句，一律拒绝——多语句是绕过"只读"的最省事办法
    body = text.rstrip()
    inner = body[:-1] if body.endswith(";") else body
    if ";" in inner:
        return "一次只能执行一条 SQL（检测到多条语句）"

    lowered = inner.lower()
    head = lowered.lstrip()
    if not head.startswith(_ALLOWED_PREFIXES):
        return "只允许只读查询：语句必须以 SELECT / WITH / EXPLAIN 开头"
    for word in _FORBIDDEN_KEYWORDS:
        # 关键词两侧要求是"词边界"，避免把 select_notes 这种列名当成 select
        if f" {word} " in f" {head} " or head.startswith(f"{word} "):
            return f"只允许只读查询（检测到会改写数据的 {word.upper()} 语句）"
    return None


def _readonly_uri(path: Path) -> str:
    """把数据库路径拼成 SQLite 的只读 URI。

    为什么用 URI 而不是 `connect(str(path))`：
        普通连接默认是**读写**模式，文件不存在时还会**悄悄新建一个空库**。
        只读 URI（mode=ro）两件事都避免了：文件不存在直接报错，写操作直接失败。

    :param path: 数据库文件的绝对路径
    :return: `file:...?mode=ro` 形式的连接串
    """
    # Windows 的反斜杠在 URI 里要换成正斜杠；盘符后的冒号必须保留（quote 的 safe 参数）
    posix = str(path).replace("\\", "/")
    return f"file:{quote(posix, safe='/:')}?mode=ro"


def _install_deadline(conn: sqlite3.Connection, seconds: float) -> None:
    """给连接装一个"到点就中断"的进度回调。

    SQLite 的 Python 驱动没有 `set_timeout`，长查询会一直占着线程。
    `set_progress_handler` 每执行若干条虚拟机指令回调一次，
    回调返回非 0 值就会让当前语句抛 `OperationalError: interrupted`。

    :param conn: 已打开的只读连接
    :param seconds: 允许执行的最长秒数
    """
    started = time.monotonic()

    def _handler() -> int:
        """返回 1 表示"超时，请中断当前语句"。"""
        return 1 if time.monotonic() - started > seconds else 0

    # 第二个参数是"每多少条虚拟机指令回调一次"，几万次几乎无性能影响
    conn.set_progress_handler(_handler, 20_000)


def _format_cell(value: object) -> str:
    """把单元格值转成一行可读文本。

    :param value: SQLite 返回的原始值（可能是 None / bytes / int / str）
    :return: 用于拼接表格的字符串
    """
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        # 二进制（图片、压缩包）不进上下文，只报长度，否则会把上下文塞满乱码
        return f"<{len(value)} 字节二进制>"
    text = str(value).replace("\r\n", "\n").replace("\n", " ⏎ ").replace("|", "\\|")
    return text


def build_sql_action(db_path: str, query: str = "", **_kwargs: object) -> Action:
    """把一次 sql_query 调用翻译成待裁决的操作。

    路径参数必须在 Action.paths 里交给 policy 校验，否则 `sql_query` 会变成
    "可以打开任意路径的文件"的口子。

    :param db_path: 数据库文件路径
    :param query: SQL（仅用于说明文案的前 60 字，不参与裁决）
    :param _kwargs: max_rows 等其余参数，与裁决无关
    :return: 供裁决的 Action
    """
    resolved = resolve_abs_path(db_path)
    return Action(
        tool="sql_query",
        kind=Kind.READ,
        target=str(resolved),
        paths=(resolved,),
        preview={"db_path": str(resolved), "query": query[:60]},
        detail=f"AI 将以只读方式查询数据库：{resolved.name}",
    )


@tool
@make_tool(
    POLICIES["sql_query"],
    lambda db_path, query, max_rows=_DEFAULT_ROWS: build_sql_action(db_path, query),
)
def sql_query(db_path: str, query: str, max_rows: int = _DEFAULT_ROWS) -> str:
    """以只读方式在本机 SQLite 数据库上执行一条 SELECT 查询。

    适用："这张表有多少行""按月份汇总一下""看看表结构"。
    不适用：改数据（本工具只读）、MySQL/PostgreSQL（只支持 SQLite 文件）、
            导出大结果集（行数与字符数都有上限）。
    查表结构可以用：`SELECT name, sql FROM sqlite_master WHERE type='table'`。

    :param db_path: 数据库文件路径（.db / .sqlite / .sqlite3），必须是绝对路径
                     （与 read_file 一致：相对路径在后端进程里有歧义，一律拒绝）
    :param query: 一条只读 SQL，必须以 SELECT / WITH / EXPLAIN 开头
    :param max_rows: 最多返回多少行，1~200，默认 50
    :return: "OK: 列名 + 各行数据" 或 "FAIL: 原因"
    """
    reason = check_readonly_sql(query)
    if reason:
        return fmt(False, reason)

    try:
        path = resolve_abs_path(db_path)
    except Exception as e:
        return fmt(False, f"数据库路径不合法: {e}")
    if not path.is_file():
        return fmt(False, f"找不到数据库文件：{path}")

    # 路径范围校验再走一遍：工具可能被直接调用（不经 make_tool），不能只依赖 Action
    blocked = _path_reason(path)
    if blocked:
        return fmt(False, blocked)

    limit = max(1, min(_MAX_ROWS, int(max_rows)))
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(_readonly_uri(path), uri=True, timeout=5.0)
        _install_deadline(conn, _QUERY_DEADLINE)
        cursor = conn.execute(query)
        columns = [d[0] for d in (cursor.description or [])]
        # 多取一行用来判断"是否还有更多"，比再发一条 COUNT(*) 便宜
        rows = cursor.fetchmany(limit + 1)
        truncated = len(rows) > limit
        rows = rows[:limit]

        if not columns:
            # 极少数语句（如 EXPLAIN 之外的 PRAGMA 查询）没有列信息
            return fmt(True, "查询已执行，但没有返回任何列")
        if not rows:
            return fmt(True, f"列: {' | '.join(columns)}\n（没有匹配的记录）")

        lines = [f"列: {' | '.join(columns)}"]
        for row in rows:
            lines.append(" | ".join(_format_cell(value) for value in row))
        if truncated:
            lines.append(f"…（超过 {limit} 行，已截断；可加 WHERE 或聚合后再查）")

        text = "\n".join(lines)
        if len(text) > _MAX_OUTPUT_CHARS:
            text = text[:_MAX_OUTPUT_CHARS] + f"\n…（结果超过 {_MAX_OUTPUT_CHARS} 字符，已截断）"
        return fmt(True, f"{text}\n（共 {len(rows)} 行，数据库：{path.name}）")
    except sqlite3.OperationalError as e:
        message = str(e)
        if "interrupted" in message.lower():
            return fmt(False, f"查询超过 {_QUERY_DEADLINE:.0f} 秒被中断，请加索引或缩小范围")
        return fmt(False, f"SQL 执行失败: {message}")
    except sqlite3.DatabaseError as e:
        return fmt(False, f"不是有效的 SQLite 数据库或文件已损坏: {e}")
    finally:
        if conn is not None:
            conn.close()


def _path_reason(path: Path) -> str | None:
    """对数据库文件做一次只读操作的路径范围校验。

    :param path: 已解析的绝对路径
    :return: 允许时返回 None；越界时返回原因
    """
    # 项目内：延迟导入，避免工具模块在 policy 初始化前就去读配置
    from app.tools.tool_utils import path_decision

    return path_decision(path, OP_READ)


# 本模块对外暴露的工具列表
SQL_TOOLS = [sql_query]
