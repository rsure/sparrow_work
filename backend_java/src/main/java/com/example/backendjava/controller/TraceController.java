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
// Jakarta 校验注解：limit 的下界（小于 1 直接 400）
import jakarta.validation.constraints.Min;
// Jakarta 校验注解：limit 的上界（超过上限直接 400）
import jakarta.validation.constraints.Max;
// Spring 校验开关：类上标了它，方法参数上的 @Min/@Max 才会被校验
import org.springframework.validation.annotation.Validated;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 轨迹业务接口：执行事件按会话/轮次查询
import com.example.backendjava.service.TraceService;
// 项目内：limit 的默认值与上限契约表（Python 侧镜像在 app/core/limits.py）
import com.example.backendjava.common.PageLimits;

// 标准库：Map 用于动态轨迹结构
import java.util.Map;

/**
 * 执行轨迹接口。
 *
 * <p>Python 侧这三个端点返回裸 JSON，这里保持兼容。</p>
 */
@Validated
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
    public Map<String, Object> listSessions(
            @RequestParam(defaultValue = "" + PageLimits.DEFAULT_TRACE_SESSIONS)
            // 越界 400：与 Python 侧 Query(ge=1, le=200) 对齐
            @Min(1) @Max(PageLimits.MAX_TRACE_SESSIONS) int limit
    ) {
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
            @RequestParam(defaultValue = "" + PageLimits.DEFAULT_TRACE_TURNS)
            // 越界 400：轮次上限 200，再多就应该分批看而不是一次拉完
            @Min(1) @Max(PageLimits.MAX_TRACE_TURNS) int limit
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
            @RequestParam(defaultValue = "" + PageLimits.DEFAULT_TRACE_EVENTS)
            // 排查一次通常要看几百条事件，上限放宽到 5000；越界同样是 400
            @Min(1) @Max(PageLimits.MAX_TRACE_EVENTS) int limit
    ) {
        return ServiceSupport.require(traceService, "轨迹服务").listEvents(sessionId, turnId, limit);
    }
}
