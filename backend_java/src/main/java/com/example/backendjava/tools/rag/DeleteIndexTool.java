// 模块说明：delete_index 工具（对应 Python file_read_tool.py 的 delete_index）。
//
// 与 Python 的差异：Python 在工具内部再调一次 ask_user 列出将删除的文档；
// Java 侧的统一关卡已经按策略要求确认（WRITE + requireConfirm），
// 因此这里不再重复弹窗，避免用户点两次。
package com.example.backendjava.tools.rag;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）

// 标准库：ArrayList 文档 id 列表
import java.util.ArrayList;
// 标准库：List 文件名与待校验路径
import java.util.List;
// 标准库：Map 弹窗参数与删除结果
import java.util.Map;
// 第三方（Spring）：延迟获取可选 Bean
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：RAG 文档 DTO
import com.example.backendjava.dto.RagDtos;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：RAG 服务接口
import com.example.backendjava.service.RagService;

/**
 * 从 RAG 知识库删除文件/文件夹的导入记录（磁盘上的原文件不受影响）。
 */
@Component
public class DeleteIndexTool extends AbstractGuardedTool {

    /** RAG 服务；可能还没有实现 Bean。 */
    private final ObjectProvider<RagService> ragServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime           工具执行关卡
     * @param ragServiceProvider RAG 服务提供者
     */
    public DeleteIndexTool(ToolRuntime runtime, ObjectProvider<RagService> ragServiceProvider) {
        super(runtime);
        this.ragServiceProvider = ragServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "delete_index";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "从 RAG 知识库删除某个文件、或某个文件夹下所有文件的导入记录"
                + "（切片和向量一起删；磁盘上的原文件不受影响）。"
                + "支持两种写法：已导入文档的文件名（如 note.md），或文件/文件夹的绝对路径。"
                + "这是不可恢复的操作，系统会自动请用户确认。";
    }

    /**
     * 构造写操作：目标可能是一个文件名，无法在裁决前安全解析成路径，
     * 因此这里只把原始参数放进预览（与 Python 的 Policy 不声明 path_args 一致）。
     *
     * @param args 工具入参：path
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String raw = ToolArgs.requiredString(args, "path");
        return new ToolAction(
                name(),
                ToolKind.WRITE,
                raw,
                List.of(),
                Map.of("path", raw),
                "AI 将从知识库删除与「" + raw + "」匹配的导入记录（磁盘原文件不受影响）"
        );
    }

    /**
     * 执行删除：匹配文档 -> 批量删除 -> 汇总。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 删除结果
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        RagService service = ragServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("RAG 服务尚未实现，当前无法删除知识库记录");
        }
        String raw = ToolArgs.requiredString(args, "path");
        try {
            IndexedDocSupport.MatchResult matched = IndexedDocSupport.match(service, List.of(raw));
            if (matched.docs().isEmpty()) {
                return ToolResult.fail("知识库中没有与「" + raw + "」匹配的导入记录。"
                        + "可以先调用 list_indexed_docs 查看已导入文档的确切名字");
            }
            List<String> names = new ArrayList<>();
            for (RagDtos.RagDocument doc : matched.docs().subList(0, Math.min(20, matched.docs().size()))) {
                names.add("  - " + doc.source());
            }
            String more = matched.docs().size() > 20
                    ? "\n  …共 " + matched.docs().size() + " 篇"
                    : "";
            List<Long> ids = matched.docs().stream().map(RagDtos.RagDocument::id).toList();
            Map<String, Object> result = service.batchDelete(ids);
            Object deletedValue = result == null ? null : result.get("deleted");
            int deleted = deletedValue instanceof Number number ? number.intValue() : ids.size();
            return ToolResult.ok("已从知识库删除 " + deleted + " 篇文档：\n"
                    + String.join("\n", names) + more);
        } catch (RuntimeException e) {
            return ToolResult.fail("删除失败: " + e.getMessage());
        }
    }
}
