package com.example.backendjava.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

/**
 * 工作区记忆实体（对应 Python 侧 {@code entity/memory.py} 的 Memory）。
 *
 * <p>向量与内容哈希都是可重算的派生字段：SQLite 是唯一真相源，换向量化方式后
 * 跑一次 reindex 即可全部重算。id 用 UUID 字符串（Java 侧约定），
 * 与 Python 的自增整数不同。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "memory_item")
public class MemoryItem {

    /** 记忆唯一 id（Java 侧用 UUID 字符串）。 */
    @Id
    @Column(name = "id", nullable = false, length = Integer.MAX_VALUE)
    private String id;

    /** 所属工作区 id；不同工作区的记忆互相隔离。 */
    @Column(name = "workspace_id", nullable = false, length = Integer.MAX_VALUE)
    private String workspaceId;

    /** 来源会话 id（溯源用，可为空）。 */
    @Column(name = "session_id", length = Integer.MAX_VALUE)
    private String sessionId;

    /** 记忆正文。 */
    @Column(name = "content", nullable = false, length = Integer.MAX_VALUE)
    private String content;

    /** 分类：preference / decision / fact / todo。 */
    @Column(name = "category", nullable = false, length = Integer.MAX_VALUE)
    private String category = "fact";

    /** 重要度 1~5。 */
    @Column(name = "importance")
    private Integer importance = 3;

    /** 来源：auto / manual。 */
    @Column(name = "source", length = Integer.MAX_VALUE)
    private String source = "auto";

    /** 正文 SHA-256：完全相同的内容直接判重。 */
    @Column(name = "content_hash", length = Integer.MAX_VALUE)
    private String contentHash;

    /** 向量（float32 小端 BLOB）。 */
    @Column(name = "embedding")
    private byte[] embedding;

    /** 向量维度（过滤「换过向量化方式」的旧向量）。 */
    @Column(name = "dim")
    private Integer dim;

    /** 创建时间，ISO-8601 字符串。 */
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    /** 最近一次修改时间。 */
    @Column(name = "updated_at")
    private String updatedAt;

    /** 最近一次被检索命中的时间。 */
    @Column(name = "last_used_at")
    private String lastUsedAt;

    /** 被检索命中的累计次数。 */
    @Column(name = "use_count")
    private Integer useCount = 0;

    /** 被合并进来的次数。 */
    @Column(name = "merged_count")
    private Integer mergedCount = 0;
}
