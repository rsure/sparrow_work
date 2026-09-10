// 模块说明：RAG 索引元信息实体，对应 Python 侧 app/entity/models.py 的 IndexMeta。
// 键值表只记录两项：向量化模型名（model）与向量维度（dim）。
package com.example.backendjava.entity;

// 第三方（JPA）：列映射注解
import jakarta.persistence.Column;
// 第三方（JPA）：声明本类为实体
import jakarta.persistence.Entity;
// 第三方（JPA）：主键注解（本表主键是业务键，不是自增 id）
import jakarta.persistence.Id;
// 第三方（JPA）：表名注解
import jakarta.persistence.Table;
// 第三方（Lombok）：自动生成全部字段的 getter
import lombok.Getter;
// 第三方（Lombok）：自动生成全部字段的 setter
import lombok.Setter;

/**
 * 索引元信息：当前索引使用哪个向量化模型、向量维度是多少。
 *
 * <p>换模型/换维度后新旧向量不可比较，必须在入库时拦住并提示重建整个索引，
 * 这就是本表存在的唯一目的。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "rag_index_meta")
public class RagIndexMeta {

    /** 配置项名：目前只有 model（模型标识）与 dim（向量维度）。 */
    @Id
    @Column(name = "key", length = 64, nullable = false)
    private String key;

    /** 配置项取值：统一按文本存，dim 的数字也先转成字符串。 */
    @Column(name = "value", nullable = false, length = Integer.MAX_VALUE)
    private String value;
}
