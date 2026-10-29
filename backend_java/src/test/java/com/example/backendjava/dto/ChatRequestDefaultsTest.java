// 模块说明：聊天请求体「可选字段」的默认值与校验单元测试。
//
// 为什么单独写这个测试：曾经的 bug 是「前端不传 doc_top_k / max_iterations → int 被填 0
// → @Min(1) 判成越界 → 请求 400，withDefaults() 里的默认值永远来不及生效」。
// 只断言「默认值是 5」不够，必须同时断言两件事：
//   1) 字段为 null（= 前端没传）时校验通过，并且 withDefaults() 补成 5 / 25；
//   2) 字段显式传 0 时校验失败（docs/adr/0001：显式越界一律报错，不静默改成默认值）。
package com.example.backendjava.dto;

// JUnit 5 测试注解
import org.junit.jupiter.api.Test;
// Jakarta 校验入口：拿默认的 Hibernate Validator 实现，不启动 Spring 容器
import jakarta.validation.Validation;
// Jakarta 校验器：对 DTO 实例跑一遍注解上的约束
import jakarta.validation.Validator;
// Jakarta 约束违反项：从里面取中文提示，断言「报的是哪条错」
import jakarta.validation.ConstraintViolation;
// 标准库：Set 装违反项；Collectors 把提示文案拼成一段便于断言
import java.util.Set;
import java.util.stream.Collectors;
// 静态导入：断言方法（assertEquals / assertTrue）
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * ChatRequest / ChatResumeRequest 的默认值与校验约定。
 *
 * <p>这些约定与 Python 侧 backend/app/controllers/chat_controller.py 的
 * ChatRequest 字段定义一一对应：doc_top_k 默认 5、范围 1~20；
 * max_iterations 默认 25、范围 1~50。</p>
 */
class ChatRequestDefaultsTest {

    /** 全类共用一份校验器：构建一次就够，重复构建没有意义还慢。 */
    private static final Validator VALIDATOR = Validation.buildDefaultValidatorFactory().getValidator();

    /**
     * 把违反项拼成「字段: 提示」的形式，方便断言具体报的是哪条错。
     *
     * @param violations 校验器返回的违反项集合
     * @return 用 ";" 连接的文案；没有违反项时返回空串
     */
    private static String messages(Set<? extends ConstraintViolation<?>> violations) {
        return violations.stream()
                .map(violation -> violation.getPropertyPath() + ": " + violation.getMessage())
                .collect(Collectors.joining("; "));
    }

    /**
     * 前端普通对话（非 doc 模式）的请求体：两个可选字段都不传，必须校验通过并补默认值。
     */
    @Test
    void omittedOptionalFieldsShouldPassValidationAndFallBackToDefaults() {
        // 字段缺失在 Java 侧就是 null：这是 Jackson 对 Integer 字段的填充结果
        ChatDtos.ChatRequest request = new ChatDtos.ChatRequest("你好", null, null, null, null, false);

        // 关键回归点：null 不能被 @Min/@Max 判成越界，否则前端普通提问会直接 400
        assertTrue(VALIDATOR.validate(request).isEmpty(),
                "不传 doc_top_k / max_iterations 时不应报校验错误，实际：" + messages(VALIDATOR.validate(request)));

        // 归一化后业务层拿到的都是确定值，不需要再判断 null
        ChatDtos.ChatRequest normalized = request.withDefaults();
        assertEquals("agent", normalized.mode());
        assertEquals(5, normalized.docTopK().intValue());
        assertEquals(25, normalized.maxIterations().intValue());
    }

    /**
     * 显式传越界值仍然必须报错：0 不是「没传」，不能被悄悄换成默认值（docs/adr/0001）。
     */
    @Test
    void explicitOutOfRangeValuesShouldStillFailValidation() {
        // doc_top_k=0：低于下限
        ChatDtos.ChatRequest zeroTopK = new ChatDtos.ChatRequest("你好", null, null, 0, null, false);
        String topKErrors = messages(VALIDATOR.validate(zeroTopK));
        assertTrue(topKErrors.contains("doc_top_k 最小为 1"), "doc_top_k=0 应报最小值错误，实际：" + topKErrors);

        // doc_top_k=21：高于上限
        ChatDtos.ChatRequest tooLargeTopK = new ChatDtos.ChatRequest("你好", null, null, 21, null, false);
        String topKMaxErrors = messages(VALIDATOR.validate(tooLargeTopK));
        assertTrue(topKMaxErrors.contains("doc_top_k 最大为 20"), "doc_top_k=21 应报最大值错误，实际：" + topKMaxErrors);

        // max_iterations=0：同样不能当成「没传」
        ChatDtos.ChatRequest zeroIterations = new ChatDtos.ChatRequest("你好", null, null, null, 0, false);
        String iterationErrors = messages(VALIDATOR.validate(zeroIterations));
        assertTrue(iterationErrors.contains("max_iterations 最小为 1"),
                "max_iterations=0 应报最小值错误，实际：" + iterationErrors);
    }

    /**
     * 合法范围内的显式值必须原样保留，不被默认值覆盖。
     */
    @Test
    void explicitValidValuesShouldBeKept() {
        ChatDtos.ChatRequest request = new ChatDtos.ChatRequest("\\doc 这份文档讲了什么", null, "doc", 3, 40, false);

        assertTrue(VALIDATOR.validate(request).isEmpty(), "3 / 40 都在合法范围内，不该报错");
        ChatDtos.ChatRequest normalized = request.withDefaults();
        assertEquals("doc", normalized.mode());
        assertEquals(3, normalized.docTopK().intValue());
        assertEquals(40, normalized.maxIterations().intValue());
    }

    /**
     * 恢复请求：前端 chat_resume 永远不传 max_iterations，必须校验通过并补成 25。
     */
    @Test
    void resumeOmittedMaxIterationsShouldPassValidationAndFallBackToDefault() {
        // 前端 services/chat.ts 的 chat_resume 只发 session_id / interrupt_id / approved / remember
        ChatDtos.ChatResumeRequest request = new ChatDtos.ChatResumeRequest("session-1", "interrupt-1", true, false, null);

        assertTrue(VALIDATOR.validate(request).isEmpty(),
                "不传 max_iterations 时不应报校验错误，实际：" + messages(VALIDATOR.validate(request)));
        assertEquals(25, request.withDefaults().maxIterations().intValue());

        // 显式 0 依旧报错，与上面的 chat/stream 规则保持一致
        ChatDtos.ChatResumeRequest zero = new ChatDtos.ChatResumeRequest("session-1", "interrupt-1", true, false, 0);
        assertTrue(messages(VALIDATOR.validate(zero)).contains("max_iterations 最小为 1"));
    }
}
