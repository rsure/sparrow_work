// 模块说明：审计查询接口，路径与 Python 侧 GET /api/audit 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /audit
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 审计业务接口：工具调用记录查询
import com.example.backendjava.service.AuditService;

// 标准库：List 用于审计记录列表
import java.util.List;
// 标准库：Map 用于动态记录结构
import java.util.Map;

/**
 * 审计查询接口。
 */
@RestController
@RequestMapping("/audit")
public class AuditController {

    /** 审计服务；学习者实现后自动注入。 */
    private final ObjectProvider<AuditService> auditService;

    /**
     * 构造器注入可选 Service。
     *
     * @param auditService Spring 的按类型查找器
     */
    public AuditController(ObjectProvider<AuditService> auditService) {
        this.auditService = auditService;
    }

    /**
     * 查询工具调用审计记录。
     *
     * @param sessionId 会话 id，可选
     * @param tool      工具名，可选
     * @param limit     最多返回多少条，默认 100
     * @return 审计记录列表
     */
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(
            @RequestParam(name = "session_id", required = false) String sessionId,
            @RequestParam(required = false) String tool,
            @RequestParam(defaultValue = "100") int limit
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(auditService, "审计服务").list(sessionId, tool, limit)
        );
    }
}
