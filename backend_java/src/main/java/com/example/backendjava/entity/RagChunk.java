// 模块说明：RAG 切片实体，对应 Python 侧 app/entity/models.py 的 Chunk。
// 一行代表文档切块后的一个片段：原文 + 清洗文本 + 向量 BLOB + 增量索引需要的指纹。
package com.example.backendjava.entity;

// 第三方（JPA）：列映射注解
import jakarta.persistence.Column;
// 第三方（JPA）：声明本类为实体
import jakarta.persistence.Entity;
// 第三方（JPA）：自增主键生成策略
import jakarta.persistence.GeneratedValue;
// 第三方（JPA）：主键生成策略枚举
import jakarta.persistence.GenerationType;
// 第三方（JPA）：主键注解
import jakarta.persistence.Id;
// 第三方（JPA）：表名注解
import jakarta.persistence.Table;
// 第三方（Lombok）：自动生成全部字段的 getter
import lombok.Getter;
// 第三方（Lombok）：自动生成全部字段的 setter
import lombok.Setter;

/**
 * RAG 文档的一个切片。
 *
 * <p>列名 {@code content} 沿用 Java 侧已有表结构，对应 Python 侧的 {@code text}；
 * 其余增量索引字段与 Python 保持一致，便于两个后端的行为逐项对照。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "rag_chunk")
public class RagChunk {

    /** 切片主键，自增；同时作为内存向量索引里的向量 id。 */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    /** 所属文档 id，关联 rag_document.id。 */
    @Column(name = "document_id", nullable = false)
    private Long documentId;

    /** 切片在文档内的顺序号（从 0 开始），同一文档内唯一。 */
    @Column(name = "chunk_index", nullable = false)
    private Integer chunkIndex = 0;

    /** 切片原文：检索结果直接展示给用户，不做截断。 */
    @Column(name = "content", nullable = false, length = Integer.MAX_VALUE)
    private String text;

    /** 清洗（去空白 + 截断）后的文本：向量化与内容指纹都基于它。 */
    // 以下新增列保持可空：老版本数据库已有数据时，Hibernate 的 ddl-auto=update 才能安全加列
    @Column(name = "text_clean", length = Integer.MAX_VALUE)
    private String textClean;

    /** 清洗后文本的字符数（单位：字符），用于统计与排查超长切片。 */
    @Column(name = "char_len")
    private Integer charLen = 0;

    /** 是否因超过 CHAR_LIMIT 被截断；true 表示向量只覆盖了切片前半段。 */
    @Column(name = "truncated")
    private Boolean truncated = false;

    /** 清洗后文本的 SHA-256：增量索引的 key，内容没变即可复用旧向量。 */
    @Column(name = "content_hash", length = 64)
    private String contentHash = "";

    /** 向量 BLOB（小端 float32）：长度 = 维度 × 4；未向量化时为 null。 */
    @Column(name = "embedding")
    private byte[] embedding;

    /** 向量维度（= 字节数 / 4）：用于识别换模型前写入的不兼容向量。 */
    @Column(name = "dim")
    private Integer dim;

    /** 生成该向量的模型标识；为空表示该切片尚未向量化。 */
    @Column(name = "model", length = 128)
    private String model;

    /** 向量生成时间（ISO-8601 字符串）；为空表示该切片尚未向量化。 */
    @Column(name = "embedded_at")
    private String embeddedAt;

    /** 切片行入库时间（ISO-8601 字符串），由服务层在插入时写入。 */
    @Column(name = "created_at")
    private String createdAt;
}
