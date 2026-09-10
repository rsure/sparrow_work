// 模块说明：文件扫描业务接口。实现建议用独立线程池 + 任务状态表，SSE 只负责轮询推送。
package com.example.backendjava.service;

// Spring MVC 的 SSE 发射器
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// 项目内通用分页结果
import com.example.backendjava.common.PageResult;

// 扫描接口的请求/响应 DTO 容器
import com.example.backendjava.dto.ScanDtos;

/**
 * 扫描服务接口。
 */
public interface ScanService {

    /**
     * 分页查询历史扫描任务。
     *
     * @param pageSize 每页条数
     * @param pageNum  页码（从 1 开始）
     * @return 分页结果
     */
    PageResult<ScanDtos.TaskInfo> pages(int pageSize, int pageNum);

    /**
     * 发起扫描，立即返回任务 id。
     *
     * @param path 要扫描的根目录
     * @return 新任务 id
     */
    String start(String path);

    /**
     * 以 SSE 推送任务进度；任务进入终态后补发 end 事件并关流。
     *
     * @param taskId      任务 id
     * @param interval    轮询间隔（秒）
     * @param maxDuration 最长推送时长（秒），防止僵尸连接
     * @return SSE 发射器
     */
    SseEmitter streamStatus(String taskId, double interval, double maxDuration);

    /**
     * 以 SSE 增量推送扫描到的文件。
     *
     * @param taskId    任务 id
     * @param fromIndex 从第几个文件开始推送；前端重连时用它续读，0 表示从头
     * @return SSE 发射器
     */
    SseEmitter streamFiles(String taskId, int fromIndex);

    /**
     * 查询任务进度快照。
     *
     * @param taskId 任务 id
     * @return 进度快照
     */
    ScanDtos.ScanProgress status(String taskId);

    /**
     * 请求取消任务。
     *
     * @param taskId 任务 id
     * @return 取消受理结果
     */
    ScanDtos.ScanCancelResult cancel(String taskId);

    /**
     * 取结果；任务未完成时返回进度快照，完成后返回完整结果。
     *
     * @param taskId 任务 id
     * @return 进度或结果 JSON；结构随任务状态变化
     */
    Object info(String taskId);

    /**
     * 取结果；任务未完成时返回已扫描到的部分结果。
     *
     * @param taskId 任务 id
     * @return 部分或完整结果 JSON
     */
    Object result(String taskId);
}
