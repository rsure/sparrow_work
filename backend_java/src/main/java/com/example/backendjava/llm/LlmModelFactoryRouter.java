// 模块说明：模型工厂路由。按供应商 id 选择具体工厂，业务层不感知实现类。
package com.example.backendjava.llm;

// Spring 组件注解：把路由器注册成 Bean
import org.springframework.stereotype.Component;
// LangChain4j 同步模型接口
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口
import dev.langchain4j.model.chat.StreamingChatModel;
// 项目内业务异常：没有工厂支持该供应商时抛 501
import com.example.backendjava.common.ApiException;
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

// 标准库：List 保存容器里所有工厂实现
import java.util.List;

/**
 * 模型工厂路由器。
 *
 * <p>Spring 会把所有实现 {@link LlmModelFactory} 的 Bean 注入到构造函数里。
 * 新增 Anthropic / Gemini / Ollama 工厂时，只需加一个 @Component，无需修改本类。</p>
 */
@Component
public class LlmModelFactoryRouter {

    /** 容器里全部模型工厂；顺序不影响结果，因为每个供应商只应由一个工厂支持。 */
    private final List<LlmModelFactory> factories;

    /**
     * 构造器注入所有模型工厂。
     *
     * @param factories Spring 收集到的工厂实现列表
     */
    public LlmModelFactoryRouter(List<LlmModelFactory> factories) {
        this.factories = factories;
    }

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return 同步模型实例
     * @throws ApiException 没有工厂支持该供应商时抛出 501
     */
    public ChatModel createChatModel(LlmModelSpec spec) {
        return findFactory(spec.providerId()).createChatModel(spec);
    }

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return 流式模型实例
     * @throws ApiException 没有工厂支持该供应商时抛出 501
     */
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        return findFactory(spec.providerId()).createStreamingModel(spec);
    }

    /**
     * 找到支持指定供应商的工厂。
     *
     * @param providerId 供应商 id
     * @return 匹配的工厂
     * @throws ApiException 找不到时抛出，提示学习者补一个工厂实现
     */
    private LlmModelFactory findFactory(String providerId) {
        return factories.stream()
                .filter(factory -> factory.supports(providerId))
                .findFirst()
                .orElseThrow(() -> new ApiException(
                        501,
                        "供应商 " + providerId + " 的模型工厂尚未实现："
                                + "请实现 LlmModelFactory 并注册为 Spring Bean"
                ));
    }
}
