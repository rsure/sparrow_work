// 模块说明：健康检查接口，对应 Python 侧 GET /api/health。
package com.example.backendjava.controller;

// Spring Web 注解：声明 REST 控制器，返回值自动序列化成 JSON
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：把 GET /health 映射到本方法
import org.springframework.web.bind.annotation.GetMapping;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;

// 健康检查业务实现：采集进程与运行时快照
import com.example.backendjava.service.HealthService;
// 健康检查响应体
import com.example.backendjava.dto.HealthData;

/**
 * 健康检查接口。
 *
 * <p>最终访问路径为 {@code GET /api/health}：{@code /api} 来自
 * application.yml 的 server.servlet.context-path，本类只声明 {@code /health}。</p>
 */
@RestController
public class HealthController {

    /** 健康检查业务逻辑；由构造器注入，便于单元测试替换。 */
    private final HealthService healthService;

    /**
     * 构造器注入。
     *
     * @param healthService 健康检查服务
     */
    public HealthController(HealthService healthService) {
        this.healthService = healthService;
    }

    /**
     * 返回后端运行时健康快照。
     *
     * @return 统一响应壳；code=0 表示服务正常
     */
    @GetMapping("/health")
    public ApiResponse<HealthData> health() {
        // 直接返回服务层结果；异常由 GlobalExceptionHandler 统一处理
        return ApiResponse.ok(healthService.getHealth());
    }
}
