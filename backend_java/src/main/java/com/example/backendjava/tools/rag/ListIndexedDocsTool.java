// 模块说明：list_indexed_docs 工具（对应 Python file_read_tool.py 的 list_indexed_docs）。
package com.example.backendjava.tools.rag;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：ArrayList 结果行
import java.util.ArrayList;
// 标准库：List 文档列表与待校验路径
import java.util.List;
// 标准库：Locale 大小写过滤
import java.util.Locale;
// 标准库：Map 弹窗参数
import java.util.Map;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 第三方（Spring）：延迟获取可选 Bean（RAG 服务可能尚未实现）
import org.springframework.beans.factory.ObjectProvider;
// 项目内：RAG 文档 DTO
import com.example.backendjava.dto.RagDtos;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：RAG 服务接口
import com.example.backendjava.service.RagService;

/**
 * 列出知识库里已导入的文档。
 */
@Component
public class ListIndexedDocsTool extends AbstractGuardedTool {

    /** 默认最多列出多少条。 */
    private static final int DEFAULT_LIMIT = 50;

    /** RAG 服务；可能还没有实现 Bean。 */
    private final ObjectProvider<RagService> ragServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime           工具执行关卡
     * @param ragServiceProvider RAG 服务提供者
     */
    public ListIndexedDocsTool(ToolRuntime runtime, ObjectProvider<RagService> ragServiceProvider) {
        super(runtime);
        this.ragServiceProvider = ragServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "list_indexed_docs";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "列出 RAG 知识库里已经导入的文档：文件名、完整路径、切片数、导入时间。"
                + "适用：用户问知识库里有哪些文档 / 我导入过什么，或者在删除、限定检索范围之前"
                + "先确认目标的确切文件名（文件名写错是最常见的失败原因）。只读。";
    }

    /**
     * 构造只读操作（无参数、无路径）。
     *
     * @param args 工具入参：keyword / limit
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        return new ToolAction(
                name(),
                ToolKind.READ,
                "知识库文档清单",
                List.of(),
                Map.of(),
                "读取知识库已导入文档列表"
        );
    }

    /**
     * 执行查询：按文件名做子串过滤，再按限制条数输出。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 文档列表（含总数）
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        RagService service = ragServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("RAG 服务尚未实现，当前无法查询知识库文档列表");
        }
        String keyword = ToolArgs.optionalString(args, "keyword", "");
        int limit = Math.max(1, ToolArgs.optionalInt(args, "limit", DEFAULT_LIMIT));
        try {
            List<RagDtos.RagDocument> docs = IndexedDocSupport.allDocs(service);
            String lower = keyword.toLowerCase(Locale.ROOT);
            if (!lower.isEmpty()) {
                docs = docs.stream()
                        .filter(doc -> IndexedDocSupport.displayName(doc)
                                .toLowerCase(Locale.ROOT).contains(lower))
                        .toList();
            }
            if (docs.isEmpty()) {
                String scopeDesc = lower.isEmpty() ? "" : "文件名含「" + keyword + "」的";
                return ToolResult.ok("知识库里没有" + scopeDesc + "已导入的文档");
            }
            List<String> lines = new ArrayList<>();
            int shown = Math.min(limit, docs.size());
            for (int i = 0; i < shown; i++) {
                RagDtos.RagDocument doc = docs.get(i);
                String size = doc.fileSize() == null ? "大小未知" : ToolUtils.humanSize(doc.fileSize());
                lines.add("[" + (i + 1) + "] " + IndexedDocSupport.displayName(doc)
                        + "（" + doc.chunks() + " 个切片，" + size + "）\n    " + doc.source());
            }
            String more = docs.size() > limit
                    ? "\n…另有 " + (docs.size() - limit) + " 篇未列出"
                    : "";
            return ToolResult.ok("知识库里共有 " + docs.size() + " 篇已导入文档：\n"
                    + String.join("\n", lines) + more);
        } catch (RuntimeException e) {
            return ToolResult.fail("查询知识库文档列表失败: " + e.getMessage());
        }
    }
}
