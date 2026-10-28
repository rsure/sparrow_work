// 模块说明：limit 契约的接口级测试。
//
// 为什么用集成测试而不是单元测试：这条契约的真身是「注解 + Spring 的校验链路 + 异常处理器」，
// 单独调 service 方法看不到它们。只有走一遍 MockMvc，才能证明「客户端传越界值真的收到 400」、
// 「默认值真的来自 controller 的 defaultValue」、「has_more 真的出现在 JSON 里」。
package com.example.backendjava.controller;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// Spring 自动注入测试依赖
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：不启动真实端口，直接走 Spring MVC 处理链
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整 Spring 容器：同时验证仓库派生查询与参数校验都装配正确
import org.springframework.boot.test.context.SpringBootTest;
// MockMvc：构造请求、断言响应
import org.springframework.test.web.servlet.MockMvc;
// 事务回滚：本测试只读，加上它是为了和仓库其它集成测试保持一致的隔离习惯
import org.springframework.transaction.annotation.Transactional;
// 静态导入：GET 请求构造器
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
// 静态导入：HTTP 状态码断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// 静态导入：JSON 字段断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

/**
 * limit 契约集成测试。
 *
 * <p>覆盖三条约定（见 docs/adr/0001-limit-越界一律报错.md）：</p>
 * <ol>
 *   <li>默认值只表达「没传」，由 controller 的 {@code defaultValue} 提供；</li>
 *   <li>显式越界（小于 1 或超过上限）一律 400，不做静默截断；</li>
 *   <li>历史消息响应必须带 {@code has_more}，让前端知道「还有更早的」。</li>
 * </ol>
 *
 * <p>注意：{@code server.servlet.context-path=/api}，请求路径要显式带 /api 前缀，
 * 并且要 {@code .contextPath("/api")}，否则 Spring 认为路径不匹配。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class ChatLimitContractTest {

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 历史消息：limit 小于 1 必须 400，而不是被悄悄换成默认值。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void historyShouldRejectZeroLimit() throws Exception {
        mockMvc.perform(get("/api/chat/history/sessions/no-such-session").contextPath("/api")
                        .param("limit", "0"))
                // 越界是客户端错误：告知并让它改，而不是返回一份「看起来正常」的数据
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    /**
     * 历史消息：limit 超过上限（200）必须 400。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void historyShouldRejectLimitAboveMax() throws Exception {
        mockMvc.perform(get("/api/chat/history/sessions/no-such-session").contextPath("/api")
                        .param("limit", "201"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    /**
     * 历史消息：不传 limit 时用默认值 200，响应带 has_more（空会话为 false）。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void historyShouldDefaultToMaxLimitAndReportHasMore() throws Exception {
        // 不存在的会话：一条消息都没有，has_more 必须是 false 而不是 null
        mockMvc.perform(get("/api/chat/history/sessions/no-such-session").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.session_id").value("no-such-session"))
                .andExpect(jsonPath("$.messages").isArray())
                .andExpect(jsonPath("$.messages.length()").value(0))
                .andExpect(jsonPath("$.has_more").value(false));

        // 边界值 200 本身必须被接受（上限是「包含 200」）
        mockMvc.perform(get("/api/chat/history/sessions/no-such-session").contextPath("/api")
                        .param("limit", "200"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.has_more").value(false));
    }

    /**
     * 会话列表：limit 超过上限（100）必须 400。
     *
     * <p>这条以前是「悄悄截到 100」——客户端永远不知道自己只拿到了一部分。</p>
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void listSessionsShouldRejectLimitAboveMax() throws Exception {
        mockMvc.perform(get("/api/chat/sessions").contextPath("/api")
                        .param("limit", "101"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    /**
     * 会话列表：默认值 20 必须能用（不传 limit 走默认分支）。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void listSessionsShouldAcceptDefaultLimit() throws Exception {
        mockMvc.perform(get("/api/chat/sessions").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessions").isArray());
    }
}
