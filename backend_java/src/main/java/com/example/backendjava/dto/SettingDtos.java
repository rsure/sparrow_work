// 模块说明：设置体系的请求/响应 DTO，对应 Python 侧 /api/settings/*。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;
// Jakarta 校验注解：字符串非空
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.Setter;

// 标准库：List 用于工作区根目录、设置项清单、导入结果
import java.util.List;
// 标准库：Map 用于任意 JSON 设置值
import java.util.Map;

/**
 * 设置域 DTO 集合。
 */
public final class SettingDtos {

    /** 工具类禁止实例化。 */
    private SettingDtos() {
    }

    // ======================================================================= //
    // 1. 工作区
    // ======================================================================= //

    /**
     * 覆盖式保存工作区根目录的请求体。
     *
     * @param paths 根目录绝对路径列表；空数组表示清除限制
     */
    public record WorkspacePathsRequest(
            // 根目录列表
            List<String> paths
    ) {
    }

    /**
     * 新建工作区的请求体。
     *
     * @param name  工作区名称；不能为空
     * @param roots 根目录列表；允许为空
     */
    public record WorkspaceCreateRequest(
            // 名称
            @NotBlank(message = "name 不能为空")
            String name,
            // 根目录列表
            List<String> roots
    ) {
    }

    /**
     * 更新工作区的请求体。
     *
     * @param name  新名称；null 表示不改
     * @param roots 新根目录列表；null 表示不改，空数组表示清空
     */
    public record WorkspaceUpdateRequest(
            // 新名称
            String name,
            // 新根目录列表
            List<String> roots
    ) {
    }

    /**
     * 切换当前工作区的请求体。
     *
     * <p>同时接受 id 与 workspace_id 两个字段名，兼容旧前端；两个都传时以 id 为准。</p>
     *
     * @param id          目标工作区 id（推荐字段）
     * @param workspaceId 兼容字段名
     */
    public record WorkspaceActiveRequest(
            // 推荐字段
            String id,
            // 兼容字段
            @JsonProperty("workspace_id") String workspaceId
    ) {
        /**
         * 解析出实际生效的工作区 id。
         *
         * @return id 优先；id 为空时退回 workspace_id；都为空时返回空串
         */
        public String resolveId() {
            if (id != null && !id.isBlank()) {
                return id;
            }
            return workspaceId == null ? "" : workspaceId;
        }
    }

    /**
     * 一个工作区 profile。
     *
     * @param id     工作区唯一 id
     * @param name   展示名
     * @param roots  根目录绝对路径列表
     * @param active 是否为当前生效工作区（冗余标记）
     */
    public record WorkspaceProfile(
            // 工作区 id
            String id,
            // 展示名
            String name,
            // 根目录列表
            List<String> roots,
            // 是否当前生效
            boolean active
    ) {
    }

    /**
     * 工作区列表响应体。
     *
     * @param workspaces 全部工作区
     * @param activeId   当前生效工作区 id；没有工作区时为空串
     */

    public record WorkspacesView(
            // 工作区列表
            List<WorkspaceProfile> workspaces,
            // 当前生效 id
            @JsonProperty("active_id") String activeId
    ) {
    }

    /**
     * 删除工作区的响应体。
     *
     * @param deleted 是否确实删除了一个已存在的工作区
     */
    public record WorkspaceDeletedResult(
            // 是否删除
            boolean deleted
    ) {
    }

    /**
     * 切换工作区的响应体。
     *
     * @param activeId 切换后的当前工作区 id
     */
    public record ActiveSwitchResult(
            // 当前工作区 id
            @JsonProperty("active_id") String activeId
    ) {
    }

    // ======================================================================= //
    // 2. 普通设置
    // ======================================================================= //

    /**
     * 批量保存普通设置的请求体。
     *
     * @param values 要保存的键值对；只包含要改的键
     */
    public record SettingsBatchRequest(
            // 设置键值对
            Map<String, Object> values
    ) {
    }

    /**
     * 全量设置值的响应体。
     *
     * @param values 键到当前值的映射；不含 secrets.* 键
     */
    public record SettingsView(
            // 设置键值对
            Map<String, Object> values
    ) {
    }

