// 模块说明：执行轨迹接口，路径与 Python 侧 /api/trace/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /trace
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：路径变量
import org.springframework.web.bind.annotation.PathVariable;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 轨迹业务接口：执行事件按会话/轮次查询
import com.example.backendjava.service.TraceService;

// 标准库：Map 用于动态轨迹结构
import java.util.Map;

/**
 * 执行轨迹接口。
 *
 * <p>Python 侧这三个端点返回裸 JSON，这里保持兼容。</p>
 */
@RestController
@RequestMapping("/trace")
public class TraceController {

    /** 轨迹服务；学习者实现后自动注入。 */
    private final ObjectProvider<TraceService> traceService;

    /**
     * 构造器注入可选 Service。
     *
     * @param traceService Spring 的按类型查找器
     */
    public TraceController(ObjectProvider<TraceService> traceService) {
        this.traceService = traceService;
    }

    /**
     * 列出有轨迹的会话。
     *
     * @param limit 最多返回多少个，默认 50
     * @return 会话列表
     */
    @GetMapping("/sessions")
    public Map<String, Object> listSessions(@RequestParam(defaultValue = "50") int limit) {
        return ServiceSupport.require(traceService, "轨迹服务").listSessions(limit);
    }

    /**
     * 列出某个会话的轮次。
     *
     * @param sessionId 会话 id
     * @param limit     最多返回多少轮，默认 50
     * @return 轮次列表
     */
    @GetMapping("/sessions/{sessionId}/turns")
    public Map<String, Object> listTurns(
            @PathVariable String sessionId,
            @RequestParam(defaultValue = "50") int limit
    ) {
        return ServiceSupport.require(traceService, "轨迹服务").listTurns(sessionId, limit);
    }

    /**
     * 读取轨迹事件。
     *
     * @param sessionId 会话 id
     * @param turnId    轮次 id，可选
     * @param limit     最多返回多少条，默认 500
     * @return 轨迹事件
     */
    @GetMapping("/sessions/{sessionId}")
    public Map<String, Object> listEvents(
            @PathVariable String sessionId,
            @RequestParam(name = "turn_id", required = false) String turnId,
            @RequestParam(defaultValue = "500") int limit
    ) {
        return ServiceSupport.require(traceService, "轨迹服务").listEvents(sessionId, turnId, limit);
    }
}
