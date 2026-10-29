// 模块说明：Google Gemini 模型工厂。云端服务、必须带 API Key，使用 Gemini 原生 generateContent 协议。
package com.example.backendjava.llm;

// Spring 组件注解：把本工厂注册成 Bean，由路由器自动发现
import org.springframework.stereotype.Component;
// LangChain4j 同步聊天模型（Gemini 实现）
import dev.langchain4j.model.googleai.GoogleAiGeminiChatModel;
// LangChain4j 流式聊天模型（Gemini 实现）
import dev.langchain4j.model.googleai.GoogleAiGeminiStreamingChatModel;
// LangChain4j 同步模型接口：方法返回值类型
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口：方法返回值类型
import dev.langchain4j.model.chat.StreamingChatModel;
// 项目内业务异常：缺 Key、地址非法时给出可读提示
import com.example.backendjava.common.ApiException;
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

// 标准库：解析接口地址，判断用户填的是「只有域名」还是「带路径的中转地址」
import java.net.URI;

/**
 * Google Gemini 模型工厂。
 *
 * <p>注册表里的供应商 id 是 {@code google}（不是 {@code gemini}），
 * 与 Python 侧 {@code backend/app/llm/registry.py} 保持一致，因此 supports 判的是 google。</p>
 *
 * <p>Gemini 是云端服务，每次请求都必须带 API Key；参数映射上，
 * Gemini 把「单轮输出上限」叫作 {@code maxOutputTokens}（Anthropic 叫 maxTokens），
 * 所以这里调用的是 builder.maxOutputTokens(...)。</p>
 *
 * <p><b>baseUrl 约定：</b>注册表里的官方地址只有域名
 * （{@code https://generativelanguage.googleapis.com}），而 LangChain4j 会在 baseUrl
 * 后面拼 {@code /models/{model}:generateContent}。若不补版本前缀，请求会缺少
 * {@code /v1beta} 而返回 404。因此本工厂只在「地址没有路径」时补 {@code /v1beta}；
 * 用户显式填了路径（例如中转站）则原样尊重。</p>
 */
@Component
public class GeminiLlmModelFactory implements LlmModelFactory {

    /** Gemini 接口的版本前缀：补在「只有域名」的 baseUrl 后面，供 SDK 继续拼 /models/... */
    private static final String API_VERSION_PATH = "/v1beta";

    /**
     * 支持的供应商 id。
     *
     * @param providerId 供应商 id
     * @return 是否为 google
     */
    @Override
    public boolean supports(String providerId) {
        // 用常量.equals 而不是 providerId.equals，传入 null 时不会抛空指针
        return "google".equals(providerId);
    }

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return GoogleAiGeminiChatModel 实例
     * @throws ApiException apiKey / model 缺失，或 baseUrl 格式非法时抛出 400
     */
    @Override
    public ChatModel createChatModel(LlmModelSpec spec) {
        // 同步与流式共用同一套校验，避免两条路径行为不一致
        validate(spec);

        var builder = GoogleAiGeminiChatModel.builder()
                .apiKey(spec.apiKey())
                .modelName(spec.model());

        // 归一化后再交给 SDK；返回 null 表示「没配地址」，此时用 SDK 自带的官方地址
        String baseUrl = normalizeBaseUrl(spec.baseUrl());
        if (baseUrl != null) {
            builder.baseUrl(baseUrl);
        }
        // 只有显式配置了温度才覆盖默认值，null 表示「不干预」
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        // Gemini 用 maxOutputTokens 表示单轮输出上限；0 或 null 表示用模型默认值
        if (spec.maxTokens() != null && spec.maxTokens() > 0) {
            builder.maxOutputTokens(spec.maxTokens());
        }
        return builder.build();
    }

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return GoogleAiGeminiStreamingChatModel 实例
     * @throws ApiException apiKey / model 缺失，或 baseUrl 格式非法时抛出 400
     */
    @Override
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        // 与同步模型相同的参数校验
        validate(spec);

        var builder = GoogleAiGeminiStreamingChatModel.builder()
                .apiKey(spec.apiKey())
                .modelName(spec.model());

        // 流式模型同样需要补版本前缀，否则 SSE 请求也会 404
        String baseUrl = normalizeBaseUrl(spec.baseUrl());
        if (baseUrl != null) {
            builder.baseUrl(baseUrl);
        }
        // 流式模型同样只在显式配置时覆盖采样参数
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        // maxTokens=0 或 null 都表示使用模型默认输出上限
        if (spec.maxTokens() != null && spec.maxTokens() > 0) {
            builder.maxOutputTokens(spec.maxTokens());
        }
        return builder.build();
    }

    /**
     * 校验 Gemini 必需的配置项。
     *
     * <p>baseUrl 允许为空：空值时使用 LangChain4j 内置的 Gemini 官方地址，
     * 不需要每个调用方都重复填一遍。</p>
     *
     * @param spec 模型装配参数
     * @throws ApiException apiKey 或 model 为空时抛出 400
     */
    private void validate(LlmModelSpec spec) {
        // 云端模型没有 Key 一定失败，提前给出「去设置页填写」的提示，避免底层 SDK 抛难懂的 401
        if (spec.apiKey() == null || spec.apiKey().isBlank()) {
            throw new ApiException(400, "缺少 Google Gemini API Key：请先在设置页填写对应供应商的密钥");
        }
        // 模型名为空时请求一定会失败，提前拦截
        if (spec.model() == null || spec.model().isBlank()) {
            throw new ApiException(400, "缺少模型名 model");
        }
    }

    /**
     * 把配置的 baseUrl 归一化成 LangChain4j 需要的形式。
     *
     * <p>只处理「只有域名」的情况：补上 {@code /v1beta}。用户自己写了路径
     * （如 {@code https://proxy.example.com/gemini}）说明他清楚目标端点，
     * 不能再擅自追加，否则会把请求发到不存在的路径。</p>
     *
     * @param baseUrl 配置的接口地址；允许为空
     * @return 归一化后的地址；入参为空时返回 null，表示交给 SDK 用默认地址
     * @throws ApiException 地址不是合法的 http(s) URL 时抛出 400
     */
    private String normalizeBaseUrl(String baseUrl) {
        // 空地址不是错误：SDK 自带 https://generativelanguage.googleapis.com/v1beta 作为默认值
        if (baseUrl == null || baseUrl.isBlank()) {
            return null;
        }
        String trimmed = baseUrl.trim();

        URI uri;
        try {
            uri = URI.create(trimmed);
        } catch (IllegalArgumentException exception) {
            // 把底层解析异常转成 400，前端能直接展示「地址格式不对」
            throw new ApiException(400, "Gemini 接口地址 baseUrl 格式不正确：" + trimmed);
        }
        // 必须有协议和主机名，否则拼出来的 URL 无法请求
        if (uri.getScheme() == null || uri.getHost() == null) {
            throw new ApiException(400, "Gemini 接口地址 baseUrl 必须以 http:// 或 https:// 开头：" + trimmed);
        }

        String path = uri.getPath();
        // 只有域名（或域名 + 一个斜杠）时才补版本前缀
        if (path == null || path.isEmpty() || "/".equals(path)) {
            // 先去掉末尾斜杠，统一得到 https://generativelanguage.googleapis.com/v1beta
            String withoutTrailingSlash = trimmed.endsWith("/")
                    ? trimmed.substring(0, trimmed.length() - 1)
                    : trimmed;
            return withoutTrailingSlash + API_VERSION_PATH;
        }
        // 已经有路径：原样返回，尊重用户的代理/中转配置
        return trimmed;
    }
}
