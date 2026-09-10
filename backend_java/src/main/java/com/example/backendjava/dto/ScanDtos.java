// 模块说明：文件扫描域的 DTO，对应 Python 侧 /api/scan/*。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;
// Jakarta 校验注解：字符串非空
import jakarta.validation.constraints.NotBlank;

/**
 * 扫描域 DTO 集合。
 */
public final class ScanDtos {

    /** 工具类禁止实例化。 */
    private ScanDtos() {
    }

    /**
     * 发起扫描的请求体。
     *
     * @param path 要扫描的根目录路径（绝对路径或相对当前工作目录）
     */
    public record ScanStartRequest(
            // 待扫描目录
            @NotBlank(message = "path 不能为空")
            String path
    ) {
    }

    /**
     * 按任务 id 取结果的请求体。
     *
     * @param taskId 扫描任务 id
     */
    public record ScanResultRequest(
            // 任务 id
            @NotBlank(message = "task_id 不能为空")
            @JsonProperty("task_id") String taskId
    ) {
    }

    /**
     * 扫描任务展示信息，字段与前端 TaskInfo 对齐。
     *
     * @param taskId          任务 id
     * @param path            本次扫描的根目录
     * @param status          状态：pending / running / done / cancelled / failed
     * @param scanned         已扫描文件数
     * @param totalBytes      已扫描总字节数
     * @param totalBytesHuman 人类可读的字节数，如 "1.2 GB"
     * @param skipped         被跳过的条目数
     * @param error           失败原因；正常时为 null
     * @param createdAt       创建时间（ISO-8601）
     * @param startedAt       开始执行时间（ISO-8601）；未开始为 null
     * @param endedAt         结束时间（ISO-8601）；未结束为 null
     * @param elapsed         已耗时秒数
     */
    public record TaskInfo(
            // 任务 id
            @JsonProperty("task_id") String taskId,
            // 根目录
            String path,
            // 状态
            String status,
            // 已扫描文件数
            long scanned,
            // 已扫描字节数
            @JsonProperty("total_bytes") long totalBytes,
            // 人类可读字节数
            @JsonProperty("total_bytes_human") String totalBytesHuman,
            // 跳过条目数
            long skipped,
            // 失败原因
            String error,
            // 创建时间
            @JsonProperty("created_at") String createdAt,
            // 开始时间
            @JsonProperty("started_at") String startedAt,
            // 结束时间
            @JsonProperty("ended_at") String endedAt,
            // 耗时秒数
            double elapsed
    ) {
    }

    /**
     * 扫描进度快照，对应 GET /scan/status。
     *
     * @param taskId          任务 id
     * @param status          状态
     * @param scanned         已扫描文件数
     * @param totalBytes      已扫描总字节数
     * @param totalBytesHuman 人类可读的字节数
     * @param skipped         被跳过的条目数
     * @param error           失败原因；正常时为 null
     * @param elapsed         已耗时秒数
     */
    public record ScanProgress(
            // 任务 id
            @JsonProperty("task_id") String taskId,
            // 状态
            String status,
            // 已扫描文件数
            long scanned,
            // 已扫描字节数
            @JsonProperty("total_bytes") long totalBytes,
            // 人类可读字节数
            @JsonProperty("total_bytes_human") String totalBytesHuman,
            // 跳过条目数
            long skipped,
            // 失败原因
            String error,
            // 耗时秒数
            double elapsed
    ) {
    }

    /**
     * 取消扫描的返回体。
     *
     * @param taskId          任务 id
     * @param cancelRequested 取消请求是否被接受；true 不代表任务已立即停止
     */
    public record ScanCancelResult(
            // 任务 id
            @JsonProperty("task_id") String taskId,
            // 是否接受取消请求
            @JsonProperty("cancel_requested") boolean cancelRequested
    ) {
    }
}
