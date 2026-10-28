// 模块说明：除 chat 之外的 limit 端点的契约测试。
//
// 为什么单独一个类：ChatLimitContractTest 只覆盖了 /chat/sessions 与 /chat/history，
// 而「越界一律 400」是整张契约表的约定。如果只测 chat，其它端点悄悄退回「静默截断」
// 甚至「完全不校验」都不会被发现——rag documents 以前正是完全没有上限的那个。
package com.example.backendjava.controller;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// Spring 自动注入测试依赖
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：不启动真实端口，直接走 Spring MVC 处理链
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整 Spring 容器：校验链路（@Validated + @Min/@Max）必须真的装配上才有效
import org.springframework.boot.test.context.SpringBootTest;
// MockMvc：构造请求、断言响应
import org.springframework.test.web.servlet.MockMvc;
// 事务回滚：本测试只读，加上它是为了和仓库其它集成测试保持一致的隔离习惯
import org.springframework.transaction.annotation.Transactional;
// 契约表：断言里的上限直接取常量，避免测试自己写死一份数字
import com.example.backendjava.common.PageLimits;
// 静态导入：GET 请求构造器
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
// 静态导入：HTTP 状态码断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// 静态导入：JSON 字段断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

/**
 * 其余 limit 端点的越界测试。
 *
 * <p>约定见 {@code docs/adr/0001-limit-越界一律报错.md}：显式越界（小于 1 或超过上限）
 * 一律 400，不做静默截断。参数校验发生在方法体之前，所以即使会话不存在，
 * 只要 limit 越界也应该先收到 400。</p>
 *
 * <p>注意：{@code server.servlet.context-path=/api}，请求路径要显式带 /api 前缀，
 * 并且要 {@code .contextPath("/api")}，否则 Spring 认为路径不匹配。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class PageLimitContractTest {

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 断言某个端点在 limit 取两种越界值时都返回 400。
     *
     * @param path 接口路径（含 /api 前缀）
     * @param max  该端点的上限；用于构造「上限 + 1」
     * @throws Exception MockMvc 执行失败时抛出
     */
    private void assertRejectsOutOfRange(String path, int max) throws Exception {
        // 下界：0 条没有意义，必须报错而不是被换成默认值
        mockMvc.perform(get(path).contextPath("/api").param("limit", "0"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
        // 上界：超过上限会让「一次返回多少条」失去控制
        mockMvc.perform(get(path).contextPath("/api").param("limit", String.valueOf(max + 1)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    /**
     * 文件搜索：上限 50。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void fileSearchShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/file/search", PageLimits.MAX_FILE_SEARCH);
    }

    /**
     * 审计日志：上限 500。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void auditShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/audit", PageLimits.MAX_AUDIT);
    }

    /**
     * 记忆列表：上限 500。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void memoryShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/memory", PageLimits.MAX_MEMORY);
    }

    /**
     * 轨迹会话：上限 200。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void traceSessionsShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/trace/sessions", PageLimits.MAX_TRACE_SESSIONS);
    }

    /**
     * 轨迹轮次：上限 200。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void traceTurnsShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/trace/sessions/no-such-session/turns", PageLimits.MAX_TRACE_TURNS);
    }

    /**
     * 轨迹事件：上限 5000。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void traceEventsShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/trace/sessions/no-such-session", PageLimits.MAX_TRACE_EVENTS);
    }

    /**
     * 文档列表：上限 200 —— 这是以前唯一完全没有上限的端点。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void ragDocumentsShouldRejectOutOfRangeLimit() throws Exception {
        assertRejectsOutOfRange("/api/rag/documents", PageLimits.MAX_RAG_DOCS);
    }
}
