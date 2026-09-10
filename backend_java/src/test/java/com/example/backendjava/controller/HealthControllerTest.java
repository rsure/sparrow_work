// 模块说明：健康检查接口的集成测试。验证 Java 骨架启动后 Electron 能拿到 code=0。
package com.example.backendjava.controller;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// Spring 自动注入测试依赖
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：不启动真实端口，直接调用 Spring MVC 处理链
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整 Spring 容器：同时验证数据源、SQLite 检查点等基础设施能初始化
import org.springframework.boot.test.context.SpringBootTest;
// MockMvc：构造 HTTP 请求并断言响应
import org.springframework.test.web.servlet.MockMvc;
// 静态导入：构造 GET 请求
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
// 静态导入：断言 HTTP 状态码
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// 静态导入：断言 JSON 字段
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

/**
 * 健康检查集成测试。
 *
 * <p>注意：application.yml 里配置了 {@code server.servlet.context-path=/api}，
 * 所以 MockMvc 的请求路径也要带 {@code /api} 前缀。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
class HealthControllerTest {

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 验证 GET /api/health 返回统一外壳与 Java 运行时信息。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void healthShouldReturnOk() throws Exception {
        // MockMvc 不会自动应用 server.servlet.context-path；显式声明 contextPath 才能模拟真实 URL
        mockMvc.perform(get("/api/health").contextPath("/api"))
                // HTTP 层面必须成功
                .andExpect(status().isOk())
                // 业务码必须为 0，Electron 的 waitForHealth 依赖这个字段
                .andExpect(jsonPath("$.code").value(0))
                // 健康状态必须为 ok
                .andExpect(jsonPath("$.data.status").value("ok"))
                // 运行时类型必须是 Java，便于区分 Python 后端
                .andExpect(jsonPath("$.data.runtime").value("Java"));
    }
}
