// 模块说明：LangChain4j 的流式助手接口。AiServices 按这个接口在运行时生成实现，
// 本类只声明「一次流式对话长什么样」，不写具体调用模型的代码。
package com.example.backendjava.service;

// LangChain4j 流式令牌：注册 token / 完成 / 错误回调，调用 start() 后开始生成
import dev.langchain4j.service.TokenStream;

/**
 * 对话助手接口。
 *
 * <p>由 {@code AiServices.builder(ChatAssistant.class)} 生成代理实现：
 * 方法参数被当作本轮用户消息，系统提示词与工具由 builder 统一注入，
 * 工具循环也由框架完成。</p>
 */
public interface Assistant {

    /**
     * 发起一次流式对话。
     *
     * @param userMessage 用户本轮输入
     * @return 令牌流；注册回调并调用 {@code start()} 后开始生成
     */
    TokenStream chat(String userMessage);
}
