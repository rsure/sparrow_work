// 模块说明：设置接口的集成测试。启动完整 Spring 容器 + MockMvc，验证 URL 路径、JSON 字段名、
// 业务码与错误文案都和 Python 侧一致（只看单元测试无法发现 @JsonProperty 写错或路由冲突）。
package com.example.backendjava.controller;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// Spring 自动注入测试依赖
import org.springframework.beans.factory.annotation.Autowired;
// 自动配置 MockMvc：不启动真实端口，直接走 Spring MVC 处理链
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
// 启动完整 Spring 容器：同时验证 SQLite、schema.sql 与仓库能正常工作
import org.springframework.boot.test.context.SpringBootTest;
// MockMvc：构造请求、断言响应
import org.springframework.test.web.servlet.MockMvc;
// MvcResult：需要从响应里取出 id 继续下一步操作
import org.springframework.test.web.servlet.MvcResult;
// 事务回滚：测试写库（工作区、设置行、密钥行）在方法结束后全部撤销，不污染 app.db
import org.springframework.transaction.annotation.Transactional;
// 媒体类型常量：请求体是 JSON
import org.springframework.http.MediaType;
// 静态导入：GET / POST / PUT / DELETE 请求构造器
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
// 静态导入：HTTP 状态码断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// 静态导入：JSON 字段断言
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;

// 项目内：读取响应 JSON，取出新建出来的 id / 当前值
import com.example.backendjava.util.JsonUtils;

