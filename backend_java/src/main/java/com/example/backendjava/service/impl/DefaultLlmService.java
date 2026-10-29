// 模块说明：模型服务的默认实现。完成供应商清单、模型构建与连通性测试。
package com.example.backendjava.service.impl;

// Spring 服务注解：把本类注册成 LlmService 的唯一实现
import org.springframework.stereotype.Service;
// 项目内业务异常：配置错误时抛出，由全局异常处理器转成 ApiResponse
import com.example.backendjava.common.ApiException;
// LangChain4j 同步模型接口
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式模型接口
import dev.langchain4j.model.chat.StreamingChatModel;
// 模型业务接口：供应商清单、连通性测试与模型装配
import com.example.backendjava.llm.LlmService;
// 模型工厂路由：按供应商 id 选择具体工厂
import com.example.backendjava.llm.LlmModelFactoryRouter;
// 供应商与模型清单的查询入口（内置 + 用户自定义）
import com.example.backendjava.llm.LlmProviderRegistry;
// 模型接口的供应商/模型/探测 DTO 容器
import com.example.backendjava.dto.LlmDtos;
// 装配一个模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;
// 密钥仓库：从加密存储里取出用户在设置页保存的 API Key
import com.example.backendjava.settings.SecretStore;

// 标准库：List 用于供应商清单
import java.util.List;

/**
 * 模型服务默认实现。
 *
 * <p>它不依赖业务数据库，只依赖模型注册表、工厂路由器与密钥仓库，
 * 因此可以直接用来验证 Java 到模型供应商的连通性。</p>
 */
@Service
public class DefaultLlmService implements LlmService {

    /** 供应商与模型清单（内置 + 自定义端点）。 */
    private final LlmProviderRegistry registry;

    /** 模型工厂路由器：按 providerId 选择 OpenAI 兼容等具体实现。 */
    private final LlmModelFactoryRouter factoryRouter;

    /** 密钥仓库：用户在设置页保存的 Key 存这里，测试连接时直接复用。 */
    private final SecretStore secretStore;

    /**
     * 构造器注入。
     *
     * @param registry      模型注册表
     * @param factoryRouter 模型工厂路由器
     * @param secretStore   密钥仓库
     */
    public DefaultLlmService(LlmProviderRegistry registry,
                             LlmModelFactoryRouter factoryRouter,
                             SecretStore secretStore) {
        this.registry = registry;
        this.factoryRouter = factoryRouter;
        this.secretStore = secretStore;
    }

    /**
     * 返回全部供应商与模型。
     *
     * @return 供应商清单
     */
    @Override
    public LlmDtos.ProvidersResult listProviders() {
        return new LlmDtos.ProvidersResult(registry.listProviders());
    }

    /**
     * 发一次极小的请求，验证密钥、模型名与网络是否可用。
     *
     * <p>密钥取值顺序：<b>请求体显式传入（本地调试）</b> → <b>密钥库</b>。
     * 前端点「测试连接」时不会把明文 Key 再发一次，所以必须能读到密钥库。</p>
     *
     * @param request 测试参数
     * @return 结构化测试结果；不会抛出网络异常
     */
    @Override
    public LlmDtos.ProbeResult probe(LlmDtos.ProbeRequest request) {
        // 记录开始时间，用于计算耗时；使用纳秒避免短请求显示 0ms
        long startedNanos = System.nanoTime();
        try {
            // 供应商必须存在；不存在时直接 404（provider_id 为 null 也会走到这里，提示里带 null）
            LlmDtos.ProviderInfo provider = registry.findProvider(request.providerId())
                    .orElseThrow(() -> new ApiException(404, "未知的模型供应商：" + request.providerId()));

            // 解析模型：未指定模型名时取该供应商的默认模型
            LlmDtos.ModelInfo modelInfo = registry.resolveModel(request.providerId(), request.model());

            // 接口地址优先用请求里显式传入的，其次用注册表默认值
            String baseUrl = isBlank(request.baseUrl()) ? provider.baseUrl() : request.baseUrl();

            // 密钥：请求体 > 密钥库；只有本地调试才会把 Key 放进请求体
            String apiKey = isBlank(request.apiKey()) ? secretOf(provider) : request.apiKey().strip();
            if (provider.requiresKey() && isBlank(apiKey)) {
                throw new ApiException(400, "尚未配置 " + provider.label() + " 的 API 密钥，"
                        + "请到设置页的「模型」分区填写（对应设置项：" + provider.secretKey() + "）");
            }

            // 组装模型参数：温度固定 0，尽量让 ping 请求稳定
            LlmModelSpec spec = new LlmModelSpec(
                    request.providerId(),
                    modelInfo.model(),
                    apiKey,
                    baseUrl,
                    0.0,
                    null
            );

            // 真正发一次网络请求；只要没抛异常就认为连通
            ChatModel chatModel = factoryRouter.createChatModel(spec);
            chatModel.chat("ping");

            return new LlmDtos.ProbeResult(true, elapsedMillis(startedNanos), null, null);
        } catch (Exception exception) {
            // 配置类异常与网络类异常分开提示，方便用户判断是去填 Key 还是查网络
            String kind = classifyError(exception);
            return new LlmDtos.ProbeResult(
                    false,
                    elapsedMillis(startedNanos),
                    // 错误信息截断到 300 字，避免把整段堆栈或超长响应返回给前端
                    truncate(exception.getMessage(), 300),
                    kind
            );
        }
    }

