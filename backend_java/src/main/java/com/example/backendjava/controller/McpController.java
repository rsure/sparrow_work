// 模块说明：MCP 管理接口，路径与 Python 侧 /api/mcp/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /mcp
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// MCP 业务接口：外部 MCP Server 接入与工具列举
import com.example.backendjava.service.McpService;

// 标准库：Map 用于动态快照
import java.util.Map;

/**
 * MCP 管理接口。
 *
 * <p>Python 侧这三个端点返回裸 JSON，这里保持兼容。</p>
 */
@RestController
@RequestMapping("/mcp")
public class McpController {

    /** MCP 服务；学习者实现后自动注入。 */
    private final ObjectProvider<McpService> mcpService;

    /**
     * 构造器注入可选 Service。
     *
     * @param mcpService Spring 的按类型查找器
     */
    public McpController(ObjectProvider<McpService> mcpService) {
        this.mcpService = mcpService;
    }

    /**
     * 列出 MCP server 状态。
     *
     * @return 状态快照
     */
    @GetMapping("/servers")
    public Map<String, Object> listServers() {
        return ServiceSupport.require(mcpService, "MCP 服务").snapshot();
    }

    /**
     * 重新连接全部 MCP server。
     *
     * @return 重载后的快照
     */
    @PostMapping("/reload")
    public Map<String, Object> reload() {
        return ServiceSupport.require(mcpService, "MCP 服务").reload();
    }

    /**
     * 试连一条 MCP server 配置。
     *
     * @param config 单条配置
     * @return 试连结果
     */
    @PostMapping("/test")
    public Map<String, Object> test(@RequestBody Map<String, Object> config) {
        return ServiceSupport.require(mcpService, "MCP 服务").test(config);
    }
}
