// 模块说明：跨域配置的回归测试。固定住「配置了 context-path=/api 之后，跨域规则依然生效」这条结论，
// 防止以后有人再把匹配路径写回 /api/**，导致前端拿到 200 却读不到响应体。
package com.example.backendjava.config;

// JUnit 5 测试注解：标记测试方法
import org.junit.jupiter.api.Test;
// Spring 测试注解：把容器里的 MockMvc 自动注入进来
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：走真实的 DispatcherServlet，CORS 拦截器才会被真正执行
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整 Spring 容器：与 HealthControllerTest 保持一致，确保 CorsConfig 被真实加载
import org.springframework.boot.test.context.SpringBootTest;
// MockMvc：构造带 Origin 的跨域请求并断言响应头
import org.springframework.test.web.servlet.MockMvc;
// HTTP 头常量：Origin、Access-Control-Request-Method、Access-Control-Allow-* 等
import org.springframework.http.HttpHeaders;
// 静态导入：断言 HTTP 状态码
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// 静态导入：断言响应头（跨域成败的唯一判据就是这几个头）
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
// 静态导入：OPTIONS 请求构造器，用于模拟浏览器预检
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
// 静态导入：GET 请求构造器，用于模拟简单跨域请求
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
// Hamcrest 匹配器：断言 Access-Control-Allow-Methods 里包含某个方法
import static org.hamcrest.Matchers.containsString;

/**
 * 跨域配置回归测试。
 *
 * <p>历史问题：CorsRegistry 曾写成 {@code addMapping("/api/**")}，而 context-path 正好是
 * {@code /api}，两者叠加后没有任何一条规则生效。浏览器侧的典型症状是：</p>
 * <ul>
 *   <li>简单 GET 返回 200，但没有 {@code Access-Control-Allow-Origin}，浏览器把响应体丢弃，
 *       控制台报 CORS 错误，DevTools 的 Response 面板显示 "Failed to load response data"；</li>
 *   <li>带自定义头的 POST/PUT 在预检阶段就被 403 拦下。</li>
 * </ul>
 */
@SpringBootTest
@AutoConfigureMockMvc
class CorsConfigTest {

    /** 浏览器开发态页面的来源，用来模拟 Vite(5173) 访问 8000 端口的真实场景。 */
    private static final String BROWSER_ORIGIN = "http://127.0.0.1:5173";

    /** 打包后 Electron 页面来自 file://，浏览器发送的 Origin 字面量就是 "null"。 */
    private static final String FILE_PROTOCOL_ORIGIN = "null";

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 验证简单跨域 GET 会带回 Access-Control-Allow-Origin，浏览器才肯把响应体交给页面。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void crossOriginGetShouldReturnAllowOriginHeader() throws Exception {
        // MockMvc 不会自动应用 context-path，显式声明才能模拟真实的 /api/health 地址
        mockMvc.perform(get("/api/health").contextPath("/api")
                        // Origin 是浏览器判断跨域的依据，缺了它就测不到 CORS 逻辑
                        .header(HttpHeaders.ORIGIN, BROWSER_ORIGIN))
                // 接口本身仍然要成功
                .andExpect(status().isOk())
                // allowedOriginPatterns("*") 会原样回显请求来源，前端才认这个响应
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, BROWSER_ORIGIN));
    }

    /**
     * 验证 file:// 场景（Origin: null）同样被放行，否则打包后的 Electron 页面读不到数据。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void crossOriginGetFromFileProtocolShouldBeAllowed() throws Exception {
        mockMvc.perform(get("/api/health").contextPath("/api")
                        // Electron 打包后渲染进程的 Origin 固定为字符串 "null"
                        .header(HttpHeaders.ORIGIN, FILE_PROTOCOL_ORIGIN))
                .andExpect(status().isOk())
                // 通配来源需要原样回显 "null"，浏览器才会认为允许
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, FILE_PROTOCOL_ORIGIN));
    }

    /**
     * 验证预检 OPTIONS 不再返回 403：带 Origin + Access-Control-Request-Method 的请求
     * 就是浏览器发预检的形态，必须回 200 并带齐允许的方法。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void preflightRequestShouldBeAccepted() throws Exception {
        mockMvc.perform(options("/api/health").contextPath("/api")
                        // 这三个头齐全，才算「预检请求」，而不是普通的 OPTIONS
                        .header(HttpHeaders.ORIGIN, BROWSER_ORIGIN)
                        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "GET"))
                // 预检通过时 Spring 返回 200；403 会让浏览器直接放弃真实请求
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, BROWSER_ORIGIN))
                // 允许的方法里必须包含 GET，否则浏览器认为真实请求不被许可
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_METHODS, containsString("GET")));
    }
}
