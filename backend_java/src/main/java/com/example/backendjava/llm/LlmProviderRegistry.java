// 模块说明：模型供应商与模型清单。内置 5 家 + 设置库里用户自定义的 OpenAI 兼容端点。
// 对应 Python 侧 app/llm/registry.py。
package com.example.backendjava.llm;

// Spring 组件注解：把注册表注册成 Bean，供 LlmService / ChatService 注入
import org.springframework.stereotype.Component;
// 项目内业务异常：未知供应商/模型时抛 404
import com.example.backendjava.common.ApiException;
// 模型接口的供应商/模型 DTO 容器
import com.example.backendjava.dto.LlmDtos;
// 设置注册表：读取 llm.custom_providers / llm.custom_models 两个 JSON 设置项
import com.example.backendjava.settings.SettingsRegistry;

// 标准库：ArrayList 构造合并后的可变清单
import java.util.ArrayList;
// 标准库：LinkedHashMap 去重并保留用户填写顺序
import java.util.LinkedHashMap;
// 标准库：List 组织供应商与模型清单
import java.util.List;
// 标准库：Map 承载设置项里的一条 JSON 对象
import java.util.Map;
// 标准库：Optional 表达「可能找不到」
import java.util.Optional;

/**
 * 模型注册表。
 *
 * <p>把「有哪些供应商、各自有哪些模型」当成数据声明，而不是散落在业务代码里：</p>
 * <ul>
 *   <li><b>内置清单</b>：本文件的 {@link #BUILTIN_PROVIDERS}，随代码一起发布；</li>
 *   <li><b>自定义端点</b>：设置项 {@code llm.custom_providers}，id 统一加 {@code custom-} 前缀，
 *       与 {@link OpenAiCompatibleLlmModelFactory#supports(String)} 的约定对齐；</li>
 *   <li><b>补充模型</b>：设置项 {@code llm.custom_models}，可以给内置供应商补新模型，
 *       也可以给自定义端点声明模型；同名模型以用户填的为准。</li>
 * </ul>
 *
 * <p><b>为什么每次都重新读设置：</b>设置页保存后要立刻生效，不能要求重启后端；
 * 这两个 JSON 项通常只有几条到几十条，解析成本可以忽略。</p>
 */
@Component
public class LlmProviderRegistry {

    /** 自定义供应商 id 的统一前缀：模型工厂靠它识别「走 OpenAI 兼容协议」。 */
    public static final String CUSTOM_PREFIX = "custom-";

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
            // Anthropic Claude：走 llm/AnthropicLlmModelFactory
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
            // Google Gemini：走 llm/GeminiLlmModelFactory
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

    /** 设置注册表：自定义供应商与补充模型的唯一来源。 */
    private final SettingsRegistry settingsRegistry;

    /**
     * 构造器注入。
     *
     * @param settingsRegistry 设置注册表
     */
    public LlmProviderRegistry(SettingsRegistry settingsRegistry) {
        this.settingsRegistry = settingsRegistry;
    }

    /**
     * 列出全部可用供应商（内置 + 自定义）。
     *
     * @return 合并后的供应商清单（不可变）
     */
    public List<LlmDtos.ProviderInfo> listProviders() {
        return mergedProviders();
    }

