// 模块说明：工作区记忆的请求 DTO，对应 Python 侧 /api/memory/*。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;
// Jakarta 校验注解：字符串非空
import jakarta.validation.constraints.NotBlank;
// Jakarta 校验注解：数值范围
import jakarta.validation.constraints.Max;
// Jakarta 校验注解：数值范围
import jakarta.validation.constraints.Min;

/**
 * 记忆域 DTO 集合。
 */
public final class MemoryDtos {

    /** 工具类禁止实例化。 */
    private MemoryDtos() {
    }

    /**
     * 本地检索 / 检索问答请求。
     *
     * @param workspaceId 工作区 id；null 表示当前 active 工作区
     * @param query       检索关键词或问题
     * @param topK        返回条数；null 表示取设置值
     */
    public record MemorySearchRequest(
            // 工作区 id
            @JsonProperty("workspace_id") String workspaceId,
            // 检索问题
            @NotBlank(message = "query 不能为空")
            String query,
            // 返回条数
            @JsonProperty("top_k")
            @Min(value = 1, message = "top_k 最小为 1")
            @Max(value = 50, message = "top_k 最大为 50")
            Integer topK
    ) {
    }

    /**
     * 手动新增记忆请求。
     *
     * <p><b>为什么 importance 是 Integer 而不是 int：</b>不传这个字段时 int 会被 Jackson 填成 0，
     * 0 又被 {@code @Min(1)} 判成越界，请求在进 controller 之前就 400 了，默认值根本没机会生效。
     * 用 Integer 时「没传」是 null（{@code @Min/@Max} 对 null 放行），
     * 「传了 0」仍然是 0 并照旧报 400（取舍见 docs/adr/0001）。</p>
     *
     * @param content     记忆正文（一句话）
     * @param category    分类：preference / decision / fact / todo
     * @param importance  重要度 1~5；null=没传，取默认 3
     * @param workspaceId 工作区 id；null 表示当前 active
     */
    public record MemoryCreateRequest(
            // 正文
            @NotBlank(message = "content 不能为空")
            String content,
            // 分类
            String category,
            // 重要度；null=没传（默认 3），显式越界仍报错
            @Min(value = 1, message = "importance 最小为 1")
            @Max(value = 5, message = "importance 最大为 5")
            Integer importance,
            // 工作区 id
            @JsonProperty("workspace_id") String workspaceId
    ) {
        /**
         * 补齐默认值。
         *
         * <p>判断条件是 {@code == null} 而不是 {@code <= 0}：显式传 0 已经被
         * {@code @Min(1)} 拦在入口（400），不能在这里再悄悄改成默认值。</p>
         *
         * @return category 默认 fact、importance 非 null 的新请求对象（默认 3）
         */
        public MemoryCreateRequest withDefaults() {
            String safeCategory = (category == null || category.isBlank()) ? "fact" : category;
            int safeImportance = importance == null ? 3 : importance;
            return new MemoryCreateRequest(content, safeCategory, safeImportance, workspaceId);
        }
    }

    /**
     * 手动触发记忆抽取请求。
     *
     * @param sessionId   要抽取的会话 id
     * @param workspaceId 工作区 id；null 表示当前 active
     */
    public record MemoryExtractRequest(
            // 会话 id
            @NotBlank(message = "session_id 不能为空")
            @JsonProperty("session_id") String sessionId,
            // 工作区 id
            @JsonProperty("workspace_id") String workspaceId
    ) {
    }

    /**
     * 维护动作（整理 / 重建向量）请求。
     *
     * @param workspaceId 工作区 id；null 表示当前 active
     * @param force       reindex 时是否强制重算全部向量
     */
    public record MemoryMaintenanceRequest(
            // 工作区 id
            @JsonProperty("workspace_id") String workspaceId,
            // 是否强制重算
            boolean force
    ) {
    }
}
