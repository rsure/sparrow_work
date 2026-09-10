// 模块说明：模型能力的业务接口。Controller 与 Agent 层都通过它获取模型，不直接依赖具体供应商。
package com.example.backendjava.llm;

// LangChain4j 同步模型接口
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口
import dev.langchain4j.model.chat.StreamingChatModel;

// 标准库：List 用于供应商清单
import java.util.List;

// 模型接口的供应商/模型/探测 DTO 容器
import com.example.backendjava.dto.LlmDtos;
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;

/**
 * 模型服务接口。
 *
 * <p>实现类负责：读取供应商清单、按配置创建模型、做连通性测试。
 * 上层（ChatService / AgentRuntime）只依赖本接口，切换供应商时不需要改业务代码。</p>
 */
public interface LlmService {

    /**
     * 列出全部可用供应商与模型。
     *
     * @return 供应商清单
     */
    LlmDtos.ProvidersResult listProviders();

    /**
     * 测试某个供应商/模型配置是否可用。
     *
     * @param request 测试参数
     * @return 测试结果；网络错误、密钥错误都会转成结构化结果而不是抛异常
     */
    LlmDtos.ProbeResult probe(LlmDtos.ProbeRequest request);

    /**
     * 按参数创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return 同步模型
     */
    ChatModel createChatModel(LlmModelSpec spec);

    /**
     * 按参数创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return 流式模型
     */
    StreamingChatModel createStreamingModel(LlmModelSpec spec);
}
