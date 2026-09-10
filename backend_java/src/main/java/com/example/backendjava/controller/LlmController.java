// 模块说明：模型接入接口，对应 Python 侧 /api/llm/*。
package com.example.backendjava.controller;

// Spring Web 注解：声明 REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：声明本控制器的统一路径前缀 /llm
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：读取 JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;
// 模型业务接口：供应商清单、连通性测试与模型装配
import com.example.backendjava.llm.LlmService;
// 模型接口的供应商/模型/探测 DTO 容器
import com.example.backendjava.dto.LlmDtos;

// 标准库：List 用于供应商清单
import java.util.List;

/**
 * 模型接入接口。
 *
 * <p>最终路径为 {@code /api/llm/providers} 与 {@code /api/llm/probe}。</p>
 */
@RestController
@RequestMapping("/llm")
public class LlmController {

    /** 模型服务；默认实现已经完整可用。 */
    private final LlmService llmService;

    /**
     * 构造器注入。
     *
     * @param llmService 模型服务
     */
    public LlmController(LlmService llmService) {
        this.llmService = llmService;
    }

    /**
     * 列出全部供应商与模型。
     *
     * @return 统一响应壳，data 为供应商数组
     */
    @GetMapping("/providers")
    public ApiResponse<LlmDtos.ProvidersResult> providers() {
        return ApiResponse.ok(llmService.listProviders());
    }

    /**
     * 测试某个模型配置是否可用。
     *
     * @param request 测试参数
     * @return 统一响应壳，data 为测试结果
     */
    @PostMapping("/probe")
    public ApiResponse<LlmDtos.ProbeResult> probe(@RequestBody LlmDtos.ProbeRequest request) {
        return ApiResponse.ok(llmService.probe(request));
    }
}
