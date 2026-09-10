// 模块说明：grep_files 工具（对应 Python file_read_tool.py 的 grep_files）。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.TextReadResult; // 项目内：文本读取结果（正文 + 读取说明）

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法
import com.example.backendjava.tools.WalkStats; // 项目内：目录遍历统计（跳过数量/是否截断）

// 标准库：Files 判断类型与读大小
import java.nio.file.Files;
// 标准库：IOException 文件系统异常
import java.io.IOException;
// 标准库：List 保存候选文件与命中结果
import java.util.ArrayList;
import java.util.List;
// 标准库：Locale 大小写转换
import java.util.Locale;
// 标准库：Map 构造待裁决操作
import java.util.Map;
// 标准库：Path 路径
import java.nio.file.Path;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 在磁盘目录里按关键字找文件：同时匹配文件名和文件内容（不区分大小写）。
 */
@Component
public class GrepFilesTool extends AbstractGuardedTool {

    /** 递归遍历时最多扫描的文件数，防止用户给一个磁盘根目录导致长时间卡住。 */
    private static final int MAX_WALK_FILES = 50_000;

    /** 读取内容时单个文件的体积上限（5MB）；更大的文件只做文件名匹配。 */
    private static final long GREP_MAX_FILE_BYTES = 5L * 1024 * 1024;

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public GrepFilesTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "grep_files";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "在磁盘目录里按关键字找文件：同时匹配文件名和文件内容（不区分大小写），"
                + "不要求文件已导入知识库。适用：XXX 写在哪个文件里、哪些文件提到了 XXX、"
                + "找名字带 XXX 的文件。结果给出完整路径和命中行。关键字是普通子串匹配（不是正则）。";
    }

    /**
     * 把参数翻译成一次待裁决的只读操作。
     *
     * @param args 工具入参：root / keyword / max_results
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path root = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "root"));
        String keyword = ToolArgs.requiredString(args, "keyword");
        return new ToolAction(
                name(),
                ToolKind.READ,
                root.toString(),
                List.of(root),
                Map.of("root", root.toString(), "keyword", keyword),
                "在 " + root + " 中搜索关键字「" + keyword + "」"
        );
    }

    /**
     * 执行搜索：文件名与内容同时匹配，每个命中文件最多展示 3 行。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 命中文件列表（路径 + 命中行）
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        try {
            Path base = action.paths().get(0);
            String keyword = ToolArgs.requiredString(args, "keyword");
            String kw = keyword.toLowerCase(Locale.ROOT);
            int maxResults = Math.max(1, ToolArgs.optionalInt(args, "max_results", 30));
            if (!Files.exists(base)) {
                return ToolResult.fail("路径不存在: " + base);
            }

            WalkStats stats = new WalkStats();
            List<Path> candidates = Files.isRegularFile(base)
                    ? List.of(base)
                    : ToolUtils.walkFiles(base, MAX_WALK_FILES, stats);

            List<String> results = new ArrayList<>();
            int scanned = 0;
            for (Path file : candidates) {
                if (results.size() >= maxResults) {
                    stats.markTruncated();
                    break;
                }
                scanned++;
                boolean nameHit = file.getFileName().toString().toLowerCase(Locale.ROOT).contains(kw);
                List<String> lineHits = new ArrayList<>();
                try {
                    // 太大的文件只比较文件名，不读内容
                    if (Files.size(file) <= GREP_MAX_FILE_BYTES) {
                        TextReadResult read = ToolUtils.readTextAny(file);
                        if (read.text() != null) {
                            String[] lines = read.text().split("\\R", -1);
                            for (int i = 0; i < lines.length; i++) {
                                if (lines[i].toLowerCase(Locale.ROOT).contains(kw)) {
                                    String shown = lines[i].strip();
                                    if (shown.length() > 160) {
                                        shown = shown.substring(0, 160);
                                    }
                                    lineHits.add("    第 " + (i + 1) + " 行: " + shown);
                                    // 每个文件最多展示 3 行，防止刷屏
                                    if (lineHits.size() >= 3) {
                                        break;
                                    }
                                }
                            }
                        }
                    }
                } catch (IOException ignored) {
                    // 单个文件读不了：跳过内容匹配，只看文件名
                }
                if (nameHit || !lineHits.isEmpty()) {
                    String tag = nameHit && !lineHits.isEmpty()
                            ? "文件名+内容"
                            : (nameHit ? "文件名" : "内容");
                    List<String> block = new ArrayList<>();
                    block.add("[" + tag + "命中] " + file);
                    block.addAll(lineHits);
                    results.add(String.join("\n", block));
                }
            }

            StringBuilder summary = new StringBuilder("在 " + base + " 中扫描 " + scanned
                    + " 个文件，命中 " + results.size() + " 个");
            if (stats.getSkippedDirs() > 0) {
                summary.append("（跳过 ").append(stats.getSkippedDirs()).append(" 个依赖/缓存目录）");
            }
            if (stats.getSkippedSystem() > 0) {
                summary.append("（跳过 ").append(stats.getSkippedSystem()).append(" 个系统文件/目录）");
            }
            if (stats.isTruncated()) {
                summary.append("；⚠ 已达到上限，可能还有更多结果");
            }
            if (results.isEmpty()) {
                return ToolResult.ok(summary + "。没有找到包含「" + keyword + "」的文件");
            }
            return ToolResult.ok(summary + "\n" + String.join("\n", results));
        } catch (RuntimeException e) {
            return ToolResult.fail("搜索失败: " + e.getMessage());
        }
    }
}
