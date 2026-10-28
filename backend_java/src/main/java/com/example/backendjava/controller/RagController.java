// 模块说明：RAG 文档库接口，路径与 Python 侧 /api/rag/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /rag
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：DELETE 映射
import org.springframework.web.bind.annotation.DeleteMapping;
// Spring Web 注解：路径变量
import org.springframework.web.bind.annotation.PathVariable;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
// Spring Web 注解：JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// Jakarta 校验注解
import jakarta.validation.Valid;
// Jakarta 校验注解：limit 的下界（小于 1 直接 400）
import jakarta.validation.constraints.Min;
// Jakarta 校验注解：limit 的上界（超过上限直接 400）
import jakarta.validation.constraints.Max;
// Spring 校验开关：类上标了它，方法参数上的 @Min/@Max 才会被校验
import org.springframework.validation.annotation.Validated;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;
// 项目内：limit 的默认值与上限契约表（Python 侧镜像在 app/core/limits.py）
import com.example.backendjava.common.PageLimits;
// 项目内业务异常：资源不存在
import com.example.backendjava.common.ApiException;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// RAG 业务接口：文档入库、切块与检索
import com.example.backendjava.service.RagService;
// RAG 接口的请求/响应 DTO 容器
import com.example.backendjava.dto.RagDtos;

// 标准库：List 用于文档列表与检索结果
import java.util.List;
// 标准库：Map 用于删除/重建结果
import java.util.Map;

/**
 * RAG 文档库接口。
 */
@Validated
@RestController
@RequestMapping("/rag")
public class RagController {

    /** RAG 服务；学习者实现后自动注入。 */
    private final ObjectProvider<RagService> ragService;

    /**
     * 构造器注入可选 Service。
     *
     * @param ragService Spring 的按类型查找器
     */
    public RagController(ObjectProvider<RagService> ragService) {
        this.ragService = ragService;
    }

    /**
     * 按本地文件路径入库。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    @PostMapping("/documents")
    public ApiResponse<RagDtos.IndexResult> indexFile(
            @Valid @RequestBody RagDtos.IndexFileRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").indexFile(request));
    }

    /**
     * 按纯文本入库。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    @PostMapping("/documents/text")
    public ApiResponse<RagDtos.IndexResult> indexText(
            @Valid @RequestBody RagDtos.IndexTextRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").indexText(request));
    }

    /**
     * 按来源删除全部文档。
     *
     * @param source 来源标识
     * @return 删除结果
     */
    @DeleteMapping("/documents/by-source")
    public ApiResponse<Map<String, Object>> deleteBySource(@RequestParam String source) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").deleteBySource(source));
    }

    /**
     * 按文档 id 删除。
     *
     * @param docId 文档 id
     * @return 删除结果
     */
    @DeleteMapping("/documents/{docId}")
    public ApiResponse<Map<String, Object>> deleteById(@PathVariable long docId) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").deleteById(docId));
    }

    /**
     * 批量删除文档。
     *
     * @param request 含 id 列表的请求体
     * @return 删除结果
     */
    @PostMapping("/documents/batch-delete")
    public ApiResponse<Map<String, Object>> batchDelete(
            @RequestBody RagDtos.BatchDeleteRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").batchDelete(request.ids()));
    }

    /**
     * 查询文档详情。
     *
     * @param docId 文档 id
     * @return 文档详情
     */
    @GetMapping("/documents/{docId}")
    public ApiResponse<RagDtos.RagDocument> getDocument(@PathVariable long docId) {
        RagDtos.RagDocument document = ServiceSupport.require(ragService, "RAG 服务").getDocument(docId);
        // 服务层用 null 表示不存在；Controller 转成业务码 404
        if (document == null) {
            throw new ApiException(404, "document not found");
        }
        return ApiResponse.ok(document);
    }

    /**
     * 分页列出文档。
     *
     * @param limit  每页条数，默认 50
     * @param offset 偏移量，默认 0
     * @return 文档列表
     */
    @GetMapping("/documents")
    public ApiResponse<List<RagDtos.RagDocument>> listDocuments(
            @RequestParam(defaultValue = "" + PageLimits.DEFAULT_RAG_DOCS)
            // 以前这里是唯一没有上界的 limit（能一次拉全库），现在统一到契约表
            @Min(1) @Max(PageLimits.MAX_RAG_DOCS) int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").listDocuments(limit, offset));
    }

    /**
     * 向量检索。
     *
     * @param request 检索请求
     * @return 命中片段
     */
    @PostMapping("/search")
    public ApiResponse<List<RagDtos.SearchHit>> search(
            @Valid @RequestBody RagDtos.SearchRequest request
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(ragService, "RAG 服务").search(request.withDefaults())
        );
    }

    /**
     * 全量重建向量索引。
     *
     * @return 重建结果
     */
    @PostMapping("/index/rebuild")
    public ApiResponse<Map<String, Object>> rebuildIndex() {
        return ApiResponse.ok(ServiceSupport.require(ragService, "RAG 服务").rebuildIndex());
    }
}
