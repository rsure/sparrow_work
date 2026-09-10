// 模块说明：文件扫描服务实现（对应 Python 侧 controllers/sanner_controller.py +
// services/scan_manager.py + services/task_service.py + services/scan_servicer.py）。
//
// 数据流：/start 校验路径并立即返回 task_id ──► 后台 daemon 线程递归遍历目录
//         ──► 逐个文件记账（计数/字节/跳过）──► 终态落库。
// 查询侧：/status 单次快照；/stream 与 /files/stream 用 SSE 轮询推送；
//         /info、/result 取完整/部分结果。
package com.example.backendjava.service.impl;

// Jackson 泛型类型引用：把落库的 files_json 文本解析成 List<Map>
import com.fasterxml.jackson.core.type.TypeReference;

// 日志
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为服务组件
import org.springframework.stereotype.Service;
// Spring MVC 的 SSE 发射器：进度流与文件流
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// Jakarta 依赖注入：按类型注入字段
import jakarta.annotation.Resource;

// 标准库：IO 异常（目录遍历、SSE 发送）
import java.io.IOException;
// 标准库：文件树遍历（walkFileTree）与路径/属性
import java.nio.file.AccessDeniedException;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
// 标准库：时间戳与耗时
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneId;
// 标准库：集合与并发
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

// 项目内：业务异常（路径不合法/不存在、任务不存在）
import com.example.backendjava.common.ApiException;
// 项目内：通用分页结果
import com.example.backendjava.common.PageResult;
// 项目内：扫描接口的请求/响应 DTO
import com.example.backendjava.dto.ScanDtos;
// 项目内：文件快照
import com.example.backendjava.entity.FileEntry;
// 项目内：扫描任务实体
import com.example.backendjava.entity.ScanTask;
// 项目内：扫描任务仓库
import com.example.backendjava.repository.ScanTaskRepository;
// 项目内：扫描业务接口（本类实现它）
import com.example.backendjava.service.ScanService;
// 项目内：JSON 工具（SSE 帧、结果/文件明细落库）
import com.example.backendjava.util.JsonUtils;

/**
 * 扫描服务实现。
 */
@Service
public class ScanServiceImpl implements ScanService {

    /** 日志：记录任务启动/结束与流关闭。 */
    private static final Logger log = LoggerFactory.getLogger(ScanServiceImpl.class);

    // ------------------------------------------------------------------ //
    // 常量
    // ------------------------------------------------------------------ //

    /** 内存中最多保留多少个任务，超限时回收最旧的已完成任务。 */
    private static final int MAX_KEEP = 100;

    /** 任务终态集合。 */
    private static final Set<String> TERMINAL_STATES = Set.of("done", "cancelled", "failed");

    /** 黑名单目录名（按目录名精确匹配，不区分路径）。 */
    private static final Set<String> SKIP_DIRS = Set.of(
            ".git", ".svn", ".hg",
            "node_modules", "__pycache__",
            ".venv", "venv", ".idea", ".vscode");

    /** 没有扩展名、但有固定文件名的特例 → 代码类。 */
    private static final Set<String> NAME_TO_KIND = Set.of("makefile", "dockerfile", ".gitignore");

    /** 扩展名 → 文件大类。 */
    private static final Map<String, String> EXT_TO_KIND = new HashMap<>();

