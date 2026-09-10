// 模块说明：RAG 索引元信息表的数据访问接口。
package com.example.backendjava.repository;

// 项目内：索引元信息实体
import com.example.backendjava.entity.RagIndexMeta;
// 第三方（Spring Data JPA）：通用 CRUD（主键类型是 String）
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * 索引元信息仓库：按 key 读写 model / dim 两项。
 */
public interface RagIndexMetaRepository extends JpaRepository<RagIndexMeta, String> {
}
