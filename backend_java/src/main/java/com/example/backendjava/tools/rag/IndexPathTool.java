// 模块说明：index_path 工具（对应 Python file_read_tool.py 的 index_path）。
package com.example.backendjava.tools.rag;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法
import com.example.backendjava.tools.WalkStats; // 项目内：目录遍历统计（跳过数量/是否截断）

// 标准库：ArrayList 待导入文件
import java.util.ArrayList;
// 标准库：Files 判断文件/目录
import java.nio.file.Files;
// 标准库：LinkedHashMap 保持跳过类型的展示顺序
import java.util.LinkedHashMap;
// 标准库：List 文件列表与待校验路径
import java.util.List;
// 标准库：Locale 后缀小写
import java.util.Locale;
// 标准库：Map 统计与弹窗参数
import java.util.Map;
// 标准库：Path 路径
import java.nio.file.Path;
// 标准库：Set 文件夹批量导入接受的后缀
import java.util.Set;
// 第三方（Spring）：延迟获取可选 Bean
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：RAG 入库结果
import com.example.backendjava.dto.RagDtos;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：RAG 服务接口
import com.example.backendjava.service.RagService;

/**
 * 把文件或文件夹导入 RAG 知识库。
 */
@Component
public class IndexPathTool extends AbstractGuardedTool {

    /** 递归遍历时最多收集的文件数。 */
    private static final int MAX_WALK_FILES = 50_000;

    /**
     * 导入「整个文件夹」时只收这些文档类后缀，避免把代码、日志、lock 文件一股脑灌进知识库。
     *
     * <p>Python 侧由解析注册表动态派生；Java 侧还没有解析注册表，先用这份静态清单，
     * 单独指定某个文件时不受此限制（只要能读成文本就允许导入）。</p>
     */
    private static final Set<String> FOLDER_INDEX_SUFFIXES = Set.of(
            // 纯文本类
            ".txt", ".md", ".markdown",
            // 文档类
            ".pdf",
            ".docx", ".doc", ".dot", ".wps", ".wpt", ".docm",
            ".xlsx", ".xls", ".xlt", ".xlsm",
            ".pptx", ".ppt", ".pps", ".pot"
    );

    /** RAG 服务；可能还没有实现 Bean。 */
    private final ObjectProvider<RagService> ragServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime           工具执行关卡
     * @param ragServiceProvider RAG 服务提供者
     */
    public IndexPathTool(ToolRuntime runtime, ObjectProvider<RagService> ragServiceProvider) {
        super(runtime);
        this.ragServiceProvider = ragServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "index_path";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "把文件或文件夹导入 RAG 知识库（解析、切片、向量化），之后可以用 rag_search 检索。"
                + "适用：用户明确要求导入/加入知识库/建立索引，或者文档太大无法用 read_file 读完、需要检索时。"
                + "只想看看/统计/读一下时不要调用本工具。文件夹只导入常见文档类文件；"
                + "单独指定的文件只要是文本都能导入。内容未变化的文件会自动跳过。";
    }

