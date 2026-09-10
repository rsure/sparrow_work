// 模块说明：可选 Service 的获取工具。接口尚未实现时，让接口返回清晰的 501，而不是让应用启动失败。
package com.example.backendjava.util;

// Spring 的 ObjectProvider：按类型查找 Bean，找不到时返回 null 而不是抛 NoSuchBeanDefinitionException
import org.springframework.beans.factory.ObjectProvider;

// 业务异常（错误码 + 提示）
import com.example.backendjava.common.ApiException;

/**
 * Service 查找工具。
 *
 * <p>本工程的 Controller 全部依赖接口，具体实现由学习者后续补上。
 * 如果直接注入接口，缺少实现时 Spring 会启动失败；改用 ObjectProvider 后，
 * 应用仍可启动，未实现的接口会返回 {@code code=501} 的友好提示。</p>
 */
public final class ServiceSupport {

    /** 工具类禁止实例化。 */
    private ServiceSupport() {
    }

    /**
     * 取出 Service 实现；不存在时抛出 501 业务异常。
     *
     * @param provider 按类型查找 Bean 的 ObjectProvider
     * @param feature  功能中文名，用于拼出“XXX 尚未实现”的提示
     * @param <T>      Service 接口类型
     * @return 已注册的 Service 实例
     * @throws ApiException 当容器里没有对应实现时抛出，code=501
     */
    public static <T> T require(ObjectProvider<T> provider, String feature) {
        // getIfAvailable() 只在恰好一个 Bean 时返回；没有实现时返回 null
        T service = provider.getIfAvailable();
        if (service == null) {
            throw new ApiException(
                    501,
                    feature + " 尚未实现：请实现对应 Service 接口并注册为 Spring Bean"
            );
        }
        return service;
    }
}
