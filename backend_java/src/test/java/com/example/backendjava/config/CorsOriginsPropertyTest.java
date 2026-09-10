// 模块说明：验证 app.cors-origins 配置真的生效。默认 "*" 会放开全部来源，
// 这里改成白名单后，只有名单内的页面能读到响应，名单外的来源拿不到跨域头。
package com.example.backendjava.config;

// JUnit 5 测试注解：标记测试方法
import org.junit.jupiter.api.Test;
// Spring 测试注解：注入容器里的 MockMvc
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：走真实 DispatcherServlet，CORS 拦截器才会执行
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整容器：加载真实的 CorsConfig
import org.springframework.boot.test.context.SpringBootTest;
// 覆盖配置：用一个逗号分隔（且带空格）的白名单替换默认的 "*"，顺带测到解析时的 trim
import org.springframework.test.context.TestPropertySource;
// MockMvc：构造跨域请求并断言响应头
import org.springframework.test.web.servlet.MockMvc;
// HTTP 头常量：Origin 与 Access-Control-Allow-Origin
import org.springframework.http.HttpHeaders;
// 静态导入：GET 请求构造器
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
// 静态导入：断言响应头存在/不存在
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;

/**
 * app.cors-origins 白名单测试。
 *
 * <p>对应 application.yml 的 {@code app.cors-origins}（环境变量 {@code APP_CORS_ORIGINS}），
 * 与 Python 侧同名配置语义一致：默认 {@code *}，可收窄为逗号分隔的白名单。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "app.cors-origins= http://127.0.0.1:5173 , http://localhost:5173 ")
class CorsOriginsPropertyTest {

    /** 白名单里的来源：开发态 Vite 页面，必须被放行。 */
    private static final String ALLOWED_ORIGIN = "http://127.0.0.1:5173";

    /** 白名单外的来源：模拟别的网页偷偷调用本机接口，必须拿不到跨域头。 */
    private static final String DENIED_ORIGIN = "http://evil.example";

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 验证白名单内的来源能拿到 Access-Control-Allow-Origin。
     *
     * <p>配置里故意在逗号两侧留了空格：如果解析时没 trim，这个来源就匹配不上，
     * 本用例会失败——这正是它存在的意义。</p>
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void allowedOriginShouldReceiveCorsHeader() throws Exception {
        // 显式声明 contextPath，模拟真实的 /api/health 地址
        mockMvc.perform(get("/api/health").contextPath("/api")
                        .header(HttpHeaders.ORIGIN, ALLOWED_ORIGIN))
                // 白名单命中时回显请求来源，浏览器才会把响应体交给页面
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, ALLOWED_ORIGIN));
    }

    /**
     * 验证白名单外的来源拿不到 Access-Control-Allow-Origin，浏览器会拦下响应体。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void deniedOriginShouldNotReceiveCorsHeader() throws Exception {
        mockMvc.perform(get("/api/health").contextPath("/api")
                        .header(HttpHeaders.ORIGIN, DENIED_ORIGIN))
                // 只要没有这个头，浏览器就不会把响应交给页面脚本
                .andExpect(header().doesNotExist(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN));
    }
}
