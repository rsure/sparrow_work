// 模块说明：list_dir 工具（对应 Python file_read_tool.py 的 list_dir）。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法
import com.example.backendjava.tools.WalkStats; // 项目内：目录遍历统计（跳过数量/是否截断）

// 标准库：ArrayList 收集目录项
import java.util.ArrayList;
// 标准库：Comparator 定义「目录在前、文件名升序」的排序
import java.util.Comparator;
// 标准库：DirectoryStream 只列当前这一层
import java.nio.file.DirectoryStream;
// 标准库：Files 判断类型、读大小
import java.nio.file.Files;
// 标准库：IOException 文件系统异常
import java.io.IOException;
// 标准库：List 保存目录项与明细行
import java.util.List;
// 标准库：Locale 让大小写转换不受本机语言环境影响
import java.util.Locale;
// 标准库：Map 保存后缀计数
import java.util.Map;
// 标准库：Path 目录/文件路径
import java.nio.file.Path;
// 第三方（Spring）：声明为受管组件，自动登记进 DefaultToolRegistry
import org.springframework.stereotype.Component;
// 项目内：工具执行结果（统一 OK/FAIL 前缀）
import com.example.backendjava.dto.ToolResult;

/**
 * 列出目录内容并给出统计；传入文件则返回该文件的元信息。
 */
@Component
public class ListDirTool extends AbstractGuardedTool {

    /** 递归统计时最多遍历的文件数，防止用户给一个磁盘根目录导致长时间卡住。 */
    private static final int MAX_WALK_FILES = 50_000;

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public ListDirTool(ToolRuntime runtime) {
        super(runtime);
    }

    /**
     * 工具名：模型调用时使用。
     *
     * @return "list_dir"
     */
    @Override
    public String name() {
        return "list_dir";
    }

    /**
     * 工具说明：告诉模型什么时候该用它。
     *
     * @return 说明文本
     */
    @Override
    public String description() {
        return "列出目录内容并给出统计（文件数、子目录数、总大小、文件类型分布）；"
                + "传入文件则返回该文件的元信息。适用：查看文件夹里有什么、比较几个文件夹谁更大、"
                + "找某类文件、了解目录结构。需要比较多个目录时，对每个目录分别调用一次。只读。";
    }

