# app/entity/chat_record.py
"""对话记录实体：chat_session（一次会话）与 chat_message（一条消息），每轮对话都落到 SQLite。

为什么要持久化：
    chat_controller 里的 _SESSIONS 和 LangGraph 的 checkpointer 都只活在内存里，
    后端一重启（或会话空闲超过 1 小时被清理）用户就再也看不到之前聊过什么。
    这两张表把「用户看得见的东西」单独存一份——提问、回答、工具轨迹、这一轮是怎么结束的；
    模型内部状态依然只在 checkpointer 里，两边互不干扰。

为什么拆两张表：
    - chat_session 一条 = 一次会话，前端「最近会话」列表直接读它（标题、条数、最后活跃时间）；
    - chat_message 一条 = 一条可见消息，通过 session_id 外键挂在会话下，删会话时级联删消息。

写入时机见 app/services/chat_history_service.py，调用方是 app/controllers/chat_controller.py。
"""

# 让类型注解延迟求值（PEP 563），便于直接用 X | None、list[...] 这类新语法
from __future__ import annotations

# 时间列类型：两个表的 created_at / updated_at 都用它
from datetime import datetime

# SQLAlchemy 构件：列类型（Boolean/DateTime/Float/Integer/JSON/String/Text）、
# 外键 ForeignKey、索引 Index 与 SQL 函数 func（CURRENT_TIMESTAMP 作列默认值）
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
# ORM 映射构件：Mapped 标注列类型、mapped_column 声明列、relationship 声明一对多关联
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 项目内：本文件的两个实体都挂在全局声明式基类 Base 上，
# 这样 app/db/db_config.py 的 init_db() 一次 create_all 就能把表建出来
from app.db.db_config import Base


class ChatSession(Base):
    """一次会话（一条 = 用户从「新建对话」开始、到换下一个会话为止的一串消息）。"""

    # 物理表名：会话级元信息（标题、消息条数、起止时间）
    __tablename__ = "chat_session"

    # 会话主键：直接复用 chat_controller 生成的会话 id，它同时也是 LangGraph 的 thread_id，
    # 三处（内存会话表 / checkpointer / 本表）用同一个值才能互相对上
    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 会话标题（最长 200 字符，可为空串）：取第一条用户提问的前 30 个字符，供列表展示
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # 本会话最近一次用的对话模式："agent"=工具 Agent 链路，"doc"=`\doc` 知识库指令链路
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    # 已落库的消息条数（用户 + 助手各算一条），列表页直接展示，不用再 count 一次
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 是否置顶（UX-4 收尾）：置顶的会话永远排在「最近会话」列表最前面，
    # 否则列表按 updated_at 倒序，常用的长会话聊几次就被新会话挤下去了
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 是否归档（UX-4 收尾）：归档 = 收进"档案箱"，默认不在列表里出现，
    # 但一条都不删（导出、搜索时仍可找到），给用户"暂不打扰"的中间态
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 首次创建时间；由数据库默认值 CURRENT_TIMESTAMP 填写（UTC）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    # 最近一次写入消息的时间（UTC）：由服务层显式赋值（带微秒，排序比 CURRENT_TIMESTAMP 更准），
    # 「最近会话」列表按它倒序。
    #
    # 这里刻意**不加** onupdate=func.current_timestamp()：SQLite 的 CURRENT_TIMESTAMP 只精确到秒，
    # 而它一旦触发，就会把服务层写进来的微秒值截断成整秒——排序立刻出错。
    # 触发条件并不罕见：同一秒内（更准确地说，同一个系统时钟节拍内）两次 _touch 会算出完全相同的
    # 微秒值，SQLAlchemy 认为该列没变就不放进 UPDATE 的 SET，于是 onupdate 接手，写进 CURRENT_TIMESTAMP。
    # 结果就是「更晚活跃的会话」排到了「更早的会话」后面（测试 test_ux_polish 里那条断言会假失败）。
    # 兜底交给服务层：改会话行的地方都显式赋值（rename / set_session_flags 用 Core UPDATE 显式回写自身）。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=func.current_timestamp(),
    )

    # 一对多关联：ChatSession.messages 取到本会话全部消息并按 id 升序（= 时间顺序）；
    # cascade="all, delete-orphan" 表示删除会话时自动删掉它的消息
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )

    def __repr__(self) -> str:
        """调试/日志用的一行表示：只带会话 id、标题与消息条数，避免把正文打出来。"""
        return f"<ChatSession {self.session_id} title={self.title!r} msgs={self.message_count}>"


class ChatMessage(Base):
    """一条可见消息（用户提问，或助手的一次回答）。"""

    # 物理表名：会话消息正文与元信息
    __tablename__ = "chat_message"
    # 表级索引：按会话查消息（打开旧会话、补种上下文）是最频繁的查询，给 session_id 建索引
    __table_args__ = (Index("idx_chat_message_session", "session_id"),)

    # 消息主键，自增：既是唯一标识，也用作「同一会话内的先后顺序」（越大越新）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 所属会话 id，外键指向 chat_session.session_id；会话被删时数据库层 CASCADE 一并删掉消息
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_session.session_id", ondelete="CASCADE"), nullable=False
    )
    # 说话人："user"=用户提问，"assistant"=助手回答
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 消息正文；助手被终止 / 报错时可能是空串（这一轮确实什么字都没来得及输出）
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 这条消息属于哪种对话模式："agent"=工具 Agent，"doc"=`\doc` 知识库指令
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    # 本轮助手调用过的工具轨迹（原样存 chat_controller 里那份 list[dict]）；
    # 用户提问这一条恒为 None。用 JSON 列是因为轨迹结构由各工具自定义，不适合拆成固定列
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 这一轮是怎么结束的："done"=正常答完，"stopped"=用户点了终止，
    # "error"=出错，"pending_confirm"=停在"等用户确认"处（用户确认后会就地补全这一条）
    finish_reason: Mapped[str] = mapped_column(String(20), nullable=False, default="done")
    # 本轮耗时（单位：秒，含等待用户确认的时间）；用户提问这一条恒为 None
    elapsed: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 本轮真实 token 用量（OPS-6 / UX-5）：形如 {"input_tokens":120,"output_tokens":340,"total_tokens":460}。
    # 存在消息行上而不是会话行上，是因为同一会话里可能换过模型，成本要按"当时那个模型"的单价算。
    # none_as_null=True：Python None 存成 SQL NULL（而不是字符串 'null'），
    # 这样"有没有用量"可以直接用 IS NULL / IS NOT NULL 判断
    usage_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    # 本轮实际使用的模型（provider/model）：与 usage_json 配套，历史回放与成本聚合都读它
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 入库时间，由数据库默认值 CURRENT_TIMESTAMP 填写（UTC）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # 多对一关联：反向指回所属会话（与 ChatSession.messages 通过 back_populates 配对）
    session: Mapped["ChatSession"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        """调试用的一行表示：主键、所属会话、角色与结束原因；正文只给长度，避免刷屏。"""
        return (
            f"<ChatMessage id={self.id} session={self.session_id} role={self.role} "
            f"finish={self.finish_reason} len={len(self.content or '')}>"
        )
