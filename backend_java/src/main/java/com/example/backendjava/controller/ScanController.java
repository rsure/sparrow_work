// 模块说明：文件扫描接口，路径与 Python 侧 /api/scan/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /scan
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：查询参数
import org.springframework.web.bind.annotation.RequestParam;
// Spring Web 注解：JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// Jakarta 校验注解
import jakarta.validation.Valid;
// Spring MVC 的 SSE 发射器
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;
// 项目内分页结果
import com.example.backendjava.common.PageResult;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;

// 扫描业务接口：目录遍历与分页返回
import com.example.backendjava.service.ScanService;
// 扫描接口的请求/响应 DTO 容器
import com.example.backendjava.dto.ScanDtos;

/**
 * 文件扫描接口。
 */
@RestController
@RequestMapping("/scan")
public class ScanController {

    /** 扫描服务；学习者实现后自动注入。 */
    private final ObjectProvider<ScanService> scanService;

    /**
     * 构造器注入可选 Service。
     *
     * @param scanService Spring 的按类型查找器
     */
    public ScanController(ObjectProvider<ScanService> scanService) {
        this.scanService = scanService;
    }

    /**
     * 分页查询历史扫描任务。
     *
     * @param pageSize 每页条数，默认 10
     * @param pageNum  页码，默认 1
     * @return 分页结果
     */
    @GetMapping("/pages")
    public ApiResponse<PageResult<ScanDtos.TaskInfo>> pages(
            // 前端参数名是 snake_case：page_size / page_num
            @RequestParam(name = "page_size", defaultValue = "10") int pageSize,
            @RequestParam(name = "page_num", defaultValue = "1") int pageNum
    ) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").pages(pageSize, pageNum));
    }

    /**
     * 发起扫描。
     *
     * @param request 扫描请求
     * @return 新任务 id
     */
    @PostMapping("/start")
    public ApiResponse<String> start(@Valid @RequestBody ScanDtos.ScanStartRequest request) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").start(request.path()));
    }

    /**
     * SSE 推送任务进度。
     *
     * @param taskId      任务 id
     * @param interval    轮询间隔（秒），默认 5
     * @param maxDuration 最长推送时长（秒），默认 3600
     * @return SSE 流
     */
    @GetMapping("/stream")
    public SseEmitter streamStatus(
            @RequestParam("task_id") String taskId,
            @RequestParam(defaultValue = "5.0") double interval,
            // 前端参数名是 max_duration（snake_case）
            @RequestParam(name = "max_duration", defaultValue = "3600.0") double maxDuration
    ) {
        return ServiceSupport.require(scanService, "扫描服务")
                .streamStatus(taskId, interval, maxDuration);
    }

    /**
     * SSE 增量推送扫描到的文件。
     *
     * @param taskId    任务 id
     * @param fromIndex 从第几个文件开始推送，默认 0；前端重连时用它续读
     * @return SSE 流
     */
    @GetMapping("/files/stream")
    public SseEmitter streamFiles(
            @RequestParam("task_id") String taskId,
            @RequestParam(name = "from_index", defaultValue = "0") int fromIndex
    ) {
        return ServiceSupport.require(scanService, "扫描服务").streamFiles(taskId, fromIndex);
    }

    /**
     * 查询任务进度快照。
     *
     * @param taskId 任务 id
     * @return 进度快照
     */
    @GetMapping("/status")
    public ApiResponse<ScanDtos.ScanProgress> status(@RequestParam("task_id") String taskId) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").status(taskId));
    }

    /**
     * 请求取消任务。
     *
     * @param taskId 任务 id
     * @return 取消受理结果
     */
    @PostMapping("/cancel")
    public ApiResponse<ScanDtos.ScanCancelResult> cancel(@RequestParam("task_id") String taskId) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").cancel(taskId));
    }

    /**
     * 取结果；未完成时返回进度快照。
     *
     * @param taskId 任务 id
     * @return 进度或结果 JSON
     */
    @GetMapping("/info")
    public ApiResponse<Object> info(@RequestParam("task_id") String taskId) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").info(taskId));
    }

    /**
     * 取结果；未完成时返回部分结果。
     *
     * @param request 含 task_id 的请求体
     * @return 部分或完整结果 JSON
     */
    @PostMapping("/result")
    public ApiResponse<Object> result(@Valid @RequestBody ScanDtos.ScanResultRequest request) {
        return ApiResponse.ok(ServiceSupport.require(scanService, "扫描服务").result(request.taskId()));
    }
}