    /**
     * 把参数翻译成一次待裁决的写操作（只读解析路径，不真正入库）。
     *
     * @param args 工具入参：path / force
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String raw = ToolArgs.requiredString(args, "path");
        RagService service = ragServiceProvider.getIfAvailable();
        Path parsed = IndexedDocSupport.parsePath(raw);
        if (service == null && (parsed == null || !parsed.isAbsolute())) {
            // 没有 RAG 服务时无法把「已导入文件名」换算成路径，直接给出可执行的建议
            throw new IllegalArgumentException("RAG 服务尚未实现，请提供要导入文件的绝对路径");
        }
        Path path = IndexedDocSupport.resolveImportPath(service, raw);
        return new ToolAction(
                name(),
                ToolKind.WRITE,
                path.toString(),
                List.of(path),
                Map.of("path", path.toString(),
                        "force", ToolArgs.optionalBool(args, "force", false)),
                "AI 将把 " + path + " 导入知识库（解析、切片、向量化）"
        );
    }

    /**
     * 执行导入：收集文件 -> 逐个入库 -> 汇总成功/失败/跳过。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 导入统计
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        RagService service = ragServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("RAG 服务尚未实现，当前无法导入知识库");
        }
        Path path = action.paths().get(0);
        boolean force = ToolArgs.optionalBool(args, "force", false);
        try {
            if (!Files.exists(path)) {
                return ToolResult.fail("路径不存在: " + path);
            }
            CollectResult collected = collectIndexable(path);
            String skippedMessage = collected.skipped().isEmpty()
                    ? ""
                    : "；跳过不支持的类型：" + collected.skipped().entrySet().stream()
                    .map(entry -> entry.getKey() + " " + entry.getValue() + " 个")
                    .reduce((left, right) -> left + "，" + right).orElse("");
            if (collected.files().isEmpty()) {
                return ToolResult.fail("没有可导入的文档: " + path + skippedMessage);
            }

            // 逐个导入，遇到失败继续，最后汇总（避免第 100 个失败导致前 99 个白导）
            Map<String, Integer> actions = new LinkedHashMap<>();
            List<String> failures = new ArrayList<>();
            long totalChunks = 0;
            long totalNew = 0;
            for (Path file : collected.files()) {
                try {
                    RagDtos.IndexResult result = service.indexFile(new RagDtos.IndexFileRequest(
                            file.toString(), null, null, force));
                    actions.merge(result.action(), 1, Integer::sum);
                    totalChunks += result.totalChunks();
                    totalNew += result.newChunks();
                } catch (RuntimeException e) {
                    failures.add(file.getFileName() + ": " + e.getMessage());
                }
            }

            int okCount = actions.values().stream().mapToInt(Integer::intValue).sum();
            if (okCount == 0) {
                return ToolResult.fail("全部导入失败: "
                        + String.join("; ", failures.subList(0, Math.min(3, failures.size()))));
            }

            String message = path + "：成功 " + okCount + "/" + collected.files().size() + " 个文件"
                    + "（新建 " + actions.getOrDefault("created", 0)
                    + "，更新 " + actions.getOrDefault("updated", 0)
                    + "，未变化跳过 " + actions.getOrDefault("skipped", 0) + "），"
                    + "总切片 " + totalChunks + "，新向量 " + totalNew + skippedMessage;
            if (!failures.isEmpty()) {
                message += "；" + failures.size() + " 个失败: "
                        + String.join("; ", failures.subList(0, Math.min(3, failures.size())));
            }
            return ToolResult.ok(message);
        } catch (RuntimeException e) {
            return ToolResult.fail("导入失败: " + e.getMessage());
        }
    }

    /**
     * 收集待导入的文件，并统计被跳过的文件类型。
     *
     * <ul>
     *   <li>p 是文件：pdf/docx 或任何非二进制文本都允许（用户明确点名了这个文件）；</li>
     *   <li>p 是文件夹：只收 FOLDER_INDEX_SUFFIXES 内的文档类文件。</li>
     * </ul>
     *
     * @param path 已存在的文件或目录
     * @return 待导入文件列表 + 被跳过的后缀计数
     */
    private static CollectResult collectIndexable(Path path) {
        Map<String, Integer> skipped = new LinkedHashMap<>();
        if (Files.isRegularFile(path)) {
            String suffix = ToolUtils.suffixOf(path);
            if (ToolUtils.RICH_DOC_SUFFIXES.contains(suffix) || !ToolUtils.isBinaryFile(path)) {
                return new CollectResult(List.of(path), skipped);
            }
            skipped.merge(suffix.isEmpty() ? "(无后缀)" : suffix, 1, Integer::sum);
            return new CollectResult(List.of(), skipped);
        }
        List<Path> picked = new ArrayList<>();
        for (Path file : ToolUtils.walkFiles(path, MAX_WALK_FILES, new WalkStats())) {
            String suffix = ToolUtils.suffixOf(file).toLowerCase(Locale.ROOT);
            if (FOLDER_INDEX_SUFFIXES.contains(suffix)) {
                picked.add(file);
            } else {
                skipped.merge(suffix.isEmpty() ? "(无后缀)" : suffix, 1, Integer::sum);
            }
        }
        return new CollectResult(picked, skipped);
    }

    /**
     * 收集结果。
     *
     * @param files   待导入文件
     * @param skipped 被跳过的后缀计数
     */
    private record CollectResult(
            // 待导入文件
            List<Path> files,
            // 被跳过的后缀计数
            Map<String, Integer> skipped
    ) {
    }
}
