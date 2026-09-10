// 模块说明：扫描任务实体（对应 Python 侧 entity/scan_task.py 的 TaskInfo）。
// 入库字段承载记账与起止时间；运行时字段（取消信号、文件明细、线程）仅存在于内存、不入库。
package com.example.backendjava.entity;

// JPA 注解：实体/表/列/主键/瞬态字段/加载后回调
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PostLoad;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
// Lombok：自动生成 getter/setter
import lombok.Getter;
import lombok.Setter;

// 标准库：List 保存文件明细与跳过原因
import java.util.ArrayList;
import java.util.List;

/**
 * 扫描任务记录：只承载数据与状态。
 *
 * <ul>
 *   <li>入库字段：计数、起止时间、错误信息、最终结果，便于历史查询；</li>
 *   <li>运行时字段（{@code @Transient}）：仅存在于内存，供后台扫描线程与查询接口读写。</li>
 * </ul>
 */
@Getter
@Setter
@Entity
@Table(name = "task_info")
public class ScanTask {

    /** 任务唯一 id（由调用方生成，如 uuid 的 hex 形式）。 */
    @Id
    @Column(name = "task_id", nullable = false)
    private String taskId;

    /** 扫描根目录的绝对路径。 */
    @Column(name = "path", nullable = false)
    private String path;

    /** pending / running / done / cancelled / failed。 */
    @Column(name = "status", nullable = false)
    private volatile String status = "pending";

    /** 成功读取到的文件数（被跳过的文件不计入）。 */
    @Column(name = "scanned", nullable = false)
    private volatile long scanned = 0;

    /** 已扫文件的字节数合计。 */
    @Column(name = "total_bytes", nullable = false)
    private volatile long totalBytes = 0;

    /** 被跳过的文件/目录数量。 */
    @Column(name = "skipped", nullable = false)
    private volatile long skipped = 0;

    /** 失败原因（仅 status=failed 时有值）。 */
    @Column(name = "error")
    private volatile String error;

    /** 任务记录入库时间。 */
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    /** 扫描线程真正开始的时刻；未开始为 null。 */
    @Column(name = "started_at")
    private volatile String startedAt;

    /** 扫描结束（完成/取消/失败）的时刻；未结束为 null。 */
    @Column(name = "ended_at")
    private volatile String endedAt;

    /** 完成后的完整结果 JSON（ScanResult.to_json 形状）。 */
    @Column(name = "result_json", length = Integer.MAX_VALUE)
    private String resultJson;

    /** 扫描到的全部文件明细 JSON（FileInfo.to_dict 列表）。 */
    @Column(name = "files_json", length = Integer.MAX_VALUE)
    private String filesJson;

    // ------------------------------------------------------------------ //
    // 运行时字段（不入库）
    // ------------------------------------------------------------------ //

    /** 取消信号：置 true 后后台线程在下一个检查点退出。 */
    @Transient
    private volatile boolean cancelled = false;

    /** 已扫描到的文件明细（内存态，落库时转 files_json）。 */
    @Transient
    private List<FileEntry> files = new ArrayList<>();

    /** 跳过原因明细（内存态，落库时汇总进 result_json）。 */
    @Transient
    private List<String> skippedReasons = new ArrayList<>();

    /** 后台扫描线程；未启动时为 null。 */
    @Transient
    private Thread thread;

    /**
     * Hibernate 从数据库加载实体时可能绕过构造器（跳过字段初始化），
     * 这里补齐运行时字段，避免后续操作碰到 null。
     */
    @PostLoad
    void onLoad() {
        if (files == null) {
            files = new ArrayList<>();
        }
        if (skippedReasons == null) {
            skippedReasons = new ArrayList<>();
        }
    }
}
