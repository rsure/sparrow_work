-- 模块说明：Java 后端的最小业务表结构。
-- 执行时机：Spring Boot 启动时由 spring.sql.init 自动执行；全部使用 IF NOT EXISTS，重复启动安全。
-- 设计原则：先覆盖 Python 侧最核心的实体（设置、会话、消息、审计、记忆、RAG 文档/分块），
--           后续需要新表时优先引入 Flyway/Liquibase，而不是继续堆 schema.sql。

-- 普通设置：键值对形式，value 存 JSON 字符串（数组/对象也序列化后存入）
CREATE TABLE IF NOT EXISTS app_settings (
    -- 设置键，格式固定为「组.键」，如 llm.provider
    key         TEXT PRIMARY KEY,
    -- 设置值；统一按 JSON 字符串保存，读取时由 Service 反序列化
    value       TEXT NOT NULL,
    -- 最近一次更新时间，ISO-8601 字符串
    updated_at  TEXT NOT NULL
);

-- 对话会话：一行代表一个会话，session_id 同时作为 LangGraph 的 threadId
CREATE TABLE IF NOT EXISTS chat_session (
    -- 会话唯一 id；前端生成或后端生成，同时用作检查点的 threadId
    id          TEXT PRIMARY KEY,
    -- 会话标题；默认取第一条用户消息的前若干字
    title       TEXT NOT NULL DEFAULT '',
    -- 创建时间，ISO-8601 字符串
    created_at  TEXT NOT NULL,
    -- 最近一次活动时间，用于“最近会话”排序
    updated_at  TEXT NOT NULL,
    -- 是否置顶：0=否，1=是
    pinned      INTEGER NOT NULL DEFAULT 0,
    -- 是否归档：0=否，1=是
    archived    INTEGER NOT NULL DEFAULT 0
);

-- 对话消息：一行代表一条用户/助手消息，用于历史回放与重启后补种上下文
CREATE TABLE IF NOT EXISTS chat_message (
    -- 自增主键
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 所属会话 id，关联 chat_session.id
    session_id  TEXT NOT NULL,
    -- 消息角色：user / assistant / system / tool
    role        TEXT NOT NULL,
    -- 消息正文；工具消息可能是 JSON 字符串
    content     TEXT NOT NULL,
    -- 消息创建时间，ISO-8601 字符串
    created_at  TEXT NOT NULL
);

-- 消息表按会话查询的索引：历史列表与上下文补种都按 session_id 过滤
CREATE INDEX IF NOT EXISTS idx_chat_message_session
    ON chat_message (session_id, id);

-- 工具调用审计：记录谁在什么时候调用了什么工具、结果如何
CREATE TABLE IF NOT EXISTS audit_log (
    -- 自增主键
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 会话 id；可为空（例如启动自检类操作）
    session_id  TEXT,
    -- 工具名，如 write_file / run_command
    tool        TEXT NOT NULL,
    -- 工具入参的 JSON 字符串（敏感内容由业务层脱敏）
    arguments   TEXT NOT NULL DEFAULT '{}',
    -- 是否成功：0=失败，1=成功
    success     INTEGER NOT NULL DEFAULT 0,
    -- 结果摘要或错误信息
    result      TEXT NOT NULL DEFAULT '',
    -- 记录时间，ISO-8601 字符串
    created_at  TEXT NOT NULL
);

-- 工作空间记忆：长期保存的偏好/事实，供检索与提示词注入
CREATE TABLE IF NOT EXISTS memory_item (
    -- 记忆唯一 id（Java 侧用 UUID 字符串）
    id          TEXT PRIMARY KEY,
    -- 所属工作区 id；不同工作区的记忆互相隔离
    workspace_id TEXT NOT NULL,
    -- 来源会话 id（溯源用，可为空）
    session_id  TEXT,
    -- 记忆正文
    content     TEXT NOT NULL,
    -- 分类：preference / decision / fact / todo
    category    TEXT NOT NULL DEFAULT 'fact',
    -- 重要度 1~5
    importance  INTEGER DEFAULT 3,
    -- 来源：auto / manual
    source      TEXT DEFAULT 'auto',
    -- 正文 SHA-256：完全相同直接判重
    content_hash TEXT,
    -- 向量（float32 小端 BLOB）
    embedding   BLOB,
    -- 向量维度
    dim         INTEGER,
    -- 创建时间，ISO-8601 字符串
    created_at  TEXT NOT NULL,
    -- 最近更新时间，ISO-8601 字符串
    updated_at  TEXT,
    -- 最近一次被检索命中的时间，ISO-8601 字符串
    last_used_at TEXT,
    -- 被检索命中的累计次数
    use_count   INTEGER DEFAULT 0,
    -- 被合并进来的次数
    merged_count INTEGER DEFAULT 0
);

-- RAG 文档：一行代表一篇已入库的文档（字段与 Python 侧 documents 表对齐）
CREATE TABLE IF NOT EXISTS rag_document (
    -- 自增主键；前端删除/检索时使用的 doc_id
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 来源标识（默认是文件绝对路径），同一 source 再次入库视为更新
    source      TEXT NOT NULL DEFAULT '',
    -- 文档标题（展示用）
    title       TEXT NOT NULL DEFAULT '',
    -- 原始文件路径；纯文本入库时为空
    path        TEXT NOT NULL DEFAULT '',
    -- 整篇内容的 SHA-256：相同即可整篇跳过
    doc_hash    TEXT NOT NULL DEFAULT '',
    -- 入库时间，ISO-8601 字符串
    created_at  TEXT NOT NULL,
    -- 最近更新时间，ISO-8601 字符串
    updated_at  TEXT NOT NULL DEFAULT ''
);