    /**
     * 把参数翻译成一次待裁决的只读操作。
     *
     * @param args 工具入参：path / recursive / max_entries
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path path = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "path"));
        return new ToolAction(
                name(),
                ToolKind.READ,
                path.toString(),
                List.of(path),
                Map.of("path", path.toString()),
                "列出目录 " + path + " 的内容"
        );
    }

    /**
     * 执行列目录：非递归只看当前层，递归统计整棵子树。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 统计信息 + 明细
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        try {
            Path path = action.paths().get(0);
            if (!Files.exists(path)) {
                return ToolResult.fail("路径不存在: " + path);
            }
            if (Files.isRegularFile(path)) {
                return ToolResult.ok("这是一个文件: " + path + "\n" + ToolUtils.describeFile(path));
            }
            boolean recursive = ToolArgs.optionalBool(args, "recursive", false);
            int maxEntries = Math.max(1, ToolArgs.optionalInt(args, "max_entries", 100));
            return recursive
                    ? listRecursive(path, maxEntries)
                    : listOneLevel(path, maxEntries);
        } catch (RuntimeException e) {
            return ToolResult.fail("列目录失败: " + e.getMessage());
        }
    }

    /**
     * 只列当前这一层：先剔除系统项，再目录在前、文件在后排序。
     *
     * @param path       目录路径
     * @param maxEntries 最多列出多少条明细
     * @return 工具结果
     */
    private ToolResult listOneLevel(Path path, int maxEntries) {
        List<Path> all = new ArrayList<>();
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(path)) {
            for (Path child : stream) {
                all.add(child);
            }
        } catch (IOException e) {
            return ToolResult.fail("读取目录失败: " + e.getMessage());
        }
        List<Path> children = all.stream()
                .filter(child -> ToolUtils.systemPathReason(child) == null)
                .sorted(Comparator
                        .comparing((Path child) -> !Files.isDirectory(child))
                        .thenComparing(child -> child.getFileName().toString().toLowerCase(Locale.ROOT)))
                .toList();
        int hiddenSystem = all.size() - children.size();
        long totalSize = 0L;
        Map<String, Integer> suffixCounts = ToolUtils.newSuffixCounter();
        int dirCount = 0;
        int fileCount = 0;
        for (Path child : children) {
            if (Files.isDirectory(child)) {
                dirCount++;
                continue;
            }
            fileCount++;
            try {
                totalSize += Files.size(child);
            } catch (IOException ignored) {
                // 单个文件读不到大小不影响整体统计
            }
            String suffix = ToolUtils.suffixOf(child);
            suffixCounts.merge(suffix.isEmpty() ? "(无后缀)" : suffix, 1, Integer::sum);
        }
        StringBuilder header = new StringBuilder("目录 " + path + "（仅当前层）：子目录 " + dirCount
                + " 个，文件 " + fileCount + " 个，文件总大小 " + ToolUtils.humanSize(totalSize));
        if (hiddenSystem > 0) {
            header.append("；已隐藏 ").append(hiddenSystem).append(" 个系统文件/目录（不允许处理）");
        }
        List<String> lines = new ArrayList<>();
        for (Path child : children.subList(0, Math.min(maxEntries, children.size()))) {
            lines.add(Files.isDirectory(child)
                    ? "[目录] " + child.getFileName() + "/"
                    : "[文件] " + child.getFileName() + "  " + ToolUtils.describeFile(child));
        }
        String more = children.size() > maxEntries
                ? "\n…其余 " + (children.size() - maxEntries) + " 条未列出"
                : "";
        String body = lines.isEmpty() ? "(空目录)" : String.join("\n", lines);
        return ToolResult.ok(header + "\n类型分布（前 10）："
                + ToolUtils.topSuffixSummary(suffixCounts, 10)
                + "\n明细：\n" + body + more);
    }

    /**
     * 递归统计整棵子树：跳过依赖/缓存目录与系统项，并报告跳过了多少。
     *
     * @param path       目录路径
     * @param maxEntries 最多列出多少条明细
     * @return 工具结果
     */
    private ToolResult listRecursive(Path path, int maxEntries) {
        WalkStats stats = new WalkStats();
        List<Path> files = ToolUtils.walkFiles(path, MAX_WALK_FILES, stats);
        long totalSize = 0L;
        Map<String, Integer> suffixCounts = ToolUtils.newSuffixCounter();
        for (Path file : files) {
            try {
                totalSize += Files.size(file);
            } catch (IOException ignored) {
                // 单个文件读不到大小不影响整体统计
            }
            String suffix = ToolUtils.suffixOf(file);
            suffixCounts.merge(suffix.isEmpty() ? "(无后缀)" : suffix, 1, Integer::sum);
        }
        StringBuilder header = new StringBuilder("目录 " + path + "（递归）：文件 " + files.size()
                + " 个，总大小 " + ToolUtils.humanSize(totalSize));
        if (stats.getSkippedDirs() > 0) {
            header.append("；已跳过 ").append(stats.getSkippedDirs())
                    .append(" 个依赖/缓存目录（node_modules、.git 等）");
        }
        if (stats.getSkippedSystem() > 0) {
            header.append("；已跳过 ").append(stats.getSkippedSystem())
                    .append(" 个系统文件/目录（不允许处理）");
        }
        if (stats.isTruncated()) {
            header.append("；⚠ 文件超过 ").append(MAX_WALK_FILES).append(" 个，统计已截断、数字偏小");
        }
        List<String> lines = new ArrayList<>();
        int shown = Math.min(maxEntries, files.size());
        for (int i = 0; i < shown; i++) {
            Path file = files.get(i);
            String size;
            try {
                size = ToolUtils.humanSize(Files.size(file));
            } catch (IOException e) {
                size = "大小未知";
            }
            lines.add("[文件] " + path.relativize(file) + "  " + size);
        }
        String more = files.size() > maxEntries
                ? "\n…其余 " + (files.size() - maxEntries) + " 条未列出"
                : "";
        String body = lines.isEmpty() ? "(空目录)" : String.join("\n", lines);
        return ToolResult.ok(header + "\n类型分布（前 10）："
                + ToolUtils.topSuffixSummary(suffixCounts, 10)
                + "\n明细：\n" + body + more);
    }
}
