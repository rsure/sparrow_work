// 模块说明：RAG 文档实体，对应 Python 侧 app/entity/models.py 的 Document。
// 一行代表一篇已入库的文档；source 是唯一标识，同一 source 再次入库视为「更新」。
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
 * RAG 文档元信息。
 *
 * <p>与 Python 侧的差异：Java 侧表名沿用已有的 {@code rag_document}，并把原始文件路径
 * 单独存进 {@code path} 列（纯文本入库时为空串），便于前端展示与排查。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "rag_document")
public class RagDocument {

    /** 文档主键，自增；前端删除/检索时使用的 doc_id。 */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    /** 文档唯一来源标识：默认是文件绝对路径，也可以是 URL / 业务主键（最长 1024 字符）。 */
    @Column(name = "source", nullable = false, length = 1024)
    private String source = "";

    /** 文档标题：仅用于列表展示；为空时由服务层取文件名。 */
    @Column(name = "title", nullable = false, length = 512)
    private String title = "";

    /** 原始文件绝对路径；纯文本入库时为空串（对应 Python 侧没有单独路径列的差异）。 */
    @Column(name = "path", nullable = false, length = 1024)
    private String path = "";

    /** 整篇文档内容的 SHA-256（64 位十六进制）：相同即可整篇跳过解析与切分。 */
    // 新加列保持可空：老版本数据库里已存在行时，Hibernate 的 ddl-auto=update 才能安全加列
    @Column(name = "doc_hash", length = 64)
    private String docHash = "";

    /** 入库时间（ISO-8601 字符串）：第一次写入时生成。 */
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    /** 最近更新时间（ISO-8601 字符串）：每次重新入库时刷新。 */
    // 同上：新加列保持可空，避免老库加列失败
    @Column(name = "updated_at")
    private String updatedAt;
}
