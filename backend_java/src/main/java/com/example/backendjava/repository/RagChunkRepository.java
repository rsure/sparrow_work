// 模块说明：RAG 切片表的数据访问接口。
package com.example.backendjava.repository;

// 项目内：RAG 切片实体
import com.example.backendjava.entity.RagChunk;
// 第三方（Spring Data JPA）：通用 CRUD
import org.springframework.data.jpa.repository.JpaRepository;
// 第三方（Spring Data JPA）：声明批量更新/删除语句
import org.springframework.data.jpa.repository.Modifying;
// 第三方（Spring Data JPA）：自定义 JPQL 查询
import org.springframework.data.jpa.repository.Query;
// 第三方（Spring Data JPA）：把方法参数绑定到查询里的命名参数
import org.springframework.data.repository.query.Param;

// 标准库：Collection 用于批量 id 查询与删除
import java.util.Collection;
// 标准库：List 返回切片列表
import java.util.List;

/**
 * RAG 切片仓库。
 */
public interface RagChunkRepository extends JpaRepository<RagChunk, Long> {

    /**
     * 取某篇文档的全部切片，按切片序号升序。
     *
     * @param documentId 文档 id
     * @return 切片列表；没有切片时为空列表
     */
    List<RagChunk> findByDocumentIdOrderByChunkIndexAsc(Long documentId);

    /**
     * 取多篇文档的全部切片（批量删除前先记下 id，便于同步内存索引）。
     *
     * @param documentIds 文档 id 集合
     * @return 切片列表
     */
    List<RagChunk> findByDocumentIdIn(Collection<Long> documentIds);

    /**
     * 取所有已经向量化的切片（启动时重建内存索引用）。
     *
     * @return 有 embedding 的切片列表
     */
    List<RagChunk> findByEmbeddingIsNotNull();

    /**
     * 统计某篇文档的切片总数。
     *
     * @param documentId 文档 id
     * @return 切片条数
     */
    long countByDocumentId(Long documentId);

    /**
     * 统计某篇文档里已经向量化的切片数（排查「有切片但缺向量」用）。
     *
     * @param documentId 文档 id
     * @return 已向量化条数
     */
    long countByDocumentIdAndEmbeddingIsNotNull(Long documentId);

    /**
     * 删除某篇文档的全部切片（重新切分入库前调用）。
     *
     * @param documentId 文档 id
     */
    @Modifying
    @Query("DELETE FROM RagChunk c WHERE c.documentId = :documentId")
    void deleteByDocumentId(@Param("documentId") Long documentId);

    /**
     * 批量删除多篇文档的全部切片。
     *
     * @param documentIds 文档 id 集合
     */
    @Modifying
    @Query("DELETE FROM RagChunk c WHERE c.documentId IN :documentIds")
    void deleteByDocumentIdIn(@Param("documentIds") Collection<Long> documentIds);
}
