// 模块说明：模型供应商相关的请求/响应 DTO。字段名与 Python 侧 /api/llm/* 接口保持一致。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;

// 标准库：List 用于返回模型清单
import java.util.List;

/**
 * LLM 接口的 DTO 集合。
 *
 * <p>使用嵌套 record 而不是为每个类单独建文件：这些类型只服务于 /api/llm/*，
 * 放在一起更容易对照接口契约；每个 record 的组件都有 Javadoc 说明。</p>
 */
public final class LlmDtos {

    /** 工具类禁止实例化。 */
    private LlmDtos() {
    }

    /**
     * 单个模型的静态描述。
     *
     * @param model          调用 API 时使用的模型名，如 deepseek-flash
     * @param label          展示名，如 "DeepSeek V4.1 Flash"
     * @param contextWindow  上下文窗口上限（单位：token）
     * @param supportsTools  是否支持工具调用（function calling）
     * @param supportsVision 是否支持图片输入
     * @param priceIn        每百万输入 token 的价格（单位：元，仅用于估算）
     * @param priceOut       每百万输出 token 的价格（单位：元，仅用于估算）
     */
    public record ModelInfo(
            // API 模型名：真正发给供应商的 model 字段
            String model,
            // 展示名：设置页下拉框显示
            String label,
            // 上下文窗口：决定何时压缩对话
            @JsonProperty("context_window") int contextWindow,
            // 是否支持工具调用：为 false 的模型不应出现在 Agent 候选里
            @JsonProperty("supports_tools") boolean supportsTools,
            // 是否支持图片输入：首版只展示，不启用多模态
            @JsonProperty("supports_vision") boolean supportsVision,
            // 输入单价：元 / 百万 token
            @JsonProperty("price_in") double priceIn,
            // 输出单价：元 / 百万 token
            @JsonProperty("price_out") double priceOut
    ) {
    }

    /**
     * 一家模型供应商的描述。
     *
     * @param id          供应商 id，如 deepseek / openai / custom-myapi
     * @param label       展示名
     * @param baseUrl     默认接口地址；空串表示由模型工厂决定
     * @param secretKey   密钥在密钥库里的名字；不需要密钥时为空串
     * @param requiresKey 是否需要 API Key；Ollama 本地模型为 false
     * @param isCustom    是否为用户自定义的 OpenAI 兼容端点
     * @param models      该供应商下可选的模型清单
     */
    public record ProviderInfo(
            // 供应商唯一 id
            String id,
            // 展示名
            String label,
            // 默认接口地址
            @JsonProperty("base_url") String baseUrl,
            // 密钥名（不带 secrets. 前缀）
            @JsonProperty("secret_key") String secretKey,
            // 是否需要密钥
            @JsonProperty("requires_key") boolean requiresKey,
            // 是否自定义端点
            @JsonProperty("is_custom") boolean isCustom,
            // 模型清单
            List<ModelInfo> models
    ) {
    }

    public record ProvidersResult(
            List<ProviderInfo> providers
    ){

    }
    /**
     * 模型连通性测试请求。
     *
     * @param providerId 供应商 id
     * @param model      模型名；为空时取该供应商的第一个模型
     * @param baseUrl    接口地址；为空时用供应商默认地址
     * @param apiKey     API Key；为空时由后续的密钥服务补齐（当前脚手架暂未实现）
     */
    public record ProbeRequest(
            // 供应商 id，如 deepseek
            @JsonProperty("provider_id") String providerId,
            // 模型名；可空
            String model,
            // 接口地址；可空
            @JsonProperty("base_url") String baseUrl,
            // API Key；仅用于本地测试，正式实现应从密钥库读取
            @JsonProperty("api_key") String apiKey
    ) {
    }

    /**
     * 模型连通性测试结果。
     *
     * @param ok        是否成功
     * @param latencyMs 请求耗时（毫秒）
     * @param error     失败原因；成功时为 null
     * @param errorKind 失败分类：secret / model / network / unknown；成功时为 null
     */
    public record ProbeResult(
            // 是否成功
            boolean ok,
            // 耗时毫秒
            @JsonProperty("latency_ms") long latencyMs,
            // 失败原因
            String error,
            // 失败分类
            @JsonProperty("error_kind") String errorKind
    ) {
    }
}