    /**
     * 按 id 查找供应商。
     *
     * @param providerId 供应商 id；自定义端点形如 custom-myapi
     * @return 找到时返回 ProviderInfo；找不到时返回 Optional.empty()
     */
    public Optional<LlmDtos.ProviderInfo> findProvider(String providerId) {
        if (providerId == null) {
            return Optional.empty();
        }
        return mergedProviders().stream()
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

    // ------------------------------------------------------------------ //
    // 合并清单
    // ------------------------------------------------------------------ //

    /**
     * 合并「内置供应商 + 设置里的自定义端点」，并把自定义模型并进各自的 models。
     *
     * @return 合并后的供应商清单
     */
    private List<LlmDtos.ProviderInfo> mergedProviders() {
        List<CustomModel> customModels = readCustomModels();
        List<LlmDtos.ProviderInfo> merged = new ArrayList<>(BUILTIN_PROVIDERS.size() + 4);

        // 1) 内置供应商：把 llm.custom_models 里归属它的模型并进去
        for (LlmDtos.ProviderInfo builtin : BUILTIN_PROVIDERS) {
            merged.add(mergeModels(builtin, customModels));
        }

        // 2) 自定义端点：id 统一加 custom- 前缀
        for (Map<String, Object> item : settingItems("llm.custom_providers")) {
            String rawId = stringOf(item, "id");
            // 没有 id 就无法被 llm.provider 选中，直接忽略这一项
            if (rawId.isBlank()) {
                continue;
            }
            String id = CUSTOM_PREFIX + rawId;
            // 重复 id 只保留第一条：后一条覆盖前一条会让用户以为「改了没生效」
            boolean duplicated = merged.stream().anyMatch(provider -> provider.id().equals(id));
            if (duplicated) {
                continue;
            }
            String baseUrl = stringOf(item, "base_url");
            // 没有地址就无法发请求；忽略这一项，而不是留一个注定失败的供应商
            if (baseUrl.isBlank()) {
                continue;
            }
            String label = stringOf(item, "label");
            if (label.isBlank()) {
                label = rawId;
            }
            List<LlmDtos.ModelInfo> models = new ArrayList<>();
            for (CustomModel model : customModels) {
                if (model.providerId().equals(id)) {
                    models.add(model.info());
                }
            }
            // 密钥名约定为 custom-xxx.api_key，与前端 ModelSection.vue 一致
            merged.add(new LlmDtos.ProviderInfo(
                    id, label, baseUrl, id + ".api_key", true, true, List.copyOf(models)));
        }
        return List.copyOf(merged);
    }

    /**
     * 把一个内置供应商与它的补充模型合并。
     *
     * @param builtin      内置供应商
     * @param customModels 设置里声明的全部自定义模型
     * @return 合并后的供应商；没有补充模型时原样返回
     */
    private LlmDtos.ProviderInfo mergeModels(LlmDtos.ProviderInfo builtin, List<CustomModel> customModels) {
        List<LlmDtos.ModelInfo> extra = new ArrayList<>();
        for (CustomModel model : customModels) {
            if (model.providerId().equals(builtin.id())) {
                extra.add(model.info());
            }
        }
        // 没有补充模型：直接返回原对象，避免无意义地重建
        if (extra.isEmpty()) {
            return builtin;
        }
        Map<String, LlmDtos.ModelInfo> byName = new LinkedHashMap<>();
        for (LlmDtos.ModelInfo info : builtin.models()) {
            byName.put(info.model(), info);
        }
        // 同名模型以用户填的为准：context_window / 单价应该听用户的
        for (LlmDtos.ModelInfo info : extra) {
            byName.put(info.model(), info);
        }
        return new LlmDtos.ProviderInfo(
                builtin.id(), builtin.label(), builtin.baseUrl(), builtin.secretKey(),
                builtin.requiresKey(), builtin.isCustom(), List.copyOf(byName.values()));
    }

    /**
     * 读取设置项 llm.custom_models，转成「供应商 id + 模型描述」的列表。
     *
     * @return 自定义模型列表；设置读失败或格式不对时返回空列表
     */
    private List<CustomModel> readCustomModels() {
        List<CustomModel> result = new ArrayList<>();
        for (Map<String, Object> item : settingItems("llm.custom_models")) {
            String provider = stringOf(item, "provider");
            String model = stringOf(item, "model");
            // context_window 必填：没有它就不知道该在什么时候压缩上下文，宁可忽略这一项
            int contextWindow = intOf(item, "context_window", 0);
            if (provider.isBlank() || model.isBlank() || contextWindow <= 0) {
                continue;
            }
            String label = stringOf(item, "label");
            if (label.isBlank()) {
                label = model;
            }
            result.add(new CustomModel(
                    normalizeProviderId(provider),
                    new LlmDtos.ModelInfo(
                            model,
                            label,
                            contextWindow,
                            boolOf(item, "supports_tools", true),
                            boolOf(item, "supports_vision", false),
                            doubleOf(item, "price_in", 0.0),
                            doubleOf(item, "price_out", 0.0))));
        }
        return result;
    }

    /**
     * 归一化 custom_models 里写的 provider 字段。
     *
     * <p>用户可能写内置 id（deepseek），也可能写自定义端点的裸 id（myapi）；
     * 这里统一成「内置保持原名、其余补 custom- 前缀」，避免同一家供应商出现两个 id。</p>
     *
     * @param raw 用户填的 provider
     * @return 归一化后的供应商 id
     */
    private static String normalizeProviderId(String raw) {
        if (raw.startsWith(CUSTOM_PREFIX)) {
            return raw;
        }
        boolean builtin = BUILTIN_PROVIDERS.stream().anyMatch(provider -> provider.id().equals(raw));
        return builtin ? raw : CUSTOM_PREFIX + raw;
    }

    /**
     * 读取一个 JSON 数组型设置项，并统一成 {@code List<Map<String, Object>>}。
     *
     * @param key 设置键，如 llm.custom_providers
     * @return 数组里的对象项；不是数组或读失败时返回空列表
     */
    private List<Map<String, Object>> settingItems(String key) {
        Object value;
        try {
            value = settingsRegistry.getSetting(key);
        } catch (RuntimeException e) {
            // 读设置失败按「没有自定义项」处理：绝不能因为一次读库失败让整个对话 500
            return List.of();
        }
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> items = new ArrayList<>(list.size());
        for (Object element : list) {
            if (element instanceof Map<?, ?> map) {
                Map<String, Object> normalized = new LinkedHashMap<>();
                map.forEach((itemKey, itemValue) -> normalized.put(String.valueOf(itemKey), itemValue));
                items.add(normalized);
            }
        }
        return items;
    }

    /**
     * 读一个字符串字段。
     *
     * @param item JSON 对象
     * @param key  字段名
     * @return 去首尾空白后的字符串；缺失时为空串
     */
    private static String stringOf(Map<String, Object> item, String key) {
        Object value = item.get(key);
        return value == null ? "" : String.valueOf(value).strip();
    }

    /**
     * 读一个整数字段。
     *
     * @param item     JSON 对象
     * @param key      字段名
     * @param fallback 缺失或类型不对时的兜底值
     * @return 整数值
     */
    private static int intOf(Map<String, Object> item, String key, int fallback) {
        Object value = item.get(key);
        return value instanceof Number number ? number.intValue() : fallback;
    }

    /**
     * 读一个浮点字段。
     *
     * @param item     JSON 对象
     * @param key      字段名
     * @param fallback 缺失或类型不对时的兜底值
     * @return 浮点值
     */
    private static double doubleOf(Map<String, Object> item, String key, double fallback) {
        Object value = item.get(key);
        return value instanceof Number number ? number.doubleValue() : fallback;
    }

    /**
     * 读一个布尔字段。
     *
     * @param item     JSON 对象
     * @param key      字段名
     * @param fallback 缺失或类型不对时的兜底值
     * @return 布尔值
     */
    private static boolean boolOf(Map<String, Object> item, String key, boolean fallback) {
        Object value = item.get(key);
        return value instanceof Boolean flag ? flag : fallback;
    }

    /**
     * 一条自定义模型的归属信息。
     *
     * @param providerId 归一化后的供应商 id（内置原名或 custom-xxx）
     * @param info       模型静态描述（模型名、窗口、单价等）
     */
    private record CustomModel(
            // 归一化后的供应商 id
            String providerId,
            // 模型静态描述
            LlmDtos.ModelInfo info
    ) {
    }
}