// 模块说明：RAG 文档表的数据访问接口。
package com.example.backendjava.repository;

// 项目内：RAG 文档实体
import com.example.backendjava.entity.RagDocument;
// 第三方（Spring Data JPA）：通用 CRUD 与分页能力
import org.springframework.data.jpa.repository.JpaRepository;
// 第三方（Spring Data JPA）：自定义 JPQL/原生 SQL 查询
import org.springframework.data.jpa.repository.Query;
// 第三方（Spring Data JPA）：把方法参数绑定到查询里的命名参数
import org.springframework.data.repository.query.Param;

// 标准库：Optional 表达「按 source 最多查到一篇」
import java.util.Optional;
// 标准库：List 返回分页结果
import java.util.List;

/**
 * RAG 文档仓库。
 */
public interface RagDocumentRepository extends JpaRepository<RagDocument, Long> {

    /**
     * 按唯一来源标识查找文档。
     *
     * @param source 来源标识（文件绝对路径 / URL / 业务主键）
     * @return 找到时返回文档，否则为空
     */
    Optional<RagDocument> findBySource(String source);

    /**
     * 按 id 倒序分页（最新导入的在前）。
     *
     * <p>用原生 SQL 是因为接口的 {@code limit/offset} 语义允许非页对齐的偏移量，
     * Spring Data 的 PageRequest 只能表达「第几页」。表名与列名都是本项目固定值，
     * 不存在拼接用户输入的风险。</p>
     *
     * @param limit  本次最多返回多少条
     * @param offset 跳过前面多少条
     * @return 文档列表
     */
    @Query(value = "SELECT * FROM rag_document ORDER BY id DESC LIMIT :limit OFFSET :offset",
            nativeQuery = true)
    List<RagDocument> pageNewest(@Param("limit") int limit, @Param("offset") int offset);
}
