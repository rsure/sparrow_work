// 模块说明：glob 工具（对应 Python glob_tool.py）。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法
import com.example.backendjava.tools.WalkStats; // 项目内：目录遍历统计（跳过数量/是否截断）

// 标准库：Files 判断目录
import java.nio.file.Files;
// 标准库：Path 路径
import java.nio.file.Path;
// 标准库：ArrayList 收集命中
import java.util.ArrayList;
// 标准库：List 待裁决路径与结果行
import java.util.List;
// 标准库：Map 弹窗预览
import java.util.Map;
// 标准库：Pattern 实现 glob 到正则的转换（PathMatcher 在 Windows 上的大小写行为不稳定）
import java.util.regex.Pattern;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 按路径模式查找文件。
 */
@Component
public class GlobTool extends AbstractGuardedTool {

    /** 遍历文件数上限，防止用户给盘符根目录时长时间卡住。 */
    private static final int MAX_WALK_FILES = 50_000;

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public GlobTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "glob";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "在目录下按路径模式查找文件，返回匹配文件的相对路径、大小与修改时间。"
                + "适用：找出所有 .vue 文件、src 下面有几个测试文件。模式相对 root："
                + "* 匹配一段、** 匹配任意层目录、? 匹配一个字符。例：**/*.vue、*.log、src/**/*.ts。"
                + "只看路径模式、不读文件内容：要按内容关键字找请用 grep_files。";
    }

    /**
     * 把参数翻译成一次待裁决的只读操作。
     *
     * @param args 工具入参：root / pattern / max_results
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path root = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "root"));
        String pattern = ToolArgs.requiredString(args, "pattern");
        return new ToolAction(
                name(),
                ToolKind.READ,
                root + " / " + pattern,
                List.of(root),
                Map.of("root", root.toString(), "pattern", pattern),
                "在 " + root + " 下按模式 " + pattern + " 查找文件"
        );
    }

    /**
     * 执行查找：遍历后把相对路径转成 POSIX 风格字符串，再做大小写不敏感匹配。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 匹配文件列表
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        try {
            Path base = action.paths().get(0);
            if (!Files.isDirectory(base)) {
                return ToolResult.fail("不是目录: " + base);
            }
            String pattern = ToolArgs.requiredString(args, "pattern");
            int maxResults = Math.max(1, ToolArgs.optionalInt(args, "max_results", 100));
            Pattern regex = globToPattern(pattern);

            WalkStats stats = new WalkStats();
            List<Path> hits = new ArrayList<>();
            for (Path file : ToolUtils.walkFiles(base, MAX_WALK_FILES, stats)) {
                // Path.match 不支持 ** 的跨目录语义，且对大小写敏感；统一转 POSIX 字符串再匹配
                String relative = base.relativize(file).toString().replace('\\', '/');
                if (regex.matcher(relative).matches()) {
                    hits.add(file);
                }
            }

            StringBuilder summary = new StringBuilder("在 " + base + " 下按模式「" + pattern
                    + "」匹配到 " + hits.size() + " 个文件");
            if (stats.getSkippedDirs() > 0) {
                summary.append("（跳过 ").append(stats.getSkippedDirs()).append(" 个依赖/缓存目录）");
            }
            if (stats.getSkippedSystem() > 0) {
                summary.append("（跳过 ").append(stats.getSkippedSystem()).append(" 个系统文件/目录）");
            }
            if (stats.isTruncated()) {
                summary.append("；⚠ 遍历文件数达到 ").append(MAX_WALK_FILES).append(" 上限，结果可能不全");
            }
            if (hits.isEmpty()) {
                return ToolResult.ok(summary.toString());
            }
            List<String> lines = new ArrayList<>();
            int shown = Math.min(maxResults, hits.size());
            for (int i = 0; i < shown; i++) {
                Path file = hits.get(i);
                lines.add("[" + (i + 1) + "] " + base.relativize(file)
                        + "  " + ToolUtils.describeFile(file));
            }
            if (hits.size() > maxResults) {
                lines.add("…另有 " + (hits.size() - maxResults)
                        + " 个未列出（可调大 max_results 或缩小模式）");
            }
            return ToolResult.ok(summary + "\n" + String.join("\n", lines));
        } catch (RuntimeException e) {
            return ToolResult.fail("查找失败: " + e.getMessage());
        }
    }

    /**
     * 把 glob 模式转成大小写不敏感的正则。
     *
     * <p>语义与 Python fnmatch 对齐：* 不跨目录、** 跨任意层、? 单个字符、
     * [seq] 字符集合。转换而不是直接用 PathMatcher，是为了统一 Windows/Unix 的
     * 大小写行为，并让 **\/ 能匹配零层目录。</p>
     *
     * @param glob 原始 glob 模式
     * @return 编译好的正则
     */
    public static Pattern globToPattern(String glob) {
        String source = glob.replace('\\', '/');
        StringBuilder regex = new StringBuilder("^");
        for (int i = 0; i < source.length(); i++) {
            char c = source.charAt(i);
            if (c == '*') {
                if (i + 1 < source.length() && source.charAt(i + 1) == '*') {
                    // 吞掉连续的 *；"**/" 还要允许零层目录
                    while (i + 1 < source.length() && source.charAt(i + 1) == '*') {
                        i++;
                    }
                    if (i + 1 < source.length() && source.charAt(i + 1) == '/') {
                        i++;
                        regex.append("(?:.*/)?");
                    } else {
                        regex.append(".*");
                    }
                } else {
                    regex.append("[^/]*");
                }
            } else if (c == '?') {
                regex.append("[^/]");
            } else if (c == '[') {
                int end = source.indexOf(']', i + 1);
                if (end > i + 1) {
                    String content = source.substring(i + 1, end);
                    // fnmatch 用 [!seq] 表示取反，正则里对应 [^seq]
                    if (content.startsWith("!")) {
                        content = "^" + content.substring(1);
                    }
                    regex.append('[').append(content).append(']');
                    i = end;
                } else {
                    regex.append("\\[");
                }
            } else if ("\\.^$|(){}]+".indexOf(c) >= 0) {
                regex.append('\\').append(c);
            } else {
                regex.append(c);
            }
        }
        regex.append('$');
        return Pattern.compile(regex.toString(), Pattern.CASE_INSENSITIVE);
    }
}