-- RAG 分块：一行代表文档切块后的一个片段（字段与 Python 侧 chunks 表对齐）
CREATE TABLE IF NOT EXISTS rag_chunk (
    -- 自增主键；同时作为内存向量索引里的向量 id
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 所属文档 id，关联 rag_document.id
    document_id  INTEGER NOT NULL,
    -- 片段序号，从 0 开始
    chunk_index  INTEGER NOT NULL DEFAULT 0,
    -- 片段原文（对应 Python 侧的 text）
    content      TEXT NOT NULL,
    -- 清洗（去空白 + 截断）后的文本：向量化与内容指纹都基于它
    text_clean   TEXT NOT NULL DEFAULT '',
    -- 清洗后文本的字符数
    char_len     INTEGER NOT NULL DEFAULT 0,
    -- 是否因超过长度上限被截断
    truncated    BOOLEAN NOT NULL DEFAULT 0,
    -- 清洗后文本的 SHA-256：增量复用的 key
    content_hash TEXT NOT NULL DEFAULT '',
    -- 向量数据：小端 float32 的 BLOB；未向量化时为空
    embedding    BLOB,
    -- 向量维度（= 字节数 / 4）
    dim          INTEGER,
    -- 生成该向量的模型标识
    model        TEXT,
    -- 向量生成时间，ISO-8601 字符串
    embedded_at  TEXT,
    -- 切片行入库时间，ISO-8601 字符串
    created_at   TEXT NOT NULL DEFAULT ''
);

-- 分块表按文档查询的索引：删除文档与重建索引时需要
CREATE INDEX IF NOT EXISTS idx_rag_chunk_document
    ON rag_chunk (document_id, chunk_index);

-- 注意：content_hash 等增量索引字段由 Hibernate 的 ddl-auto=update 在启动时补齐。
-- 不能在这里直接对 content_hash 建索引：老版本数据库的 rag_chunk 表还没有该列，
-- SQL 初始化脚本会先于 Hibernate 的加列动作执行，从而报 "no such column"。

-- RAG 索引元信息：记录当前向量化模型与维度，换模型/维度必须重建索引
CREATE TABLE IF NOT EXISTS rag_index_meta (
    -- 配置项名：model / dim
    key   TEXT PRIMARY KEY,
    -- 配置项取值
    value TEXT NOT NULL
);

-- 执行轨迹：记录每一轮 Agent 的事件，用于回放与排查
CREATE TABLE IF NOT EXISTS trace_event (
    -- 自增主键
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 会话 id
    session_id  TEXT NOT NULL,
    -- 轮次 id；同一轮的事件共享该值
    turn_id     TEXT NOT NULL,
    -- 事件类型：token / tool_start / tool_end / confirm_required / done / error 等
    type        TEXT NOT NULL,
    -- 事件负载的 JSON 字符串
    payload     TEXT NOT NULL DEFAULT '{}',
    -- 事件时间，ISO-8601 字符串
    created_at  TEXT NOT NULL
);

-- 轨迹表按会话/轮次查询的索引
CREATE INDEX IF NOT EXISTS idx_trace_event_session
    ON trace_event (session_id, turn_id, id);

-- 工作区：一行一个「AI 可以读写的根目录集合」。
-- 为什么独立成表：Python 版本把工作区放在设置的一行 JSON 里，
-- 一旦要为工作区挂会话、记忆、任务等关联数据，就会缺少稳定的外键可指向。
CREATE TABLE IF NOT EXISTS workspace (
    -- 工作区 id：w-1 / w-2 递增；默认工作区固定为 w-default
    id          TEXT PRIMARY KEY,
    -- 工作区名称，展示在设置页
    name        TEXT NOT NULL,
    -- 根目录绝对路径的 JSON 数组字符串，例如 ["D:/work/a","D:/work/b"]
    roots       TEXT NOT NULL DEFAULT '[]'
);

-- 文件扫描任务：一行代表一次目录扫描（对应 Python 侧 task_info 表）
CREATE TABLE IF NOT EXISTS task_info (
    -- 任务唯一 id（uuid 的 hex 形式）
    task_id     TEXT PRIMARY KEY,
    -- 扫描根目录的绝对路径
    path        TEXT NOT NULL,
    -- pending / running / done / cancelled / failed
    status      TEXT NOT NULL DEFAULT 'pending',
    -- 成功读取到的文件数
    scanned     INTEGER NOT NULL DEFAULT 0,
    -- 已扫文件的字节数合计
    total_bytes INTEGER NOT NULL DEFAULT 0,
    -- 被跳过的文件/目录数量
    skipped     INTEGER NOT NULL DEFAULT 0,
    -- 失败原因（仅 failed 时有值）
    error       TEXT,
    -- 任务记录入库时间，ISO-8601 字符串
    created_at  TEXT NOT NULL,
    -- 扫描线程真正开始的时刻；未开始为 null
    started_at  TEXT,
    -- 扫描结束（完成/取消/失败）的时刻；未结束为 null
    ended_at    TEXT,
    -- 完成后的完整结果 JSON（ScanResult.to_json 形状）
    result_json TEXT,
    -- 扫描到的全部文件明细 JSON（FileInfo.to_dict 列表）
    files_json  TEXT
);
