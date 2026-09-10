// 模块说明：内置模型供应商与模型清单。对应 Python 侧 app/llm/registry.py。
package com.example.backendjava.llm;

// Spring 组件注解：把注册表注册成 Bean，供 LlmService 注入
import org.springframework.stereotype.Component;
// 项目内业务异常：未知供应商/模型时抛 404
import com.example.backendjava.common.ApiException;
// 模型接口的供应商/模型/探测 DTO 容器
import com.example.backendjava.dto.LlmDtos;

// 标准库：List / Map 用于组织不可变清单
import java.util.List;
// 标准库：Optional 用于表达“可能找不到”
import java.util.Optional;

/**
 * 模型注册表。
 *
 * <p>把“有哪些供应商、各自有哪些模型”当成数据声明，而不是散落在业务代码里。
 * 用户以后要新增模型，只需要改本文件或从设置库读取自定义清单。</p>
 *
 * <p>当前只内置 5 家供应商；自定义 OpenAI 兼容端点的读取逻辑留作 TODO，
 * 对应 Python 侧的 llm.custom_providers / llm.custom_models 两个设置项。</p>
 */
@Component
public class LlmProviderRegistry {

    /** 内置供应商清单；List.of 生成的列表不可变，避免运行期被误改。 */
    private static final List<LlmDtos.ProviderInfo> BUILTIN_PROVIDERS = List.of(
            // DeepSeek：OpenAI 兼容协议；baseUrl 用 /v1 后缀，LangChain4j 会再拼 /chat/completions
            new LlmDtos.ProviderInfo(
                    "deepseek",
                    "DeepSeek",
                    "https://api.deepseek.com/v1",
                    "deepseek.api_key",
                    true,
                    false,
                    List.of(
                            new LlmDtos.ModelInfo("deepseek-flash", "DeepSeek V4.1 Flash", 1_000_000, true, true, 2.0, 8.0),
                            new LlmDtos.ModelInfo("deepseek-v4-pro", "DeepSeek V4 Pro", 1_000_000, true, false, 9.0, 27.0)
                    )
            ),
            // OpenAI：官方地址；自定义中转站也可以复用这个供应商，只要改 baseUrl
            new LlmDtos.ProviderInfo(
                    "openai",
                    "OpenAI",
                    "https://api.openai.com/v1",
                    "openai.api_key",
                    true,
                    false,
                    List.of(
                            new LlmDtos.ModelInfo("gpt-4o", "GPT-4o", 128_000, true, true, 18.0, 72.0),
                            new LlmDtos.ModelInfo("gpt-4o-mini", "GPT-4o mini", 128_000, true, true, 1.1, 4.3)
                    )
            ),
            // Anthropic Claude：模型工厂待实现；这里先把清单与计费信息声明好
            new LlmDtos.ProviderInfo(
                    "anthropic",
                    "Anthropic",
                    "https://api.anthropic.com",
                    "anthropic.api_key",
                    true,
                    false,
                    List.of(
                            new LlmDtos.ModelInfo("claude-sonnet-4-20250514", "Claude Sonnet 4", 200_000, true, true, 22.0, 110.0),
                            new LlmDtos.ModelInfo("claude-3-5-haiku-20241022", "Claude Haiku 3.5", 200_000, true, false, 6.0, 30.0)
                    )
            ),
            // Google Gemini：模型工厂待实现
            new LlmDtos.ProviderInfo(
                    "google",
                    "Google Gemini",
                    "https://generativelanguage.googleapis.com",
                    "google.api_key",
                    true,
                    false,
                    List.of(
                            new LlmDtos.ModelInfo("gemini-2.0-flash", "Gemini 2.0 Flash", 1_000_000, true, true, 5.0, 15.0)
                    )
            ),
            // Ollama：本地模型，不需要密钥；baseUrl 指向本机服务
            new LlmDtos.ProviderInfo(
                    "ollama",
                    "Ollama（本地）",
                    "http://127.0.0.1:11434",
                    "",
                    false,
                    false,
                    List.of(
                            new LlmDtos.ModelInfo("qwen2.5:7b", "Qwen2.5 7B", 32_768, true, false, 0.0, 0.0),
                            new LlmDtos.ModelInfo("llama3.1:8b", "Llama 3.1 8B", 131_072, true, false, 0.0, 0.0)
                    )
            )
    );

    /**
     * 列出全部可用供应商。
     *
     * <p>TODO：后续把设置库里的自定义供应商追加到这里，并给 id 加 "custom-" 前缀。</p>
     *
     * @return 内置供应商清单（不可变）
     */
    public List<LlmDtos.ProviderInfo> listProviders() {
        return BUILTIN_PROVIDERS;
    }

    /**
     * 按 id 查找供应商。
     *
     * @param providerId 供应商 id
     * @return 找到时返回 ProviderInfo；找不到时返回 Optional.empty()
     */
    public Optional<LlmDtos.ProviderInfo> findProvider(String providerId) {
        return BUILTIN_PROVIDERS.stream()
                .filter(provider -> provider.id().equals(providerId))
                .findFirst();
    }

    /**
     * 解析出实际要使用的模型描述。
     *
     * @param providerId 供应商 id
     * @param modelName  模型名；为空时取该供应商的第一个模型
     * @return 模型描述
     * @throws ApiException 供应商不存在（404）或模型不存在（404）
     */
    public LlmDtos.ModelInfo resolveModel(String providerId, String modelName) {
        // 先校验供应商，避免模型名恰好同名时误命中别的供应商
        LlmDtos.ProviderInfo provider = findProvider(providerId)
                .orElseThrow(() -> new ApiException(404, "未知的模型供应商：" + providerId));

        // 未指定模型名：取清单第一个作为默认模型
        if (modelName == null || modelName.isBlank()) {
            if (provider.models().isEmpty()) {
                throw new ApiException(404, "供应商 " + providerId + " 还没有配置任何模型");
            }
            return provider.models().get(0);
        }

        // 指定了模型名：必须精确匹配，不能静默换成别的模型
        return provider.models().stream()
                .filter(model -> model.model().equals(modelName))
                .findFirst()
                .orElseThrow(() -> new ApiException(
                        404,
                        "供应商 " + providerId + " 下没有模型 " + modelName
                ));
    }
}
