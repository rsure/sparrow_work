// 模块说明：RAG 文档库业务接口。实现建议用 LangChain4j 的 DocumentSplitter + EmbeddingModel + EmbeddingStore。
package com.example.backendjava.service;

// 标准库：List 用于文档列表与检索结果
import java.util.List;
// 标准库：Map 用于形状简单的删除/重建结果
import java.util.Map;

// RAG 接口的请求/响应 DTO 容器
import com.example.backendjava.dto.RagDtos;

/**
 * RAG 服务接口。
 *
 * <p>注意：当前 Maven Central 上没有官方的 langchain4j-faiss 构件，
 * 因此本工程默认使用 LangChain4j 的 InMemoryEmbeddingStore 或自定义 EmbeddingStore。
 * 具体方案见 doc/java_langchan_doc/03-LangChain4j与LangGraph4j集成指南.md。</p>
 */
public interface RagService {

    /**
     * 按本地文件路径入库。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    RagDtos.IndexResult indexFile(RagDtos.IndexFileRequest request);

    /**
     * 按纯文本入库。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    RagDtos.IndexResult indexText(RagDtos.IndexTextRequest request);

    /**
     * 按来源删除全部文档。
     *
     * @param source 来源标识
     * @return 形如 {"deleted": source} 的结果
     */
    Map<String, Object> deleteBySource(String source);

    /**
     * 按文档 id 删除。
     *
     * @param docId 文档 id
     * @return 形如 {"deleted": docId} 的结果
     */
    Map<String, Object> deleteById(long docId);

    /**
     * 批量删除。
     *
     * @param ids 文档 id 列表
     * @return 形如 {"deleted": 实际删除条数} 的结果
     */
    Map<String, Object> batchDelete(List<Long> ids);

    /**
     * 查询文档详情。
     *
     * @param docId 文档 id
     * @return 文档详情；不存在时返回 null，由 Controller 转成 404
     */
    RagDtos.RagDocument getDocument(long docId);

    /**
     * 分页列出文档。
     *
     * @param limit  每页条数
     * @param offset 偏移量
     * @return 文档列表
     */
    List<RagDtos.RagDocument> listDocuments(int limit, int offset);

    /**
     * 向量检索。
     *
     * @param request 检索请求
     * @return 命中片段
     */
    List<RagDtos.SearchHit> search(RagDtos.SearchRequest request);

    /**
     * 从数据库全量重建向量索引（不重新向量化）。
     *
     * @return 形如 {"vectors": 条数} 的结果
     */
    Map<String, Object> rebuildIndex();
}