    static {
        registerKind("document", ".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt");
        registerKind("image", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp");
        registerKind("video", ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv");
        registerKind("audio", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a");
        registerKind("archive", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz");
        registerKind("code", ".ts", ".js", ".py", ".java", ".vue", ".json",
                ".toml", ".yaml", ".yml", ".rs", ".go", ".sh");
    }

    /** 落库 files_json 的反序列化类型。 */
    private static final TypeReference<List<Map<String, Object>>> LIST_OF_MAPS = new TypeReference<>() {
    };

    // ------------------------------------------------------------------ //
    // 依赖
    // ------------------------------------------------------------------ //

    /** 扫描任务仓库。 */
    @Resource
    private ScanTaskRepository scanTaskRepository;

    /** 内存任务注册表：正在运行/最近完成的任务（线程安全）。 */
    private final Map<String, ScanTask> tasks = new ConcurrentHashMap<>();

    /** 保护注册表 GC 的锁。 */
    private final Object registryLock = new Object();

    // ------------------------------------------------------------------ //
    // 1. 分页查询
    // ------------------------------------------------------------------ //

    @Override
    public PageResult<ScanDtos.TaskInfo> pages(int pageSize, int pageNum) {
        List<ScanTask> all = scanTaskRepository.findAllByOrderByCreatedAtDesc();
        int size = Math.max(1, Math.min(pageSize, 100));
        int page = Math.max(1, pageNum);
        int from = (page - 1) * size;
        int to = Math.min(from + size, all.size());

        List<ScanDtos.TaskInfo> items = new ArrayList<>();
        for (int i = Math.min(from, all.size()); i < to; i++) {
            items.add(toTaskInfo(all.get(i)));
        }
        return PageResult.of(items, all.size(), page, size);
    }

    // ------------------------------------------------------------------ //
    // 2. 发起扫描
    // ------------------------------------------------------------------ //

    @Override
    public String start(String path) {
        Path p = Path.of(path);
        if (!p.isAbsolute()) {
            throw new ApiException(400, "只能输入绝对路径，如 F:\\demo");
        }
        if (!Files.exists(p)) {
            throw new ApiException(404, "路径不存在: " + p);
        }

        String taskId = UUID.randomUUID().toString().replace("-", "");
        ScanTask task = new ScanTask();
        task.setTaskId(taskId);
        task.setPath(p.toString());
        task.setStatus("pending");
        task.setScanned(0);
        task.setTotalBytes(0);
        task.setSkipped(0);
        task.setCreatedAt(now());
        scanTaskRepository.save(task);

        register(task);

        Thread thread = new Thread(() -> runScan(task), "scan-" + taskId);
        thread.setDaemon(true);
        task.setThread(thread);
        thread.start();
        return taskId;
    }

    // ------------------------------------------------------------------ //
    // 3. SSE：进度流
    // ------------------------------------------------------------------ //

    @Override
    public SseEmitter streamStatus(String taskId, double interval, double maxDuration) {
        ScanTask task = requireTask(taskId);
        SseEmitter emitter = new SseEmitter((long) (maxDuration * 1000));
        startDaemon("scan-sse-" + taskId, () -> runStatusStream(emitter, task, interval, maxDuration));
        return emitter;
    }

    private void runStatusStream(SseEmitter emitter, ScanTask task, double interval, double maxDuration) {
        long startNanos = System.nanoTime();
        AtomicBoolean closed = new AtomicBoolean(false);
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> closed.set(true));
        emitter.onError(ex -> closed.set(true));

        try {
            while (!closed.get()) {
                if ((System.nanoTime() - startNanos) / 1e9 > maxDuration) {
                    break;
                }
                Map<String, Object> snap = progressMap(task);
                String id = String.valueOf((long) (elapsedSeconds(task) * 1000));
                emit(emitter, "progress", id, JsonUtils.toJson(snap));

                if (isTerminal(task.getStatus())) {
                    emit(emitter, "end", null, JsonUtils.toJson(snap));
                    break;
                }
                sleepSeconds(interval);
            }
        } catch (IOException | IllegalStateException e) {
            log.debug("进度流发送失败（客户端可能已断开）：{}", e.getMessage());
        } finally {
            completeQuietly(emitter);
        }
    }

    // ------------------------------------------------------------------ //
    // 4. SSE：文件流
    // ------------------------------------------------------------------ //

    @Override
    public SseEmitter streamFiles(String taskId, int fromIndex) {
        ScanTask task = requireTask(taskId);
        SseEmitter emitter = new SseEmitter(3600_000L);
        startDaemon("scan-files-sse-" + taskId, () -> runFilesStream(emitter, task, fromIndex));
        return emitter;
    }

    private void runFilesStream(SseEmitter emitter, ScanTask task, int fromIndex) {
        long startNanos = System.nanoTime();
        int idx = fromIndex;
        AtomicBoolean closed = new AtomicBoolean(false);
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> closed.set(true));
        emitter.onError(ex -> closed.set(true));

        try {
            while (!closed.get()) {
                // 文件流比进度流更勤：1 秒一次；单条连接最长 1 小时
                if ((System.nanoTime() - startNanos) / 1e9 > 3600.0) {
                    break;
                }
                FileSlice slice = filesSince(task, idx);
                boolean terminal = isTerminal(task.getStatus());

                if (!slice.newFiles().isEmpty() || terminal) {
                    Map<String, Object> payload = filesPayload(task, slice.newFiles(), slice.nextIndex());
                    emit(emitter, "files", null, JsonUtils.toJson(payload));
                    idx = slice.nextIndex();
                }
                if (terminal) {
                    Map<String, Object> endPayload = new LinkedHashMap<>(filesPayload(task, List.of(), idx));
                    endPayload.put("items", List.of());
                    emit(emitter, "end", null, JsonUtils.toJson(endPayload));
                    break;
                }
                sleepSeconds(1.0);
            }
        } catch (IOException | IllegalStateException e) {
            log.debug("文件流发送失败（客户端可能已断开）：{}", e.getMessage());
        } finally {
            completeQuietly(emitter);
        }
    }

    // ------------------------------------------------------------------ //
    // 5. 快照 / 取消 / 结果
    // ------------------------------------------------------------------ //

    @Override
    public ScanDtos.ScanProgress status(String taskId) {
        ScanTask task = requireTask(taskId);
        synchronized (task) {
            return new ScanDtos.ScanProgress(
                    task.getTaskId(),
                    task.getStatus(),
                    task.getScanned(),
                    task.getTotalBytes(),
                    humanSize(task.getTotalBytes()),
                    task.getSkipped(),
                    task.getError(),
                    round3(elapsedSeconds(task)));
        }
    }

    @Override
    public ScanDtos.ScanCancelResult cancel(String taskId) {
        ScanTask task = requireTask(taskId);
        boolean requested;
        synchronized (task) {
            if (isTerminal(task.getStatus())) {
                requested = false;
            } else {
                task.setCancelled(true);
                requested = true;
            }
        }
        return new ScanDtos.ScanCancelResult(taskId, requested);
    }

    @Override
    public Object info(String taskId) {
        ScanTask task = requireTask(taskId);
        if (!isTerminal(task.getStatus())) {
            return progressMap(task);
        }
        if (isDoneOrCancelled(task.getStatus())) {
            return resultMap(task);
        }
        return Map.of("state", "no_result");
    }

    @Override
    public Object result(String taskId) {
        ScanTask task = requireTask(taskId);
        if (isTerminal(task.getStatus()) && !isDoneOrCancelled(task.getStatus())) {
            // 失败任务没有可返回的结果
            return Map.of("state", "no_result");
        }
        return resultMap(task);
    }

    // ------------------------------------------------------------------ //
    // 6. 后台扫描
    // ------------------------------------------------------------------ //

    /** 后台线程主流程：置 RUNNING → 真正扫描 → 定终态 → 落库。 */
    private void runScan(ScanTask task) {
        synchronized (task) {
            task.setStatus("running");
            task.setStartedAt(now());
        }
        boolean failed = false;
        try {
            doScan(task);
        } catch (Exception e) {
            failed = true;
            synchronized (task) {
                task.setStatus("failed");
                task.setError(e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }
        if (!failed) {
            synchronized (task) {
                task.setStatus(task.isCancelled() ? "cancelled" : "done");
            }
        }
        synchronized (task) {
            task.setEndedAt(now());
        }
        saveResult(task);
    }

    /** 真正的遍历：单文件直接处理，目录走 walkFileTree 并做剪枝/取消检查。 */
    private void doScan(ScanTask task) {
        Path root = Path.of(task.getPath());

        if (Files.isRegularFile(root)) {
            FileEntry entry = safeFileEntry(task, root);
            if (entry != null) {
                recordFile(task, entry);
            }
            return;
        }

        try {
            Files.walkFileTree(root, new SimpleFileVisitor<>() {
                @Override
                public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                    if (task.isCancelled()) {
                        return FileVisitResult.TERMINATE;
                    }
                    String name = dir.getFileName().toString();
                    if (name.startsWith(".")) {
                        recordSkip(task, "[跳过隐藏目录] " + dir);
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    if (SKIP_DIRS.contains(name)) {
                        recordSkip(task, "[跳过目录] " + dir);
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    if (Files.isSymbolicLink(dir)) {
                        recordSkip(task, "[跳过软链接目录] " + dir);
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                    if (task.isCancelled()) {
                        return FileVisitResult.TERMINATE;
                    }
                    FileEntry entry = safeFileEntry(task, file);
                    if (entry != null) {
                        recordFile(task, entry);
                    }
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult visitFileFailed(Path file, IOException exc) {
                    recordSkip(task, "[目录访问失败] " + file + ": "
                            + (exc == null ? "unknown" : exc.getMessage()));
                    return FileVisitResult.CONTINUE;
                }
            });
        } catch (IOException e) {
            recordSkip(task, "[目录访问失败] " + root + ": " + e.getMessage());
        }
    }

    /** 安全构造文件快照；任何异常都转为跳过记录，绝不让扫描崩溃。 */
    private FileEntry safeFileEntry(ScanTask task, Path file) {
        try {
            String name = file.getFileName().toString();
            if (name.startsWith(".")) {
                recordSkip(task, "[跳过隐藏文件] " + file);
                return null;
            }
            if (Files.isSymbolicLink(file)) {
                recordSkip(task, "[跳过软链接] " + file);
                return null;
            }
            if (Files.isDirectory(file)) {
                return null;
            }
            BasicFileAttributes attrs = Files.readAttributes(file, BasicFileAttributes.class);
            String modifiedAt = LocalDateTime.ofInstant(
                    attrs.lastModifiedTime().toInstant(), ZoneId.systemDefault()).toString();
            return new FileEntry(file.toString(), name, attrs.size(), kindOf(file), false, modifiedAt);
        } catch (NoSuchFileException e) {
            recordSkip(task, "[文件不存在/断链] " + file + ": " + e.getMessage());
            return null;
        } catch (AccessDeniedException e) {
            recordSkip(task, "[权限拒绝] " + file + ": " + e.getMessage());
            return null;
        } catch (IOException e) {
            recordSkip(task, "[IO错误] " + file + ": " + e.getMessage());
            return null;
        } catch (Exception e) {
            recordSkip(task, "[未知错误] " + file + ": " + e.getClass().getSimpleName() + ": " + e.getMessage());
            return null;
        }
    }

    /** 线程安全记账：成功则入文件列表并累加计数/字节，失败则入跳过列表。 */
    private void recordFile(ScanTask task, FileEntry entry) {
        synchronized (task) {
            task.getFiles().add(entry);
            task.setScanned(task.getScanned() + 1);
            task.setTotalBytes(task.getTotalBytes() + entry.fileSize());
        }
    }

    private void recordSkip(ScanTask task, String message) {
        synchronized (task) {
            task.getSkippedReasons().add(message);
            task.setSkipped(task.getSkipped() + 1);
        }
    }

    /** 扫描结束后，把最终结果与文件明细落库。 */
    private void saveResult(ScanTask task) {
        synchronized (task) {
            List<FileEntry> files = new ArrayList<>(task.getFiles());
            List<String> skipped = new ArrayList<>(task.getSkippedReasons());
            task.setResultJson(JsonUtils.toJson(buildResultMap(task.getPath(), files, skipped)));
            task.setFilesJson(JsonUtils.toJson(files.stream().map(FileEntry::toSnakeMap).toList()));
            scanTaskRepository.save(task);
        }
    }

    // ------------------------------------------------------------------ //
    // 7. 任务注册表与查找
    // ------------------------------------------------------------------ //

    private void register(ScanTask task) {
        synchronized (registryLock) {
            tasks.put(task.getTaskId(), task);
            gcLocked();
        }
    }

    /** 防止任务无限堆积：超过上限时清掉最旧的已完成任务。 */
    private void gcLocked() {
        if (tasks.size() <= MAX_KEEP) {
            return;
        }
        List<Map.Entry<String, ScanTask>> finished = new ArrayList<>();
        for (Map.Entry<String, ScanTask> entry : tasks.entrySet()) {
            if (isTerminal(entry.getValue().getStatus())) {
                finished.add(entry);
            }
        }
        finished.sort(Comparator.comparingDouble(e -> elapsedSeconds(e.getValue())));
        int excess = tasks.size() - MAX_KEEP;
        for (int i = 0; i < excess && i < finished.size(); i++) {
            tasks.remove(finished.get(i).getKey());
        }
    }

    /** 先查内存注册表，再回落到数据库里的历史记录。 */
    private ScanTask getTask(String taskId) {
        ScanTask task = tasks.get(taskId);
        if (task != null) {
            return task;
        }
        return scanTaskRepository.findById(taskId).map(this::restoreTransient).orElse(null);
    }

    /** 从落库 JSON 还原运行时文件/跳过明细（历史任务重读时用）。 */
    private ScanTask restoreTransient(ScanTask task) {
        if (task.getFiles() == null) {
            task.setFiles(new ArrayList<>());
        }
        if (task.getSkippedReasons() == null) {
            task.setSkippedReasons(new ArrayList<>());
        }
        if (task.getFilesJson() != null && !task.getFilesJson().isBlank()) {
            try {
                for (Map<String, Object> map : JsonUtils.parse(task.getFilesJson(), LIST_OF_MAPS)) {
                    task.getFiles().add(FileEntry.fromMap(map));
                }
            } catch (RuntimeException e) {
                log.debug("files_json 解析失败：{}", e.getMessage());
            }
        }
        if (task.getResultJson() != null && !task.getResultJson().isBlank()) {
            try {
                Map<String, Object> result = JsonUtils.parseMap(task.getResultJson());
                Object skipped = result.get("skipped");
                if (skipped instanceof List<?> list) {
                    for (Object item : list) {
                        if (item instanceof String text) {
                            task.getSkippedReasons().add(text);
                        }
                    }
                }
            } catch (RuntimeException e) {
                log.debug("result_json 解析失败：{}", e.getMessage());
            }
        }
        return task;
    }

    private ScanTask requireTask(String taskId) {
        ScanTask task = getTask(taskId);
        if (task == null) {
            throw new ApiException(404, "任务不存在");
        }
        return task;
    }

    // ------------------------------------------------------------------ //
    // 8. 形状构造
    // ------------------------------------------------------------------ //

    private ScanDtos.TaskInfo toTaskInfo(ScanTask task) {
        return new ScanDtos.TaskInfo(
                task.getTaskId(),
                task.getPath(),
                task.getStatus(),
                task.getScanned(),
                task.getTotalBytes(),
                humanSize(task.getTotalBytes()),
                task.getSkipped(),
                task.getError(),
                task.getCreatedAt(),
                task.getStartedAt(),
                task.getEndedAt(),
                elapsedSeconds(task));
    }

    /** 进度快照（Python ScanProgress.to_dict 形状，供 SSE 与 /info 使用）。 */
    private Map<String, Object> progressMap(ScanTask task) {
        synchronized (task) {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("task_id", task.getTaskId());
            map.put("path", task.getPath());
            map.put("state", task.getStatus());
            map.put("scanned", task.getScanned());
            map.put("total_bytes", task.getTotalBytes());
            map.put("total_bytes_human", humanSize(task.getTotalBytes()));
            map.put("skipped", task.getSkipped());
            map.put("elapsed", round3(elapsedSeconds(task)));
            map.put("error", task.getError());
            return map;
        }
    }

    /** 完整/部分结果（Python ScanResult.to_json 形状）。 */
    private Map<String, Object> resultMap(ScanTask task) {
        synchronized (task) {
            return buildResultMap(task.getPath(), new ArrayList<>(task.getFiles()),
                    new ArrayList<>(task.getSkippedReasons()));
        }
    }

    private Map<String, Object> buildResultMap(String path, List<FileEntry> files, List<String> skipped) {
        long totalSize = 0;
        Map<String, long[]> groups = new LinkedHashMap<>();
        for (FileEntry file : files) {
            totalSize += file.fileSize();
            long[] group = groups.computeIfAbsent(file.kind(), ignored -> new long[2]);
            group[0] += 1;
            group[1] += file.fileSize();
        }

        List<FileEntry> bySize = new ArrayList<>(files);
        bySize.sort(Comparator.comparingLong(FileEntry::fileSize).reversed());
        List<Map<String, Object>> top = new ArrayList<>();
        for (int i = 0; i < Math.min(10, bySize.size()); i++) {
            FileEntry file = bySize.get(i);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("path", file.path());
            item.put("size", file.fileSize());
            item.put("size_human", humanSize(file.fileSize()));
            item.put("kind", file.kind());
            item.put("modified_at", file.modifiedAt());
            top.add(item);
        }

        Map<String, Object> groupsOut = new LinkedHashMap<>();
        for (Map.Entry<String, long[]> entry : groups.entrySet()) {
            Map<String, Object> group = new LinkedHashMap<>();
            group.put("count", entry.getValue()[0]);
            group.put("size", entry.getValue()[1]);
            group.put("size_human", humanSize(entry.getValue()[1]));
            groupsOut.put(entry.getKey(), group);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("path", path);
        result.put("total_count", files.size());
        result.put("total_size", totalSize);
        result.put("total_size_human", humanSize(totalSize));
        result.put("groups", groupsOut);
        result.put("top", top);
        result.put("skipped", skipped);
        return result;
    }

    /** 文件流 payload（Python stream_files 形状）。 */
    private Map<String, Object> filesPayload(ScanTask task, List<FileEntry> newFiles, int nextIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("items", newFiles.stream().map(FileEntry::toApiMap).toList());
        payload.put("fromIndex", nextIndex);
        payload.put("scanned", task.getScanned());
        payload.put("totalBytes", task.getTotalBytes());
        payload.put("totalBytesHuman", humanSize(task.getTotalBytes()));
        payload.put("state", task.getStatus());
        payload.put("error", task.getError());
        return payload;
    }

    /** 返回 from_index 之后新增的文件与新的 from_index。 */
    private FileSlice filesSince(ScanTask task, int fromIndex) {
        synchronized (task) {
            List<FileEntry> all = task.getFiles();
            int start = Math.max(0, Math.min(fromIndex, all.size()));
            List<FileEntry> newFiles = new ArrayList<>(all.subList(start, all.size()));
            return new FileSlice(newFiles, all.size());
        }
    }

    // ------------------------------------------------------------------ //
    // 9. 工具
    // ------------------------------------------------------------------ //

    private void startDaemon(String name, Runnable runnable) {
        Thread thread = new Thread(runnable, name);
        thread.setDaemon(true);
        thread.start();
    }

    private void emit(SseEmitter emitter, String event, String id, String dataJson) throws IOException {
        SseEmitter.SseEventBuilder builder = SseEmitter.event().name(event).data(dataJson);
        if (id != null) {
            builder.id(id);
        }
        emitter.send(builder);
    }

    private void completeQuietly(SseEmitter emitter) {
        try {
            emitter.complete();
        } catch (IllegalStateException ignored) {
            // 已关闭：忽略
        }
    }

    private void sleepSeconds(double seconds) {
        try {
            long ms = (long) (seconds * 1000);
            Thread.sleep(Math.max(ms, 100));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static boolean isTerminal(String status) {
        return status != null && TERMINAL_STATES.contains(status);
    }

    private static boolean isDoneOrCancelled(String status) {
        return "done".equals(status) || "cancelled".equals(status);
    }

    private String now() {
        return LocalDateTime.now().toString();
    }

    /** 已耗时秒数；未开始为 0。 */
    private double elapsedSeconds(ScanTask task) {
        if (task.getStartedAt() == null) {
            return 0.0;
        }
        LocalDateTime start = parse(task.getStartedAt());
        LocalDateTime end = task.getEndedAt() != null ? parse(task.getEndedAt()) : LocalDateTime.now();
        return Duration.between(start, end).toMillis() / 1000.0;
    }

    private LocalDateTime parse(String text) {
        try {
            return LocalDateTime.parse(text);
        } catch (RuntimeException e) {
            return LocalDateTime.now();
        }
    }

    private static double round3(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    private static void registerKind(String kind, String... extensions) {
        for (String extension : extensions) {
            EXT_TO_KIND.put(extension, kind);
        }
    }

    private static String kindOf(Path path) {
        String name = path.getFileName().toString().toLowerCase(Locale.ROOT);
        if (NAME_TO_KIND.contains(name)) {
            return "code";
        }
        return EXT_TO_KIND.getOrDefault(suffixOf(path).toLowerCase(Locale.ROOT), "other");
    }

    private static String suffixOf(Path path) {
        String name = path.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot);
    }

    /** 字节数转人类可读（与 Python file_kind.human_size 对齐，保留两位小数）。 */
    private static String humanSize(long n) {
        if (n < 0) {
            return "-" + humanSize(-n);
        }
        double value = n;
        String[] units = {"B", "KB", "MB", "GB", "TB", "PB"};
        for (String unit : units) {
            if (value < 1024) {
                if ("B".equals(unit)) {
                    return (long) value + " B";
                }
                return String.format(Locale.ROOT, "%.2f %s", value, unit);
            }
            value /= 1024;
        }
        return String.format(Locale.ROOT, "%.2f EB", value);
    }

    /** 一轮文件增量：新增文件 + 新的 from_index。 */
    private record FileSlice(List<FileEntry> newFiles, int nextIndex) {
    }
}
