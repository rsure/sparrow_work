// 模块说明：RAG 文档库的请求/响应 DTO，对应 Python 侧 /api/rag/*。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;
// Jakarta 校验注解：字符串非空
import jakarta.validation.constraints.NotBlank;
// Jakarta 校验注解：数值范围
import jakarta.validation.constraints.Max;
// Jakarta 校验注解：数值范围
import jakarta.validation.constraints.Min;

// 标准库：List 用于批量 id 与检索限定
import java.util.List;

/**
 * RAG 域 DTO 集合。
 */
public final class RagDtos {

    /** 工具类禁止实例化。 */
    private RagDtos() {
    }

    /**
     * 按本地文件路径入库的请求体。
     *
     * @param path   待入库文件的本地路径
     * @param source 来源标识，用于归类与按来源删除；为空时由服务端推断
     * @param title  展示标题；为空时取文件名
     * @param force  true 表示忽略已有记录，强制重新解析并入库
     */
    public record IndexFileRequest(
            // 文件路径
            @NotBlank(message = "path 不能为空")
            String path,
            // 来源标识
            String source,
            // 标题
            String title,
            // 是否强制重新入库
            boolean force
    ) {
    }

    /**
     * 直接提交文本入库的请求体。
     *
     * @param source 来源标识
     * @param text   待入库正文
     * @param title  展示标题；为空时自动生成
     * @param force  是否强制重新入库
     */
    public record IndexTextRequest(
            // 来源标识
            @NotBlank(message = "source 不能为空")
            String source,
            // 正文
            @NotBlank(message = "text 不能为空")
            String text,
            // 标题
            String title,
            // 是否强制重新入库
            boolean force
    ) {
    }

    /**
     * 向量检索请求体。
     *
     * <p><b>为什么 topK 是 Integer 而不是 int：</b>与对话域的 doc_top_k 同一个坑——
     * 不传这个字段时 int 会被 Jackson 填成 0，0 又被 {@code @Min(1)} 判成越界，
     * 请求在进 controller 之前就 400 了，默认值根本没机会生效。
     * 用 Integer 时「没传」是 null（{@code @Min/@Max} 对 null 放行），
     * 「传了 0」仍然是 0 并照旧报 400（取舍见 docs/adr/0001）。</p>
     *
     * @param query          检索问题原文
     * @param topK           返回条数上限（1~100）；null=没传，取默认 10
     * @param scoreThreshold 相似度下限；null 表示不设阈值
     * @param docIds         限定检索的文档 id 列表；null 表示不限
     * @param sources        限定检索的来源列表；null 表示不限
     */
    public record SearchRequest(
            // 检索问题
            @NotBlank(message = "query 不能为空")
            String query,
            // 返回条数；null=没传（默认 10），显式越界仍报错
            @JsonProperty("top_k")
            @Min(value = 1, message = "top_k 最小为 1")
            @Max(value = 100, message = "top_k 最大为 100")
            Integer topK,
            // 相似度下限
            @JsonProperty("score_threshold") Double scoreThreshold,
            // 限定文档 id
            @JsonProperty("doc_ids") List<Long> docIds,
            // 限定来源
            List<String> sources
    ) {
        /**
         * 补齐 topK 默认值。
         *
         * <p>判断条件是 {@code == null} 而不是 {@code <= 0}：显式传 0 已经被
         * {@code @Min(1)} 拦在入口（400），不能在这里再悄悄改成默认值。</p>
         *
         * @return topK 非 null 的新请求对象（默认 10，与 Python 侧 rag_store_controller 的 10 一致）
         */
        public SearchRequest withDefaults() {
            return new SearchRequest(
                    query,
                    topK == null ? 10 : topK,
                    scoreThreshold,
                    docIds,
                    sources
            );
        }
    }

    /**
     * 批量删除文档的请求体。
     *
     * @param ids 待删除的文档 id 列表
     */
    public record BatchDeleteRequest(
            // 文档 id 列表
            List<Long> ids
    ) {
    }

    /**
     * 一次入库操作的结果。
     *
     * @param docId       文档主键
     * @param source      来源标识
     * @param action      动作：created / updated / skipped
     * @param totalChunks 该文档当前切片总数
     * @param newChunks   本次真正重新向量化的切片数
     */
    public record IndexResult(
            // 文档 id
            @JsonProperty("doc_id") long docId,
            // 来源
            String source,
            // 动作
            String action,
            // 切片总数
            @JsonProperty("total_chunks") int totalChunks,
            // 新增切片数
            @JsonProperty("new_chunks") int newChunks
    ) {
    }

    /**
     * 文档详情/列表项。
     *
     * @param id        文档 id
     * @param name      文件名（列表接口返回）
     * @param source    来源标识
     * @param title     标题
     * @param docHash   文档内容哈希，用于判断是否需要重新入库
     * @param chunks    切片总数
     * @param embedded  已向量化切片数；列表接口可能为 null
     * @param fileSize  源文件大小（字节）；列表接口可能为 null
     * @param createdAt 创建时间（ISO-8601）
     * @param updatedAt 更新时间（ISO-8601）
     */
    public record RagDocument(
            // 文档 id
            long id,
            // 文件名
            String name,
            // 来源
            String source,
            // 标题
            String title,
            // 内容哈希
            @JsonProperty("doc_hash") String docHash,
            // 切片总数
            long chunks,
            // 已向量化数
            Long embedded,
            // 文件大小
            @JsonProperty("file_size") Long fileSize,
            // 创建时间
            @JsonProperty("created_at") String createdAt,
            // 更新时间
            @JsonProperty("updated_at") String updatedAt
    ) {
    }

    /**
     * 一条检索命中。
     *
     * @param chunkId    切片 id
     * @param docId      所属文档 id
     * @param source     来源
     * @param title      标题
     * @param chunkIndex 切片在文档内的序号（从 0 开始）
     * @param text       切片原文
     * @param score      余弦相似度，越大越相似
     */
    public record SearchHit(
            // 切片 id
            @JsonProperty("chunk_id") long chunkId,
            // 文档 id
            @JsonProperty("doc_id") long docId,
            // 来源
            String source,
            // 标题
            String title,
            // 切片序号
            @JsonProperty("chunk_index") int chunkIndex,
            // 原文
            String text,
            // 相似度
            double score
    ) {
    }
}
