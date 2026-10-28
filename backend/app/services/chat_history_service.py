# app/services/chat_history_service.py
"""对话记录持久化服务：把每轮对话写进 SQLite，并给前端提供「最近会话」与「旧会话消息」的查询。

本模块只做三件事，业务判断一律留在 app/controllers/chat_controller.py：
    1. 写：用户提问入库、助手回答入库（停在「等确认」时先存一条占位，确认后原地补全）
    2. 读：最近会话列表（列表页）、某会话的消息（打开旧会话）、模型补种用的精简历史
    3. 删：把一个会话的记录连同它的消息一起删掉

设计取舍：
    - 表结构见 app/entity/chat_record.py；本模块只负责读写，不定义表。
    - 每条写操作都开一个独立的短事务（with get_session()），写完就提交，不做跨请求的长事务。
    - 所有函数都是同步的：SQLite 本地写一条消息是亚毫秒级，直接调用比丢线程池更好读；
      真换成远程数据库时，调用方（异步的 controller）再改成 asyncio.to_thread 即可。
"""

# 让类型注解延迟求值（PEP 563），便于直接用 X | None、list[dict] 这类新语法
from __future__ import annotations

# 标准库：json 用于 json 格式导出（ensure_ascii=False 才能保留中文）
import json
# 时间工具：datetime 表示时间点（含 utc 时区，见 _utcnow），timezone 提供 UTC 时区常量
from datetime import datetime, timezone

# SQLAlchemy 查询构件：select 组查询、func.count 求条数、or_ 做"标题或内容命中"、
# update 用于"只改标题不改 updated_at"的核心语句
from sqlalchemy import func, or_, select, update

# 项目内：会话上下文管理器（自动 commit / rollback / close）
from app.db.db_config import get_session
# 项目内：limit 的默认值与上限契约表（与 Java 侧 PageLimits 一一对应；本模块是非 HTTP 入口，
# 用 clamp_limit 兜底，保证直接调用本服务也拿不到超限的结果）
from app.core import limits
# 项目内：两个 ORM 实体，本模块所有读写都围绕它们
from app.entity.chat_record import ChatMessage, ChatSession

# 会话标题最多保留多少个字符：再长列表里也显示不下，超出部分截断并加省略号
TITLE_MAX_CHARS = 30
# 会话列表里「最后一条消息」预览最多保留多少个字符
PREVIEW_MAX_CHARS = 60
# 允许的 finish_reason 取值（防止调用方拼错字符串后，前端判不出这一轮是怎么结束的）
FINISH_REASONS = ("done", "stopped", "error", "pending_confirm")


