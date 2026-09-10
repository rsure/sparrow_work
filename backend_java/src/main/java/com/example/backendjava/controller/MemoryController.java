// 模块说明：工作区记忆接口，路径与 Python 侧 /api/memory/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /memory
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
// Spring MVC 的 SSE 发射器
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 记忆业务接口：工作区长期记忆的读写
import com.example.backendjava.service.MemoryService;
// 记忆接口的请求/响应 DTO 容器
import com.example.backendjava.dto.MemoryDtos;

// 标准库：Map 用于动态返回结构
import java.util.Map;

/**
 * 工作区记忆接口。
 *
 * <p>Python 侧这些端点返回裸 JSON（不套 ApiResponse），这里保持兼容。</p>
 */
@RestController
@RequestMapping("/memory")
public class MemoryController {

    /** 记忆服务；学习者实现后自动注入。 */
    private final ObjectProvider<MemoryService> memoryService;

    /**
     * 构造器注入可选 Service。
     *
     * @param memoryService Spring 的按类型查找器
     */
    public MemoryController(ObjectProvider<MemoryService> memoryService) {
        this.memoryService = memoryService;
    }

    /**
     * 列出当前工作区的记忆。
     *
     * @param workspaceId 工作区 id，可选
     * @param category    分类，可选
     * @param limit       最多返回条数，默认 100
     * @return 记忆列表
     */
    @GetMapping
    public Map<String, Object> list(
            @RequestParam(name = "workspace_id", required = false) String workspaceId,
            @RequestParam(required = false) String category,
            @RequestParam(defaultValue = "100") int limit
    ) {
        return ServiceSupport.require(memoryService, "记忆服务").list(workspaceId, category, limit);
    }

    /**
     * 返回记忆统计。
     *
     * @param workspaceId 工作区 id，可选
     * @return 统计结果
     */
    @GetMapping("/stats")
    public Map<String, Object> stats(
            @RequestParam(name = "workspace_id", required = false) String workspaceId
    ) {
        return ServiceSupport.require(memoryService, "记忆服务").stats(workspaceId);
    }

    /**
     * 本地相似度检索。
     *
     * @param request 检索请求
     * @return 命中结果
     */
    @PostMapping("/search")
    public Map<String, Object> search(@Valid @RequestBody MemoryDtos.MemorySearchRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").search(request);
    }

    /**
     * 检索记忆并用大模型回答（SSE）。
     *
     * @param request 检索请求
     * @return SSE 流
     */
    @PostMapping("/query")
    public SseEmitter query(@Valid @RequestBody MemoryDtos.MemorySearchRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").query(request);
    }

    /**
     * 手动新增一条记忆。
     *
     * @param request 新增请求
     * @return 新增后的记忆
     */
    @PostMapping
    public Map<String, Object> create(@Valid @RequestBody MemoryDtos.MemoryCreateRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").create(request.withDefaults());
    }

    /**
     * 删除一条记忆。
     *
     * @param memoryId 记忆 id
     * @return 删除结果
     */
    @DeleteMapping("/{memoryId}")
    public Map<String, Object> delete(@PathVariable String memoryId) {
        return ServiceSupport.require(memoryService, "记忆服务").delete(memoryId);
    }

    /**
     * 清空某个工作区的记忆。
     *
     * @param workspaceId 工作区 id，可选
     * @return 清空结果
     */
    @DeleteMapping
    public Map<String, Object> clear(
            @RequestParam(name = "workspace_id", required = false) String workspaceId
    ) {
        return ServiceSupport.require(memoryService, "记忆服务").clear(workspaceId);
    }

    /**
     * 手动触发记忆抽取。
     *
     * @param request 抽取请求
     * @return 抽取结果
     */
    @PostMapping("/extract")
    public Map<String, Object> extract(@Valid @RequestBody MemoryDtos.MemoryExtractRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").extract(request);
    }

    /**
     * 立即整理记忆。
     *
     * @param request 维护请求
     * @return 整理结果
     */
    @PostMapping("/prune")
    public Map<String, Object> prune(@RequestBody MemoryDtos.MemoryMaintenanceRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").prune(request);
    }

    /**
     * 重建记忆向量。
     *
     * @param request 维护请求
     * @return 重建结果
     */
    @PostMapping("/reindex")
    public Map<String, Object> reindex(@RequestBody MemoryDtos.MemoryMaintenanceRequest request) {
        return ServiceSupport.require(memoryService, "记忆服务").reindex(request);
    }
}
