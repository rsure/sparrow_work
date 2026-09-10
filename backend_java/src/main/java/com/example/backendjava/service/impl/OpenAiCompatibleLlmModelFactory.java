// 模块说明：OpenAI 兼容协议的模型工厂。覆盖 OpenAI、DeepSeek 与用户自定义中转站。
package com.example.backendjava.service.impl;

// Spring 组件注解：把本工厂注册成 Bean，由路由器自动发现
import org.springframework.stereotype.Component;
// LangChain4j 同步聊天模型（OpenAI 实现）
import dev.langchain4j.model.openai.OpenAiChatModel;
// LangChain4j 流式聊天模型（OpenAI 实现）
import dev.langchain4j.model.openai.OpenAiStreamingChatModel;
// LangChain4j 同步模型接口：方法返回值类型
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口：方法返回值类型
import dev.langchain4j.model.chat.StreamingChatModel;
// 项目内业务异常：缺少 Key 或 baseUrl 时给出可读提示
import com.example.backendjava.common.ApiException;

// 模型工厂扩展点：按供应商装配 LangChain4j ChatModel
import com.example.backendjava.llm.LlmModelFactory;
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

/**
 * OpenAI 兼容协议模型工厂。
 *
 * <p>DeepSeek、OpenAI 官方、以及绝大多数国内中转站都提供 OpenAI 兼容接口，
 * 因此共用一套构建逻辑，只改 baseUrl / apiKey / modelName。</p>
 *
 * <p><b>baseUrl 约定：</b>这里传入的是“基础地址”，LangChain4j 会在后面拼接
 * {@code /chat/completions}。例如：</p>
 * <ul>
 *   <li>OpenAI：https://api.openai.com/v1</li>
 *   <li>DeepSeek：https://api.deepseek.com/v1</li>
 *   <li>自定义中转站：按其文档给到“/v1”这一级</li>
 * </ul>
 */
@Component
public class OpenAiCompatibleLlmModelFactory implements LlmModelFactory {

    /**
     * 支持的供应商：openai、deepseek，以及所有以 custom- 开头的自定义端点。
     *
     * @param providerId 供应商 id
     * @return 是否由本工厂处理
     */
    @Override
    public boolean supports(String providerId) {
        // 空值保护：配置缺失时不应该抛空指针，交给上层给出可读错误
        if (providerId == null) {
            return false;
        }
        // OpenAI 与 DeepSeek 使用同一套协议；自定义端点按约定也走 OpenAI 兼容
        return "openai".equals(providerId)
                || "deepseek".equals(providerId)
                || providerId.startsWith("custom-");
    }

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return OpenAiChatModel 实例
     * @throws ApiException apiKey 或 baseUrl 缺失时抛出
     */
    @Override
    public ChatModel createChatModel(LlmModelSpec spec) {
        // 复用统一的参数校验，避免同步/流式两条路径行为不一致
        validate(spec);

        // Builder 允许只设置需要的参数；temperature / maxTokens 为空时保持供应商默认值
        var builder = OpenAiChatModel.builder()
                .baseUrl(spec.baseUrl())
                .apiKey(spec.apiKey())
                .modelName(spec.model());

        // 只有显式配置了温度才覆盖默认值，null 表示“不干预”
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        // maxTokens=0 或 null 都表示使用供应商默认上限
        if (spec.maxTokens() != null && spec.maxTokens() > 0) {
            builder.maxTokens(spec.maxTokens());
        }
        return builder.build();
    }

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return OpenAiStreamingChatModel 实例
     * @throws ApiException apiKey 或 baseUrl 缺失时抛出
     */
    @Override
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        // 与同步模型相同的参数校验
        validate(spec);

        var builder = OpenAiStreamingChatModel.builder()
                .baseUrl(spec.baseUrl())
                .apiKey(spec.apiKey())
                .modelName(spec.model());

        // 流式模型同样只在显式配置时覆盖采样参数
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        if (spec.maxTokens() != null && spec.maxTokens() > 0) {
            builder.maxTokens(spec.maxTokens());
        }
        return builder.build();
    }

    /**
     * 校验构建模型必需的两项配置。
     *
     * @param spec 模型装配参数
     * @throws ApiException apiKey 或 baseUrl 为空时抛出 400
     */
    private void validate(LlmModelSpec spec) {
        // API Key 为空时直接给出“去设置页填写”的提示，避免底层 SDK 抛难懂的 401
        if (spec.apiKey() == null || spec.apiKey().isBlank()) {
            throw new ApiException(400, "缺少 API Key：请先在设置页填写对应供应商的密钥");
        }
        // baseUrl 为空时无法确定请求地址；不猜默认值，避免把密钥发到错误的域名
        if (spec.baseUrl() == null || spec.baseUrl().isBlank()) {
            throw new ApiException(400, "缺少接口地址 baseUrl：自定义端点必须填写");
        }
        // model 为空时请求一定会失败，提前拦截
        if (spec.model() == null || spec.model().isBlank()) {
            throw new ApiException(400, "缺少模型名 model");
        }
    }
}
