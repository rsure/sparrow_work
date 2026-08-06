-- documents 文档表
CREATE TABLE documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     VARCHAR(1024) NOT NULL,
    title      VARCHAR(512),
    doc_hash   VARCHAR(64)   NOT NULL,
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_documents_source UNIQUE (source)
);

-- chunks 切片表
CREATE TABLE chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       INTEGER NOT NULL,
    chunk_index  INTEGER NOT NULL,
    text         TEXT    NOT NULL,
    text_clean   TEXT    NOT NULL,
    char_len     INTEGER NOT NULL,
    truncated    BOOLEAN NOT NULL DEFAULT 0,
    content_hash VARCHAR(64) NOT NULL,
    embedding    BLOB,
    dim          INTEGER,
    model        VARCHAR(128),
    embedded_at  DATETIME,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chunks_doc FOREIGN KEY (doc_id)
        REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT uq_chunk_doc_index UNIQUE (doc_id, chunk_index)
);

CREATE INDEX idx_chunks_doc      ON chunks (doc_id);
CREATE INDEX idx_chunks_hash     ON chunks (content_hash);
CREATE INDEX idx_chunks_embedded ON chunks (embedded_at);
CREATE INDEX idx_chunks_model    ON chunks (model);

-- index_meta 索引元信息表
CREATE TABLE index_meta (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);
