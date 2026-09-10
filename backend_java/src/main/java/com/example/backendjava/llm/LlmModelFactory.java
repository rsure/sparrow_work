// 模块说明：模型工厂扩展点。每个供应商（OpenAI 兼容、Anthropic、Gemini、Ollama）实现一份。
package com.example.backendjava.llm;

// LangChain4j 同步聊天模型接口：一次性返回完整回答
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式聊天模型接口：按 token 回调，用于 SSE
import dev.langchain4j.model.chat.StreamingChatModel;

// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

/**
 * 模型工厂接口。
 *
 * <p>新增供应商时实现本接口并注册为 Spring Bean，然后在
 * {@link LlmModelFactoryRouter} 中即可自动被选中；不要在业务代码里直接 new 具体模型类。</p>
 */
public interface LlmModelFactory {

    /**
     * 判断本工厂是否支持某个供应商 id。
     *
     * @param providerId 供应商 id，如 openai / deepseek / custom-myapi
     * @return true 表示可以处理该供应商
     */
    boolean supports(String providerId);

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return 可直接调用 chat(...) 的模型实例
     */
    ChatModel createChatModel(LlmModelSpec spec);

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return 可注册 StreamingChatResponseHandler 的模型实例
     */
    StreamingChatModel createStreamingModel(LlmModelSpec spec);
}