def _utcnow() -> datetime:
    """当前 UTC 时间，且**不带时区信息**（naive）。

    两个刻意选择：
        - 不用 datetime.utcnow()：它从 Python 3.12 起已标记废弃；
        - 不带时区：数据库里 created_at 用的是 SQLite 的 CURRENT_TIMESTAMP，存的也是"不带时区的 UTC"，
          两边保持同一种形状，读出来直接 isoformat() 交给前端即可，不用再做时区转换。

    :return: 形如 datetime(2026, 10, 1, 13, 5, 0, 123456) 的 UTC 时间
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_iso(value: datetime | None) -> str | None:
    """把数据库里的时间列转成 ISO 8601 字符串，供前端直接 new Date() 解析。

    SQLite 的 CURRENT_TIMESTAMP 与 _utcnow() 存的都是"不带时区的 UTC"，这里也不补 Z，
    由前端（scannHistory.vue 的 formatTime）判断缺时区后按 UTC 处理，避免两头各补一次。
    这里也顺带兼容"带时区"的值：真出现了就原样输出（isoformat 会带上 +00:00）。

    :param value: 数据库读出的时间；可能为 None
    :return: 形如 "2026-10-01T13:05:00.123456"；value 为 None 时返回 None
    """
    return value.isoformat() if value else None


def _make_title(text: str) -> str:
    """从用户提问里截出会话标题：压掉换行与多余空白，再按 TITLE_MAX_CHARS 截断。

    :param text: 用户第一条提问的原文
    :return: 一行短标题；提问全为空白时返回固定兜底文案
    """
    one_line = " ".join(text.split())
    if not one_line:
        return "新对话"
    if len(one_line) <= TITLE_MAX_CHARS:
        return one_line
    return one_line[:TITLE_MAX_CHARS] + "…"


def _make_preview(text: str) -> str:
    """把消息正文压成一行短预览，供会话列表展示。

    :param text: 消息正文（可能很长、可能含换行）
    :return: 一行预览；空正文返回空串
    """
    one_line = " ".join(text.split())
    if len(one_line) <= PREVIEW_MAX_CHARS:
        return one_line
    return one_line[:PREVIEW_MAX_CHARS] + "…"


def _touch(sess: ChatSession, *, add_count: int) -> None:
    """写入消息后刷新会话的记账字段：消息条数 +add_count，并把 updated_at 推到当前时刻。

    显式用 _utcnow()（带微秒）而不是让数据库填 CURRENT_TIMESTAMP（精确到秒），
    是因为「最近会话」列表按 updated_at 倒序，同一秒内新建的多个会话否则排不出先后。

    :param sess: 要刷新的会话行
    :param add_count: 本次新增了几条消息（补全已有消息时传 0）
    """
    sess.message_count = (sess.message_count or 0) + add_count
    sess.updated_at = _utcnow()


def append_user_message(session_id: str, content: str, *, mode: str = "agent") -> None:
    """把一条用户提问写入会话；会话不存在时顺手把会话建出来。

    标题只在会话还是新建（title 为空）时填一次，之后不再改动，免得列表标题跳来跳去。

    :param session_id: 会话 id（与 chat_controller 的内存会话、LangGraph thread_id 同值）
    :param content: 用户提问原文
    :param mode: 本轮模式，"agent"=工具 Agent，"rag"=`\\doc` 知识库检索
    """
    with get_session() as s:
        sess = s.get(ChatSession, session_id)
        if sess is None:
            sess = ChatSession(session_id=session_id)
            s.add(sess)
        if not sess.title:
            sess.title = _make_title(content)
        sess.mode = mode
        s.add(ChatMessage(session_id=session_id, role="user", content=content, mode=mode))
        _touch(sess, add_count=1)


def append_assistant_turn(
    session_id: str,
    content: str,
    *,
    mode: str = "agent",
    tool_calls: list[dict] | None = None,
    finish_reason: str = "done",
    elapsed: float | None = None,
    usage: dict | None = None,
    model: str | None = None,
) -> None:
    """写入/补全本轮的助手回答。

    为什么要「补全」：一轮对话可能被「等你确认」打断成两段流——第一段以 pending_confirm 收尾，
    用户点同意后 /chat/resume 接着跑完。这里让第二段直接改掉那条 pending_confirm 记录，
    而不是再插一条新的，否则一次提问会在页面上留下两条助手气泡。

    :param session_id: 会话 id
    :param content: 回答全文（被终止/出错时是已经流出来的那部分，可能是空串）
    :param mode: 本轮模式，"agent" 或 "rag"
    :param tool_calls: 本轮工具调用轨迹；没有则传 None
    :param finish_reason: 本轮结束原因，取值见 FINISH_REASONS
    :param elapsed: 本轮耗时（秒，含等待用户确认的时间）；未知时传 None
    :param usage: 本轮真实 token 用量（UX-5）；取不到时传 None（面板显示"—"而不是 0）
    :param model: 本轮使用的模型（provider/model），成本按它取单价
    """
    if finish_reason not in FINISH_REASONS:      # 拼错就落成 done，避免前端判不出状态
        finish_reason = "done"
    with get_session() as s:
        sess = s.get(ChatSession, session_id)
        if sess is None:
            # 会话行理应存在（用户提问时已建）；真丢了就补一条，宁可少个标题也不要整轮回答丢失
            sess = ChatSession(session_id=session_id, title="新对话")
            s.add(sess)

        last = s.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).first()

        if last is not None and last.role == "assistant" and last.finish_reason == "pending_confirm":
            # 上一段停在「等确认」：原地补全，条数不再 +1
            last.content = content
            last.tool_calls = tool_calls
            last.finish_reason = finish_reason
            last.elapsed = elapsed
            last.usage_json = usage
            last.model = model
            _touch(sess, add_count=0)
        else:
            s.add(ChatMessage(
                session_id=session_id,
                role="assistant",
                content=content,
                mode=mode,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                elapsed=elapsed,
                usage_json=usage,
                model=model,
            ))
            _touch(sess, add_count=1)


def list_sessions(
    limit: int = limits.DEFAULT_CHAT_SESSIONS,
    query: str | None = None,
    *,
    archived: bool = False,
) -> list[dict]:
    """按「置顶优先、然后最近活跃」倒序列出会话，供前端「最近会话」列表展示。

    排序（UX-4 收尾）：先按 pinned 倒序，再按 updated_at 倒序。
    为什么置顶要参与 SQL 排序而不是前端重新排：前端只在当前这一页数据里排，
    而 limit 是在 SQL 里截的——不在这里排，置顶的会话可能压根进不了这一页。

    搜索（UX-4）走 SQL 过滤而不是取回来再筛：
        - 标题 LIKE 或**该会话内任意消息正文** LIKE；
        - 用子查询而不是 JOIN，避免同一会话命中多条消息时出现重复行。
    为什么要"内容也能搜"：用户往往只记得聊过什么，不记得标题。

    :param limit: 最多返回多少个会话
    :param query: 搜索关键词；None/空串表示不过滤
    :param archived: True=只要归档的，False=只要未归档的（两个"箱子"分开看，不混在一起）
    :return: 会话字典列表，每项含会话 id、标题、消息条数、起止时间、置顶/归档标记与最后一条消息预览
    """
    # 非 HTTP 入口（导出、脚本）传进来的值也要落在合法区间内
    limit = limits.clamp_limit(limit, limits.MAX_CHAT_SESSIONS)
    keyword = (query or "").strip()
    with get_session() as s:
        stmt = (
            select(ChatSession)
            .where(ChatSession.archived.is_(bool(archived)))
            .order_by(
                # 布尔列在 SQLite 里存 0/1，desc() 就是"置顶的在前"
                ChatSession.pinned.desc(),
                ChatSession.updated_at.desc(),
                ChatSession.session_id.desc(),
            )
            .limit(limit)
        )
        if keyword:
            # 转义 LIKE 的通配符，避免用户输入 % 时把整库都匹配出来
            escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            matched_sessions = select(ChatMessage.session_id).where(
                ChatMessage.content.like(pattern, escape="\\")
            )
            stmt = stmt.where(
                or_(
                    ChatSession.title.like(pattern, escape="\\"),
                    ChatSession.session_id.in_(matched_sessions),
                )
            )
        rows = s.scalars(stmt).all()
        out: list[dict] = []
        for sess in rows:
            # 每个会话单独查一次最后一条消息（N+1 查询）：列表页 limit 很小（默认 20），可以接受
            last = s.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == sess.session_id)
                .order_by(ChatMessage.id.desc())
                .limit(1)
            ).first()
            out.append({
                "session_id": sess.session_id,
                "title": sess.title or "新对话",
                "mode": sess.mode,
                "message_count": sess.message_count or 0,
                # 置顶/归档标记跟着列表一起下发：前端据此把会话分进「置顶 / 最近 / 已归档」三组
                "pinned": bool(sess.pinned),
                "archived": bool(sess.archived),
                "created_at": _to_iso(sess.created_at),
                "updated_at": _to_iso(sess.updated_at),
                "preview": _make_preview(last.content) if last else "",
            })
        return out


def get_messages(session_id: str, limit: int = limits.DEFAULT_CHAT_HISTORY) -> list[dict]:
    """取某个会话的消息，按时间升序返回（最早的在前）。

    只关心消息列表的调用方（上下文补种等）用这个；需要知道「更早的还有没有」的
    用 :func:`get_messages_page`，需要「一条不漏」的（导出）用 :func:`get_all_messages`。

    :param session_id: 会话 id
    :param limit: 最多返回多少条
    :return: 消息字典列表，每项含 role / content / mode / tool_calls / finish_reason / elapsed / created_at
    """
    messages, _has_more = get_messages_page(session_id, limit=limit)
    return messages


def get_messages_page(session_id: str, limit: int = limits.DEFAULT_CHAT_HISTORY) -> tuple[list[dict], bool]:
    """取某个会话最近的 limit 条消息，并告知「更早的还有没有」。

    为什么多取一条：一次 SQL 就能同时得到「这一页」和「还有没有更早的」，
    不需要额外 COUNT。返回顺序仍是时间正序。

    :param session_id: 会话 id
    :param limit: 最多返回多少条（HTTP 入口由 Query(ge=1, le=MAX) 保证合法）
    :return: (消息字典列表, 是否还有更早的消息)
    """
    # 与 list_sessions 同理：非 HTTP 入口传进来的值也要夹到区间内
    limit = limits.clamp_limit(limit, limits.MAX_CHAT_HISTORY)
    with get_session() as s:
        rows = list(s.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            # 多取一条，只用来判断 has_more
            .limit(limit + 1)
        ).all())
    has_more = len(rows) > limit
    if has_more:
        # 丢掉的这条是最早的一条，属于「下一页」
        rows = rows[:limit]
    rows.reverse()      # 上面按 id 倒序取"最近 N 条"，这里翻回升序（= 时间顺序）
    return [_message_dict(m) for m in rows], has_more


def get_all_messages(session_id: str) -> list[dict]:
    """取某个会话的全部消息，按时间升序返回（不设窗口上限）。

    为什么单独开一个函数，而不是 `get_messages(limit=5000)`：
        分页函数会把 limit 夹到 MAX_CHAT_HISTORY（200）以内（见 app/core/limits.py 那张契约表），
        导出几千条消息的会话时会被悄悄截掉前半段，用户拿到的文档「看起来完整、其实少了内容」。
        这正是 docs/adr/0001-limit-越界一律报错.md 拒绝的「静默截断」——
        所以「全量语义」的调用方（导出、备份）走这里，不经过分页窗口。

    :param session_id: 会话 id
    :return: 消息字典列表，字段与 :func:`_message_dict` 一致
    """
    with get_session() as s:
        rows = list(s.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            # 按主键升序＝插入顺序＝时间顺序（与分页函数「倒序取最近 N 条再翻回来」等价）
            .order_by(ChatMessage.id.asc())
        ).all())
    return [_message_dict(m) for m in rows]


def _message_dict(m: ChatMessage) -> dict:
    """把一行消息实体转成接口返回的字典（字段名与前端 StoredChatMessage 对齐）。

    :param m: ChatMessage 实体
    :return: 单个消息字典
    """
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content or "",
        "mode": m.mode,
        "tool_calls": m.tool_calls,
        "finish_reason": m.finish_reason,
        "elapsed": m.elapsed,
        # UX-5：历史消息也带用量与模型，打开旧会话时面板能立刻算出累计
        "usage": m.usage_json,
        "model": m.model,
        "created_at": _to_iso(m.created_at),
    }


def has_messages(session_id: str) -> bool:
    """判断这个会话在数据库里有没有消息记录（用于决定要不要给模型补种上下文）。

    :param session_id: 会话 id
    :return: 至少有一条消息时为 True
    """
    with get_session() as s:
        return s.scalar(
            select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
        ) > 0


def get_model_messages(session_id: str, limit: int = limits.DEFAULT_RESEED_MESSAGES) -> list[dict]:
    """取出该会话的历史消息，拼成模型可以直接吃的 messages 列表（补种上下文用）。

    过滤规则：
        - 只要 user / assistant（其它角色不进对话）；
        - 丢掉正文为空白的记录（被终止或被确认打断时可能没来得及输出内容）；
        - 丢掉停在 pending_confirm 的助手记录（它只是一段半成品，补进上下文反而让模型困惑）。

    :param session_id: 会话 id
    :param limit: 最多补种多少条历史（太大的历史会挤占模型上下文，也会变慢）
    :return: [{"role": "user"|"assistant", "content": "..."}]，按时间升序
    """
    rows = get_messages(session_id, limit=limit)
    return [
        {"role": m["role"], "content": m["content"]}
        for m in rows
        if m["role"] in ("user", "assistant")
        and m["content"].strip()
        and m["finish_reason"] != "pending_confirm"
    ]


def delete_session(session_id: str) -> bool:
    """永久删除一个会话及其全部消息（前端「最近会话」列表里的删除按钮）。

    注意：这只删数据库记录，不碰 chat_controller 里的内存会话与 checkpointer。
    只清「当前上下文」的入口是 DELETE /chat/sessions/{id}，两者刻意分开。

    :param session_id: 会话 id
    :return: 是否真的删掉了一个会话（False 表示这个 id 本来就不存在）
    """
    with get_session() as s:
        sess = s.get(ChatSession, session_id)
        if sess is None:
            return False
        s.delete(sess)      # relationship 上配了 delete-orphan，消息会随之一起删除
        return True


def rename_session(session_id: str, title: str) -> bool:
    """重命名会话（UX-4）。标题为空时回落到「新对话」，避免列表里出现空白行。

    :param session_id: 会话 id
    :param title: 新标题（会被压成一行并截断到 TITLE_MAX_CHARS）
    :return: True=改成功；False=该会话不存在
    """
    clean = _make_title(title)
    with get_session() as s:
        # 用 Core UPDATE 而不是改 ORM 对象：改名不该算「活跃」，会话不该被顶到列表最前面。
        # 显式把 updated_at 赋成它自己（SQL 里是 updated_at = updated_at），
        # 这样这一列的微秒精度原样保留，不必依赖「有没有别的写入碰过它」。
        result = s.execute(
            update(ChatSession)
            .where(ChatSession.session_id == session_id)
            .values(title=clean, updated_at=ChatSession.updated_at)
        )
        return bool(result.rowcount)


def set_session_flags(
    session_id: str,
    *,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict | None:
    """设置会话的置顶 / 归档标记（UX-4 收尾）。

    两个参数都是"省略即不改"，所以同一个接口能表达四种操作：
        置顶 / 取消置顶 / 归档 / 取消归档（也可以一次同时改两项）。

    为什么用 Core UPDATE 而不是改 ORM 对象：改置顶这事**不该**把会话顶到「最近」列表最前面
    （置顶有自己的排序位）。这里显式把 updated_at 赋成它自己（SQL 里是 updated_at = updated_at），
    这一列因此原地不动，微秒精度也原样保留。

    :param session_id: 会话 id
    :param pinned: 是否置顶；None 表示不改
    :param archived: 是否归档；None 表示不改
    :return: {"pinned", "archived"}；会话不存在时返回 None
    """
    values: dict = {}
    if pinned is not None:
        values["pinned"] = bool(pinned)
    if archived is not None:
        values["archived"] = bool(archived)
    if not values:
        # 什么都没传：只查询当前状态，不写库（前端可以用它做"读标记"）
        with get_session() as s:
            sess = s.get(ChatSession, session_id)
            if sess is None:
                return None
            return {"pinned": bool(sess.pinned), "archived": bool(sess.archived)}

    values["updated_at"] = ChatSession.updated_at
    with get_session() as s:
        result = s.execute(
            update(ChatSession).where(ChatSession.session_id == session_id).values(**values)
        )
        if not result.rowcount:
            return None
        sess = s.get(ChatSession, session_id)
        if sess is None:
            return None
        # 让会话对象从库里重新读一次（Core UPDATE 之后 ORM 缓存里的值还是旧的）
        s.refresh(sess)
        return {"pinned": bool(sess.pinned), "archived": bool(sess.archived)}


def _safe_filename(text: str) -> str:
    """把会话标题变成可用作文件名的字符串（去掉 Windows 不允许的字符）。

    :param text: 会话标题
    :return: 只含中英文、数字、下划线、连字符的文件名主体；为空时返回 "chat"
    """
    cleaned = "".join(
        "_" if (ch in '\\/:*?"<>|' or ch.isspace()) else ch
        for ch in (text or "")
    )
    cleaned = cleaned.strip("._-")
    # 文件名主体的长度上限：太长的标题在资源管理器里根本看不全
    return cleaned[:40] or "chat"


def _fmt_export_time(iso: str | None) -> str:
    """把 ISO 时间字符串压成"YYYY-MM-DD HH:MM:SS（UTC）"，供导出的 Markdown 阅读。

    :param iso: 形如 "2026-10-21T10:05:00.123456" 的字符串
    :return: 可读时间；iso 为空时返回"—"
    """
    if not iso:
        return "—"
    # 只取到秒：导出的文档给人看，微秒没有意义
    return iso[:19].replace("T", " ") + "（UTC）"


def export_session(session_id: str, fmt: str = "md") -> dict | None:
    """把一个会话导出成 Markdown 或 JSON 文本（UX-4 收尾：单会话导出）。

    为什么由后端生成文本、而不是前端拿消息自己拼：
        消息里的工具轨迹、耗时、模型、finish_reason 只有后端知道怎么解释；
        前端拼容易漏字段，而且同一份导出逻辑放两处迟早会不一致。

    :param session_id: 会话 id
    :param fmt: "md"=Markdown 便于阅读 / "json"=结构化便于再加工
    :return: {"session_id","format","filename","content","message_count"}；
        会话不存在时返回 None
    """
    # 导出要「一条不漏」：走全量查询，不能用带 200 条窗口上限的分页函数
    messages = get_all_messages(session_id)
    with get_session() as s:
        sess = s.get(ChatSession, session_id)
        if sess is None:
            return None
        meta = {
            "session_id": sess.session_id,
            "title": sess.title or "新对话",
            "mode": sess.mode,
            "message_count": sess.message_count or 0,
            "pinned": bool(sess.pinned),
            "archived": bool(sess.archived),
            "created_at": _to_iso(sess.created_at),
            "updated_at": _to_iso(sess.updated_at),
        }

    # 时间戳后缀：同一个会话导出多次时不会互相覆盖
    stamp = _utcnow().strftime("%Y%m%d-%H%M")
    base = _safe_filename(meta["title"])

    if fmt == "json":
        return {
            "session_id": session_id,
            "format": "json",
            "filename": f"{base}-{stamp}.json",
            "content": json.dumps({"session": meta, "messages": messages},
                                  ensure_ascii=False, indent=2),
            "message_count": len(messages),
        }

    # ---- Markdown ----
    lines: list[str] = [
        f"# {meta['title']}",
        "",
        f"- 会话 ID：`{meta['session_id']}`",
        f"- 消息条数：{meta['message_count']}",
        f"- 创建时间：{_fmt_export_time(meta['created_at'])}",
        f"- 最后活跃：{_fmt_export_time(meta['updated_at'])}",
        f"- 导出时间：{_fmt_export_time(_utcnow().isoformat())}",
        "",
        "---",
        "",
    ]
    for msg in messages:
        who = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        head = f"## {who} · {_fmt_export_time(msg['created_at'])}"
        # 助手这一条的"这一轮是怎么结束的"对复盘最有价值，附在标题行后面
        if msg["role"] == "assistant":
            facts: list[str] = []
            if msg.get("model"):
                facts.append(f"模型 {msg['model']}")
            if msg.get("elapsed") is not None:
                facts.append(f"耗时 {msg['elapsed']:.1f}s")
            if msg.get("finish_reason") and msg["finish_reason"] != "done":
                facts.append(f"结束原因 {msg['finish_reason']}")
            if facts:
                head += "（" + "，".join(facts) + "）"
        lines.extend([head, "", msg["content"] or "（本轮没有输出内容）", ""])

        tools = msg.get("tool_calls") or []
        if tools:
            lines.append(f"<details><summary>工具调用（{len(tools)} 次）</summary>")
            lines.append("")
            for i, call in enumerate(tools, start=1):
                name = call.get("name") or "未知工具"
                # 输入/输出只留开头一段：导出文档是给人看的，不是给模型读的
                arg = str(call.get("input", ""))[:200].replace("\n", " ")
                out = str(call.get("output", ""))[:200].replace("\n", " ")
                lines.append(f"{i}. `{name}`")
                if arg:
                    lines.append(f"   - 输入：{arg}")
                if out:
                    lines.append(f"   - 输出：{out}")
            lines.extend(["", "</details>", ""])
        lines.extend(["---", ""])

    return {
        "session_id": session_id,
        "format": "md",
        "filename": f"{base}-{stamp}.md",
        "content": "\n".join(lines).rstrip() + "\n",
        "message_count": len(messages),
    }


def session_titles(session_ids: list[str]) -> dict[str, str]:
    """批量取会话标题（键=会话 id），给"别处引用了会话 id"的页面显示人话。

    目前的用处是轨迹回放页：轨迹表里只有 session_id（uuid），用户认不出来；
    一次把标题查回来换成「标题 + id 前 8 位」才好挑。用一次 IN 查询而不是逐个查，
    免得回放页列出 50 个会话就发 50 次数据库请求。

    :param session_ids: 会话 id 列表（可以有重复、可以有不存在的）
    :return: {session_id: 标题}；库里没有的 id 不会出现在结果里
    """
    ids = [sid for sid in dict.fromkeys(session_ids) if sid]
    if not ids:
        return {}
    with get_session() as s:
        rows = s.execute(
            select(ChatSession.session_id, ChatSession.title)
            .where(ChatSession.session_id.in_(ids))
        ).all()
    return {session_id: (title or "新对话") for session_id, title in rows}


def usage_rows(session_id: str) -> list[dict]:
    """取出该会话每个助手轮次的用量与模型，供成本聚合。

    为什么不在 SQL 里直接 SUM：不同轮次可能用不同模型，单价不同，
    必须先拿到 (model, tokens) 再按单价折算；这个折算逻辑放在 services/usage_service.py。

    :param session_id: 会话 id
    :return: [{"model": str|None, "usage": dict, "elapsed": float|None}]
    """
    with get_session() as s:
        rows = s.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.usage_json.isnot(None))
            .order_by(ChatMessage.id)
        ).all()
        # 再按 Python 真值过滤一层：JSON 列在部分 SQLite 版本里会把 None 存成字符串 'null'，
        # 只靠 SQL 的 IS NOT NULL 会漏进"没有用量"的行。
        return [
            {"model": row.model, "usage": row.usage_json, "elapsed": row.elapsed}
            for row in rows
            if row.usage_json
        ]
