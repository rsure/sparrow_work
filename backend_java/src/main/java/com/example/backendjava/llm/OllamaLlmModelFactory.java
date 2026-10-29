// 模块说明：Ollama 模型工厂。本地部署、不需要 API Key，是三个待补工厂里最容易验证的一个。
package com.example.backendjava.llm;

// Spring 组件注解：把本工厂注册成 Bean，由路由器自动发现
import org.springframework.stereotype.Component;
// LangChain4j 同步聊天模型（Ollama 实现）
import dev.langchain4j.model.ollama.OllamaChatModel;
// LangChain4j 流式聊天模型（Ollama 实现）
import dev.langchain4j.model.ollama.OllamaStreamingChatModel;
// LangChain4j 同步模型接口：方法返回值类型
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口：方法返回值类型
import dev.langchain4j.model.chat.StreamingChatModel;
// 项目内业务异常：缺 baseUrl 时给可读提示
import com.example.backendjava.common.ApiException;

// 模型工厂扩展点：按供应商装配 LangChain4j ChatModel
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

/**
 * Ollama 模型工厂。
 *
 * <p>Ollama 本地起服务后提供 OpenAI 兼容接口，LangChain4j 有专门实现；
 * 不需要密钥，所以不校验 apiKey，只校验 baseUrl 与 modelName。</p>
 */
@Component
public class OllamaLlmModelFactory implements LlmModelFactory {

    /**
     * 支持的供应商 id。
     *
     * @param providerId 供应商 id
     * @return 是否为 ollama
     */
    @Override
    public boolean supports(String providerId) {
        return "ollama".equals(providerId);
    }

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return OllamaChatModel 实例
     * @throws ApiException baseUrl 或 model 缺失时抛出
     */
    @Override
    public ChatModel createChatModel(LlmModelSpec spec) {
        validate(spec);
        var builder = OllamaChatModel.builder()
                .baseUrl(spec.baseUrl())
                .modelName(spec.model());
        // 只有显式配置了温度才覆盖默认值
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        return builder.build();
    }

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return OllamaStreamingChatModel 实例
     * @throws ApiException baseUrl 或 model 缺失时抛出
     */
    @Override
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        validate(spec);
        var builder = OllamaStreamingChatModel.builder()
                .baseUrl(spec.baseUrl())
                .modelName(spec.model());
        if (spec.temperature() != null) {
            builder.temperature(spec.temperature());
        }
        return builder.build();
    }

    /**
     * 校验构建模型必需的配置。
     *
     * @param spec 模型装配参数
     * @throws ApiException baseUrl 或 model 为空时抛出 400
     */
    private void validate(LlmModelSpec spec) {
        if (spec.baseUrl() == null || spec.baseUrl().isBlank()) {
            throw new ApiException(400, "缺少 Ollama 接口地址 baseUrl");
        }
        if (spec.model() == null || spec.model().isBlank()) {
            throw new ApiException(400, "缺少模型名 model");
        }
    }
}