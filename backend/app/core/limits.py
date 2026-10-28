"""HTTP 查询参数 limit 的「默认值 + 上限」契约表（Python 侧）。

为什么需要它：limit 以前是散的 —— 有的端点用 FastAPI 的 Query(ge=1, le=N) 校验，
有的端点干脆原样透传给 SQL（`?limit=1000000` 会把整库拉回来），
Java 侧又另有一套 service 内 clamp。两边数字还对不上（历史消息 Java 100 / Python 200）。

现在这张表是 Python 侧唯一来源，Java 侧镜像在
backend_java/src/main/java/com/example/backendjava/common/PageLimits.java，
两边数字必须逐项一致，改一处就要同步改另一处。

两层的分工：
- HTTP 入口（controller）：用 ``Query(default=..., ge=1, le=MAX)`` 声明，越界由 FastAPI
  直接返回 422，不做「悄悄纠正」；
- 内部入口（service、工具调用）：用 :func:`clamp_limit` 兜底，保证不会把非法的窗口大小
  传给 SQL 的 LIMIT。
"""

# 最近会话列表：默认 20 条，一次最多 100 条（与 PageLimits.MAX_CHAT_SESSIONS 一致）
DEFAULT_CHAT_SESSIONS = 20
MAX_CHAT_SESSIONS = 100

# 历史消息：默认 200 条，上限也是 200（与 PageLimits.MAX_CHAT_HISTORY 一致）
DEFAULT_CHAT_HISTORY = 200
MAX_CHAT_HISTORY = 200

# `@` 文件候选：默认 20 条，最多 50 条
DEFAULT_FILE_SEARCH = 20
MAX_FILE_SEARCH = 50

# 审计记录：默认 100 条，最多 500 条
DEFAULT_AUDIT = 100
MAX_AUDIT = 500

# 记忆条目：默认 100 条，最多 500 条
DEFAULT_MEMORY = 100
MAX_MEMORY = 500

# 轨迹会话列表：默认 50 条，最多 200 条
DEFAULT_TRACE_SESSIONS = 50
MAX_TRACE_SESSIONS = 200

# 轨迹轮次列表：默认 50 条，最多 200 条
DEFAULT_TRACE_TURNS = 50
MAX_TRACE_TURNS = 200

# 轨迹事件：默认 500 条，最多 5000 条
DEFAULT_TRACE_EVENTS = 500
MAX_TRACE_EVENTS = 5000

# 文档列表：默认 50 条，最多 200 条
DEFAULT_RAG_DOCS = 50
MAX_RAG_DOCS = 200


def clamp_limit(limit: int, maximum: int) -> int:
    """把 limit 夹到 ``1..maximum``，供 service / 工具等非 HTTP 入口兜底。

    HTTP 入口已经由 ``Query(ge=1, le=MAX)`` 拦过；这里防的是内部调用方传进 0 或负数，
    让 SQL 的 ``LIMIT 0`` / ``LIMIT -1``（SQLite 里 -1 表示不限制）意外放行。

    :param limit: 调用方给的窗口大小
    :param maximum: 该端点的上限
    :return: 夹到 1~maximum 之后的窗口大小
    """
    return max(1, min(limit, maximum))
