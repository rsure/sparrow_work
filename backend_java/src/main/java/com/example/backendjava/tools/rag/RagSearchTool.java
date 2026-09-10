// 模块说明：rag_search 工具（对应 Python file_read_tool.py 的 rag_search）。
package com.example.backendjava.tools.rag;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）

// 标准库：ArrayList 结果片段
import java.util.ArrayList;
// 标准库：List 检索结果与 scope 参数
import java.util.List;
// 标准库：Locale 数字格式化
import java.util.Locale;
// 标准库：Map 弹窗参数
import java.util.Map;
// 第三方（Spring）：延迟获取可选 Bean
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：RAG 检索 DTO
import com.example.backendjava.dto.RagDtos;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：RAG 服务接口
import com.example.backendjava.service.RagService;

/**
 * 在 RAG 知识库中检索与问题相关的片段。
 */
@Component
public class RagSearchTool extends AbstractGuardedTool {

    /** 默认返回片段条数。 */
    private static final int DEFAULT_TOP_K = 5;

    /** 一次最多返回多少条片段。 */
    private static final int MAX_TOP_K = 100;

    /** RAG 服务；可能还没有实现 Bean。 */
    private final ObjectProvider<RagService> ragServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime           工具执行关卡
     * @param ragServiceProvider RAG 服务提供者
     */
    public RagSearchTool(ToolRuntime runtime, ObjectProvider<RagService> ragServiceProvider) {
        super(runtime);
        this.ragServiceProvider = ragServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "rag_search";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "在 RAG 知识库（已导入的文档）中检索与问题相关的片段，结果带完整文件路径和相关度。"
                + "适用：基于已导入文档回答问题、找关于 XXX 的内容在哪个文件。"
                + "用户指定了文档/文件夹时，务必传 scope 限定范围，避免其它文档混进来。"
                + "检索结果为空时如实告知用户，不要编造。";
    }

    /**
     * 构造只读操作。
     *
     * @param args 工具入参：query / top_k / scope
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String query = ToolArgs.requiredString(args, "query");
        return new ToolAction(
                name(),
                ToolKind.READ,
                "知识库检索：" + query,
                List.of(),
                Map.of("query", query,
                        "top_k", ToolArgs.optionalInt(args, "top_k", DEFAULT_TOP_K)),
                "AI 将在知识库中检索：「" + query + "」"
        );
    }

    /**
     * 执行检索：解析 scope -> 调 RAG 服务 -> 格式化命中片段。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 片段列表（路径、片段序号、相关度、原文）
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        RagService service = ragServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("RAG 服务尚未实现，当前无法检索知识库");
        }
        String query = ToolArgs.requiredString(args, "query");
        int topK = Math.max(1, Math.min(
                ToolArgs.optionalInt(args, "top_k", DEFAULT_TOP_K), MAX_TOP_K));
        List<String> scope = ToolArgs.stringList(args, "scope");
        try {
            List<String> sources = null;
            String scopeMessage = "全部知识库";
            if (!scope.isEmpty()) {
                IndexedDocSupport.ScopeResult resolved = IndexedDocSupport.resolveScope(service, scope);
                if (resolved.sources().isEmpty()) {
                    return ToolResult.fail("范围 " + scope + " 内没有已导入的文档；"
                            + "可以先用 list_indexed_docs 确认文档名，或用 index_path 把它导进来");
                }
                sources = resolved.sources();
                scopeMessage = sources.size() + " 篇指定文档";
                if (!resolved.missing().isEmpty()) {
                    scopeMessage += "（未找到: " + resolved.missing() + "）";
                }
            }

            List<RagDtos.SearchHit> hits = service.search(new RagDtos.SearchRequest(
                    query, topK, null, null, sources));
            if (hits == null || hits.isEmpty()) {
                return ToolResult.ok("在" + scopeMessage + "中未检索到与「" + query + "」相关的内容");
            }
            List<String> parts = new ArrayList<>();
            for (int i = 0; i < hits.size(); i++) {
                RagDtos.SearchHit hit = hits.get(i);
                parts.add("[" + (i + 1) + "] " + hit.source()
                        + "（片段 #" + hit.chunkIndex() + "，相关度 "
                        + String.format(Locale.ROOT, "%.3f", hit.score()) + "）\n" + hit.text());
            }
            return ToolResult.ok("在" + scopeMessage + "中检索到 " + hits.size()
                    + " 个片段：\n\n" + String.join("\n\n", parts));
        } catch (RuntimeException e) {
            return ToolResult.fail("检索失败: " + e.getMessage());
        }
    }
}