/**
 * 设置接口集成测试。
 *
 * <p>与 Python 侧的对照点：路径（/api/settings/*、单数 /workspace 与复数 /workspaces 并存）、
 * 响应外壳（code/message/data）、snake_case 字段名、业务码 400/404。</p>
 *
 * <p>注意：{@code server.servlet.context-path=/api}，所以请求路径要显式带 /api 前缀。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class SettingsControllerTest {

    /** Spring MVC 测试入口；由 @AutoConfigureMockMvc 注入。 */
    @Autowired
    private MockMvc mockMvc;

    /**
     * GET /api/settings 必须返回声明里的默认值，且不含任何密钥键。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void getSettingsShouldReturnDeclaredDefaults() throws Exception {
        mockMvc.perform(get("/api/settings").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                // 未配置过的键也要有值：默认值由注册表兜底
                .andExpect(jsonPath("$.data.values['llm.model']").isNotEmpty())
                // 密钥有独立的 secrets 接口，绝不能混进全量设置
                .andExpect(jsonPath("$.data.values['secrets.deepseek.api_key']").doesNotExist());
    }

    /**
     * GET /api/settings/meta 返回每条声明的 schema，字段名必须是 snake_case。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void getSettingsMetaShouldDescribeEveryDefinition() throws Exception {
        mockMvc.perform(get("/api/settings/meta").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                // 至少要有若干条声明，字段名与 Python 一致（default / option_labels）
                .andExpect(jsonPath("$.data[0].key").isNotEmpty())
                .andExpect(jsonPath("$.data[0].default").exists())
                .andExpect(jsonPath("$.data[0].option_labels").hasJsonPath());
    }

    /**
     * PUT /api/settings 写入合法值后应能读回；未声明的键必须整批拒绝并说明原因。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void putSettingsShouldPersistThenRejectUnknownKey() throws Exception {
        mockMvc.perform(put("/api/settings").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{\"agent.max_iterations\":30}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.values['agent.max_iterations']").value(30));

        // 未声明的键：HTTP 仍是 200，业务码 400（本项目统一用响应体表达业务错误）
        mockMvc.perform(put("/api/settings").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{\"nope.key\":1}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(400))
                .andExpect(jsonPath("$.message").value("未声明的设置键：nope.key"));

        // 越界值：文案要能让用户照抄改正
        mockMvc.perform(put("/api/settings").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{\"agent.max_iterations\":1000}}"))
                .andExpect(jsonPath("$.code").value(400))
                .andExpect(jsonPath("$.message").value("设置 agent.max_iterations 不能大于 50（收到 1000）"));
    }

    /**
     * 工作区全生命周期：新建 → 改名 → 切换生效 → 删除。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void workspaceLifecycleShouldWork() throws Exception {
        MvcResult created = mockMvc.perform(post("/api/settings/workspaces").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"测试工作区\",\"roots\":[]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.name").value("测试工作区"))
                .andExpect(jsonPath("$.data.active").isBoolean())
                .andReturn();
        String id = JsonUtils.readTree(created.getResponse().getContentAsString())
                .path("data").path("id").asText();

        // 改名与改根目录：只传 name，roots 保持原值
        mockMvc.perform(put("/api/settings/workspaces/" + id).contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"改名后的工作区\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("改名后的工作区"));

        // 切换生效：返回的 active_id 必须就是这个 id
        mockMvc.perform(post("/api/settings/workspaces/active").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"id\":\"" + id + "\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.active_id").value(id));

        // 列表里必须出现这个工作区，且 active=true
        mockMvc.perform(get("/api/settings/workspaces").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.active_id").value(id));

        // 删除：deleted=true
        mockMvc.perform(delete("/api/settings/workspaces/" + id).contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true));

        // 再删一次：deleted=false，不报错（幂等）
        mockMvc.perform(delete("/api/settings/workspaces/" + id).contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(false));
    }

    /**
     * 切换到不存在的工作区：业务码 404，消息说明是哪个 id。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void activateUnknownWorkspaceShouldReturn404Code() throws Exception {
        mockMvc.perform(post("/api/settings/workspaces/active").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"id\":\"w-999\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(404))
                .andExpect(jsonPath("$.message").value("工作区不存在：w-999"));
    }

    /**
     * 历史遗留的单数接口：PUT 保存现存目录，GET 原样读回。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void legacyWorkspaceRootsShouldRoundTrip() throws Exception {
        // 用系统临时目录：它一定存在，能验证「只保存真实存在的目录」这条规则
        String existing = System.getProperty("java.io.tmpdir").replace("\\", "\\\\");
        mockMvc.perform(put("/api/settings/workspace").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"paths\":[\"" + existing + "\",\"Z:\\\\不存在的目录\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                // 不存在的路径必须被过滤掉，只回真实生效的那个
                .andExpect(jsonPath("$.data.length()").value(1));

        mockMvc.perform(get("/api/settings/workspace").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(1));
    }

    /**
     * 导出必须带格式标识并脱敏；导入只写合法键，脱敏占位符与未知键如实跳过。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void exportAndImportShouldFollowPythonRules() throws Exception {
        mockMvc.perform(get("/api/settings/export").contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.format").value("app-settings/1"))
                .andExpect(jsonPath("$.data.exported_at").isNotEmpty())
                .andExpect(jsonPath("$.data.values").isMap());

        // 合法键写入成功
        mockMvc.perform(post("/api/settings/import").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"format\":\"app-settings/1\",\"values\":{\"agent.max_iterations\":12}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.applied[0]").value("agent.max_iterations"))
                .andExpect(jsonPath("$.data.values['agent.max_iterations']").value(12));

        // 未知键与脱敏占位符按原因跳过，但不能让整份配置失败
        mockMvc.perform(post("/api/settings/import").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{\"nope.key\":1,\"mcp.servers\":\"***REDACTED***\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.applied.length()").value(0))
                .andExpect(jsonPath("$.data.skipped[0].reason").value("本机未声明的设置键"))
                .andExpect(jsonPath("$.data.skipped[1].reason").value("导出时已脱敏，导入会污染配置"));

        // 不认识的格式：整份拒绝
        mockMvc.perform(post("/api/settings/import").contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"format\":\"other/9\",\"values\":{}}"))
                .andExpect(jsonPath("$.code").value(400))
                .andExpect(jsonPath("$.message").value("不认识的配置格式：other/9（本机只支持 app-settings/1）"));
    }

    /**
     * 密钥只进不出：写入后只能读到脱敏值，删除返回 deleted 标记。
     *
     * @throws Exception MockMvc 执行失败时抛出
     */
    @Test
    void secretLifecycleShouldNeverLeakPlainValue() throws Exception {
        String name = "test.api_key";
        mockMvc.perform(put("/api/settings/secrets/" + name).contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"value\":\"sk-1234567890abcdef\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.set").value(true))
                // 打码规则与 Python mask_secret 一致：前 3 + **** + 后 4
                .andExpect(jsonPath("$.data.masked").value("sk-****cdef"));

        mockMvc.perform(get("/api/settings/secrets/" + name).contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.set").value(true))
                .andExpect(jsonPath("$.data.masked").value("sk-****cdef"));

        // 空值不允许当成「清空」：必须走删除接口，否则用户会误以为保存成功
        mockMvc.perform(put("/api/settings/secrets/" + name).contextPath("/api")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"value\":\"\"}"))
                .andExpect(jsonPath("$.code").value(400));

        mockMvc.perform(delete("/api/settings/secrets/" + name).contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true));

        mockMvc.perform(get("/api/settings/secrets/" + name).contextPath("/api"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.set").value(false))
                .andExpect(jsonPath("$.data.masked").doesNotExist());
    }
}
