// 模块说明：文件预览接口，路径与 Python 侧 /api/file/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// 响应实体：/file/raw 需要同时返回字节与 Content-Type
import org.springframework.http.ResponseEntity;
// 媒体类型：解析文件 MIME
import org.springframework.http.MediaType;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /file
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
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
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 文件业务接口：文件预览与权限校验
import com.example.backendjava.service.FileService;
// 文件接口的 DTO 容器
import com.example.backendjava.dto.FileDtos;

// 标准库：List 用于批量路径与搜索结果
import java.util.List;
// 标准库：Map 用于动态预览结果
import java.util.Map;

/**
 * 文件预览接口。
 */
@Validated
@RestController
@RequestMapping("/file")
public class FileController {

    /** 文件服务；学习者实现后自动注入。 */
    private final ObjectProvider<FileService> fileService;

    /**
     * 构造器注入可选 Service。
     *
     * @param fileService Spring 的按类型查找器
     */
    public FileController(ObjectProvider<FileService> fileService) {
        this.fileService = fileService;
    }

    /**
     * 批量获取文件清单。
     *
     * @param paths 文件绝对路径，可重复传多个 paths 参数
     * @return 文件清单
     */
    @GetMapping("/catalog")
    public ApiResponse<List<Map<String, Object>>> catalog(@RequestParam("paths") List<String> paths) {
        return ApiResponse.ok(ServiceSupport.require(fileService, "文件服务").catalog(paths));
    }

    /**
     * 读取文本预览。
     *
     * @param path     文件绝对路径
     * @param maxChars 最多返回多少字符，默认 200000
     * @return 预览结果
     */
    @GetMapping("/preview")
    public ApiResponse<Map<String, Object>> preview(
            @RequestParam String path,
            @RequestParam(name = "max_chars", defaultValue = "200000") int maxChars
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(fileService, "文件服务").preview(path, maxChars)
        );
    }

    /**
     * 在当前工作区内按文件名搜索。
     *
     * @param query 搜索关键词，默认空
     * @param limit 最多返回多少条，默认 20
     * @return 搜索结果
     */
    @GetMapping("/search")
    public ApiResponse<Map<String, Object>> search(
            @RequestParam(name = "q", defaultValue = "") String query,
            @RequestParam(defaultValue = "" + PageLimits.DEFAULT_FILE_SEARCH)
            // 候选是给人选的，超过 50 条也没人往下翻 → 越界报 400
            @Min(1) @Max(PageLimits.MAX_FILE_SEARCH) int limit
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(fileService, "文件服务").search(query, limit)
        );
    }

    /**
     * 原样返回文件内容。
     *
     * @param path 文件绝对路径
     * @return 文件字节；Content-Type 由服务层给出
     */
    @GetMapping("/raw")
    public ResponseEntity<byte[]> raw(@RequestParam String path) {
        FileDtos.RawFile rawFile = ServiceSupport.require(fileService, "文件服务").raw(path);
        // MIME 类型可能为空：回退到二进制流，避免 MediaType.parseMediaType 抛异常
        MediaType mediaType = (rawFile.contentType() == null || rawFile.contentType().isBlank())
                ? MediaType.APPLICATION_OCTET_STREAM
                : MediaType.parseMediaType(rawFile.contentType());
        return ResponseEntity.ok()
                .contentType(mediaType)
                .body(rawFile.content());
    }
}