    /**
     * 单个设置项的 schema 描述。
     *
     * @param key          设置键，形如 llm.model
     * @param label        中文展示名
     * @param type         值类型：bool / int / float / string / json / select
     * @param defaultValue 默认值
     * @param min          数值下界；不限时为 null
     * @param max          数值上界；不限时为 null
     * @param options      select 候选值；其它类型为 null
     * @param optionLabels select 候选值的中文标签
     * @param category     设置页分组
     * @param since        首次引入的里程碑
     * @param description  面向用户的说明
     * @param secret       是否为密钥项；当前恒为 false
     */
    public record SettingMeta(
            // 设置键
            String key,
            // 展示名
            String label,
            // 值类型
            String type,
            // 默认值
            @JsonProperty("default") Object defaultValue,
            // 下界
            Double min,
            // 上界
            Double max,
            // 候选值
            List<String> options,
            // 候选值标签
            @JsonProperty("option_labels") List<String> optionLabels,
            // 分组
            String category,
            // 里程碑
            String since,
            // 说明
            String description,
            // 是否密钥项
            boolean secret
    ) {
    }

    /**
     * 保存密钥的请求体。
     *
     * @param value 密钥明文；保存后不再原样返回
     */
    public record SecretPutRequest(
            // 密钥明文
            @NotBlank(message = "value 不能为空")
            String value
    ) {
    }

    /**
     * 密钥状态。
     *
     * @param set    是否已设置
     * @param masked 脱敏后的展示值；未设置时为 null
     */
    public record SecretStatus(
            // 是否已设置
            boolean set,
            // 脱敏值
            String masked
    ) {
    }

    /**
     * 删除密钥的响应体。
     *
     * <p>与 Python 侧 {@code {"deleted": bool}} 一致：删除一个本来就不存在的密钥不算错误，
     * 但要如实告诉调用方「这一下到底有没有删掉东西」。</p>
     *
     * @param deleted 是否确实删掉了一个已存在的密钥
     */
    public record SecretDeletedResult(
            // 是否删除
            boolean deleted
    ) {
    }

    // ======================================================================= //
    // 3. 导入 / 导出
    // ======================================================================= //

    /**
     * 导出文件里的密钥状态。
     *
     * @param key 密钥名（不带 secrets. 前缀）
     * @param set 是否已设置
     */
    public record SecretPoint(
            // 密钥名
            String key,
            // 是否已设置
            boolean set
    ) {
    }

    /**
     * 脱敏配置导出结果。
     *
     * @param format       导出格式标识
     * @param exportedAt   导出时间（ISO-8601）
     * @param appVersion   导出时的应用版本
     * @param values       设置键值对（已脱敏）
     * @param redactedKeys 被脱敏的键名
     * @param secrets      密钥设置状态清单
     */
    public record SettingsExport(
            // 格式标识
            String format,
            // 导出时间
            @JsonProperty("exported_at") String exportedAt,
            // 应用版本
            @JsonProperty("app_version") String appVersion,
            // 设置值
            Map<String, Object> values,
            // 被脱敏的键
            @JsonProperty("redacted_keys") List<String> redactedKeys,
            // 密钥状态
            List<SecretPoint> secrets
    ) {
    }

    /**
     * 导入配置的请求体。
     *
     * @param format       格式标识；可选
     * @param values       要导入的键值对
     * @param redactedKeys 导出时被脱敏的键；导入时跳过
     */
    public record SettingsImportRequest(
            // 格式标识
            String format,
            // 设置值
            Map<String, Object> values,
            // 被脱敏的键
            @JsonProperty("redacted_keys") List<String> redactedKeys
    ) {
    }

    /**
     * 导入时被跳过的一个键。
     *
     * @param key    设置键
     * @param reason 跳过原因（中文）
     */
    public record ImportSkipped(
            // 设置键
            String key,
            // 原因
            String reason
    ) {
    }

    /**
     * 导入结果。
     *
     * @param applied 真正写入的键
     * @param skipped 被跳过的键及原因
     * @param values  导入后全部非密钥设置值
     */
    public record SettingsImportResult(
            // 已写入的键
            List<String> applied,
            // 跳过的键
            List<ImportSkipped> skipped,
            // 导入后的设置值
            Map<String, Object> values
    ) {
    }
}