    /**
     * 创建同步聊天模型。
     *
     * @param spec 模型装配参数
     * @return 同步模型
     */
    @Override
    public ChatModel createChatModel(LlmModelSpec spec) {
        return factoryRouter.createChatModel(spec);
    }

    /**
     * 创建流式聊天模型。
     *
     * @param spec 模型装配参数
     * @return 流式模型
     */
    @Override
    public StreamingChatModel createStreamingModel(LlmModelSpec spec) {
        return factoryRouter.createStreamingModel(spec);
    }

    /**
     * 从密钥库取出供应商的 API Key。
     *
     * @param provider 供应商描述（提供密钥在库里的名字）
     * @return 密钥；供应商不需要密钥、还没配置或读库失败时返回 null
     */
    private String secretOf(LlmDtos.ProviderInfo provider) {
        if (isBlank(provider.secretKey())) {
            return null;
        }
        try {
            return secretStore.getSecret(provider.secretKey()).orElse(null);
        } catch (RuntimeException e) {
            // 密钥库读失败按「没配置」处理：让上层给出「去设置页填写」的提示，而不是 500
            return null;
        }
    }

    /**
     * 把纳秒起点换算成毫秒耗时。
     *
     * @param startedNanos System.nanoTime() 的起始值
     * @return 毫秒数
     */
    private long elapsedMillis(long startedNanos) {
        return (System.nanoTime() - startedNanos) / 1_000_000;
    }

    /**
     * 粗判异常属于哪一类，供前端给出不同提示。
     *
     * @param exception 捕获到的异常
     * @return secret / model / network / unknown
     */
    private String classifyError(Exception exception) {
        // 业务异常本身已经带了明确语义，按 code 分类最可靠
        if (exception instanceof ApiException apiException) {
            if (apiException.getCode() == 400) {
                return "secret";
            }
            if (apiException.getCode() == 404) {
                return "model";
            }
        }

        // 其它异常只能靠关键字粗判；不同 SDK 的文案差异很大，这里只求够用
        String text = exception.getMessage() == null ? "" : exception.getMessage().toLowerCase();
        if (text.contains("api key") || text.contains("401") || text.contains("403")
                || text.contains("unauthorized") || text.contains("密钥")) {
            return "secret";
        }
        if (text.contains("model") || text.contains("404") || text.contains("模型")) {
            return "model";
        }
        if (text.contains("timeout") || text.contains("connect") || text.contains("network")) {
            return "network";
        }
        return "unknown";
    }

    /**
     * 判断字符串是否为空白。
     *
     * @param value 待判断字符串
     * @return null、空串、纯空白都返回 true
     */
    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    /**
     * 截断过长的错误信息。
     *
     * @param value     原始文本
     * @param maxLength 最大字符数
     * @return 截断后的文本；null 原样返回
     */
    private String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}