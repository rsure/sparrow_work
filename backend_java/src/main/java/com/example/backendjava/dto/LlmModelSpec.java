// 模块说明：创建模型实例所需的参数集合。把“配置”与“构建”分开，便于运行时切换供应商。
package com.example.backendjava.dto;

/**
 * 模型装配参数。
 *
 * @param providerId  供应商 id，如 deepseek / openai / custom-myapi
 * @param model       API 模型名，如 deepseek-flash
 * @param apiKey      API Key；Ollama 等本地模型可以为空
 * @param baseUrl     接口地址；为空时由具体工厂决定默认值
 * @param temperature 采样温度；null 表示用模型默认值
 * @param maxTokens   单轮输出上限；null 或 0 表示不传该参数
 */
public record LlmModelSpec(
        // 供应商 id：工厂路由据此选择具体实现
        String providerId,
        // API 模型名
        String model,
        // API Key：仅存在于内存中，不写日志
        String apiKey,
        // 接口地址：自定义中转站必须提供
        String baseUrl,
        // 采样温度
        Double temperature,
        // 单轮输出 token 上限
        Integer maxTokens
) {
}
