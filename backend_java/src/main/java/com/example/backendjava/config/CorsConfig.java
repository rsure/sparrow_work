// 模块说明：开发态跨域配置。单机桌面应用只需要让本地页面能访问 127.0.0.1 的后端。
package com.example.backendjava.config;

// Spring 配置注解：声明这是一个配置类，容器启动时会被扫描
import org.springframework.context.annotation.Configuration;
// MVC 扩展接口：实现 addCorsMappings 可以追加全局跨域规则
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
// CORS 注册器：在 addCorsMappings 回调里声明路径、来源、方法与请求头
import org.springframework.web.servlet.config.annotation.CorsRegistry;
// 标准库：收集解析后的来源列表（容量小，用 ArrayList 足够）
import java.util.ArrayList;
// 标准库：List 接口，只在方法内部用于暂存解析结果
import java.util.List;

/**
 * 全局 CORS 配置。
 *
 * <p>为什么默认放开所有来源：</p>
 * <ul>
 *   <li>开发态页面来自 http://127.0.0.1:5173；</li>
 *   <li>Electron 打包后页面来自 file://，浏览器发送的 Origin 是字符串 "null"；</li>
 *   <li>本项目不引入登录态/Cookie，放开来源不会带来凭证泄露问题。</li>
 * </ul>
 *
 * <p>安全要求提高时，把 {@code APP_CORS_ORIGINS} 改成明确白名单（逗号分隔），并保持
 * allowCredentials=false。</p>
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    /** 应用配置：跨域来源白名单从这里读取，避免配置项写了却没人用。 */
    private final AppProperties properties;

    /**
     * 构造器注入配置。
     *
     * @param properties app.* 配置 Bean
     */
    public CorsConfig(AppProperties properties) {
        this.properties = properties;
    }

    /**
     * 为全部接口追加跨域规则。
     *
     * <p>为什么写 {@code /**} 而不是 {@code /api/**}：这里匹配的是「去掉 context-path 之后
     * 的查找路径」。application.yml 里配置了 {@code server.servlet.context-path=/api}，
     * 浏览器请求 {@code /api/health} 到达 Spring MVC 时路径已经被剥成 {@code /health}，
     * 所以 {@code /api/**} 一条规则都匹配不上——表现为跨域 GET 拿不到
     * {@code Access-Control-Allow-Origin}（DevTools 里请求是 200，但 Response 面板显示
     * "Failed to load response data"，页面报 TypeError: Failed to fetch），
     * 预检 OPTIONS 也会被直接拒成 403。</p>
     *
     * @param registry Spring MVC 提供的跨域注册器
     */
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                // 允许的来源：默认 "*"，可由 app.cors-origins 收窄成白名单
                .allowedOriginPatterns(resolveOriginPatterns())
                // 允许常用方法与 SSE 预检；OPTIONS 由 Spring 自动处理
                .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                // 允许任意请求头：前端会带 Content-Type / Authorization 等
                .allowedHeaders("*")
                // 让前端能读到流式响应相关头（需要时使用）
                .exposedHeaders("Content-Type", "Cache-Control", "X-Accel-Buffering")
                // 本项目不使用 Cookie，关闭凭证携带可以配合通配来源
                .allowCredentials(false)
                // 预检结果缓存 1 小时，减少开发态 OPTIONS 请求
                .maxAge(3600);
    }

    /**
     * 把 {@code app.cors-origins} 解析成 allowedOriginPatterns 需要的数组。
     *
     * <p>取值格式：逗号分隔的来源（如 {@code http://127.0.0.1:5173,http://localhost:5173}），
     * 或单个 {@code *} 表示全部放开。空值/全是空白的项会被过滤掉。</p>
     *
     * @return 至少含一个元素的来源模式数组；配置为空时回退为 {@code ["*"]}
     */
    private String[] resolveOriginPatterns() {
        List<String> patterns = new ArrayList<>();
        String raw = properties.getCorsOrigins();
        if (raw != null) {
            // 逗号分隔只是本项目约定的写法；Spring 自己不懂逗号，必须在这里切开
            for (String part : raw.split(",")) {
                String trimmed = part.trim();
                if (!trimmed.isEmpty()) {
                    patterns.add(trimmed);
                }
            }
        }
        // 配置漏填或全是逗号时回退到 "*"：宁可开发态放开，也不要让页面静默地连不上后端
        return patterns.isEmpty() ? new String[] { "*" } : patterns.toArray(new String[0]);
    }
}
