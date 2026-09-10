// 模块说明：设置体系核心逻辑的离线单元测试。不启动 Spring 容器，只验证「声明 / 校验 / 脱敏」三层，
// 这样每次改声明或改错误文案都能在几百毫秒内拿到反馈，不必等数据库初始化。
package com.example.backendjava.settings;

// 标准库：HashSet 用来发现重复声明
import java.util.HashSet;
// 标准库：List 承载 67 条声明与数组型设置值
import java.util.List;
// 标准库：Map 构造 json 型设置值（脱敏用）
import java.util.Map;
// 标准库：Set 记录已出现过的设置键
import java.util.Set;

// JUnit 5 测试注解：标记测试方法
import org.junit.jupiter.api.Test;
// 静态导入断言：相等 / 真假 / 空值 / 抛异常
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

// 项目内：业务异常，校验失败时统一抛它（code=400）
import com.example.backendjava.common.ApiException;
// 项目内：下发给设置页的 schema DTO
import com.example.backendjava.dto.SettingDtos;
// 项目内：JSON 序列化，用来断言 DTO 能被正常序列化
import com.example.backendjava.util.JsonUtils;

/**
 * 设置核心逻辑单元测试。
 *
 * <p>覆盖四件事：内置声明本身合法且齐全、写入类型校验的文案与 Python 侧一致、
 * 声明的自检能挡住写错的键/候选/区间、导出脱敏只遮敏感键。</p>
 */
class SettingsCoreTest {

    /**
     * 内置声明必须齐全（67 条）、键唯一且按键名升序排列，每条都能转成 meta。
     */
    @Test
    void builtinDefinitionsShouldBeCompleteAndSorted() {
        List<SettingDefinition> definitions = BuiltinSettings.definitions();

        assertEquals(67, definitions.size(), "内置设置声明数量应与 Python 侧（排除 workspaces.*）一致");

        Set<String> seenKeys = new HashSet<>();
        String previousKey = null;
        for (SettingDefinition definition : definitions) {
            // 重复键会让「按 key 查声明」出现二义性，必须当场发现
            assertTrue(seenKeys.add(definition.key()), "设置键重复：" + definition.key());
            if (previousKey != null) {
                assertTrue(previousKey.compareTo(definition.key()) < 0,
                        "声明未按字母序排列：" + previousKey + " -> " + definition.key());
            }
            previousKey = definition.key();

            // 设置页要显示分组与说明，缺失会让界面出现空白项
            assertNotNull(definition.category());
            assertNotNull(definition.label());
            assertNotNull(definition.description());

            // meta 是设置页唯一的 schema 来源，必须能正常序列化下发
            SettingDtos.SettingMeta meta = definition.toMeta();
            assertEquals(definition.key(), meta.key());
            assertEquals(definition.kind().value(), meta.type());
            assertTrue(JsonUtils.toJson(meta).contains(definition.key()));
        }
    }

    /**
     * 类型校验：错误文案与 Python 侧逐字一致，正常值按约定规范化。
     */
    @Test
    void coerceShouldFollowPythonMessages() {
        // 布尔型只认真布尔：字符串 "true" 也拒绝，避免各语言真值表打架
        ApiException boolError = assertThrows(ApiException.class,
                () -> SettingKind.BOOL.coerce("true", "agent.steering_enabled"));
        assertEquals(400, boolError.getCode());
        assertEquals("设置 agent.steering_enabled 要求布尔值（true/false），收到 str",
                boolError.getMessage());

        // 整数型接受整数、整值小数与可解析字符串
        assertEquals(42, SettingKind.INT.coerce("42", "agent.max_iterations"));
        assertEquals(42, SettingKind.INT.coerce(42.0, "agent.max_iterations"));

        // 布尔值不能被悄悄存成 1
        ApiException intBoolError = assertThrows(ApiException.class,
                () -> SettingKind.INT.coerce(true, "agent.max_iterations"));
        assertEquals("设置 agent.max_iterations 要求整数，收到布尔值", intBoolError.getMessage());

        // 带小数的值不能静默截断
        ApiException intFloatError = assertThrows(ApiException.class,
                () -> SettingKind.INT.coerce(1.5, "agent.max_iterations"));
        assertEquals("设置 agent.max_iterations 要求整数，收到 float", intFloatError.getMessage());

        // 浮点型接受整数，统一规范成 double
        assertEquals(0.5, ((Number) SettingKind.FLOAT.coerce(0.5, "context.compress_threshold")).doubleValue());
        assertEquals(1.0, ((Number) SettingKind.FLOAT.coerce(1, "context.compress_threshold")).doubleValue());

        // 字符串型不做数字转换：版本号 "14" 存成 14 会导致前后端类型漂移
        assertEquals("deepseek-flash", SettingKind.STRING.coerce("deepseek-flash", "llm.model"));
        ApiException stringError = assertThrows(ApiException.class,
                () -> SettingKind.STRING.coerce(1, "llm.model"));
        assertEquals("设置 llm.model 要求字符串，收到 int", stringError.getMessage());

        // select 在 coerce 阶段只管「是不是字符串」，候选值由声明校验
        ApiException selectError = assertThrows(ApiException.class,
                () -> SettingKind.SELECT.coerce(1, "llm.provider"));
        assertEquals("设置 llm.provider 要求字符串（从固定候选中选一个），收到 int",
                selectError.getMessage());
    }

    /**
     * 声明自检：键格式、select 候选、标签数量、区间上下界写反时都应该在启动阶段就报错。
     */
    @Test
    void definitionShouldRejectBadDeclarations() {
        // 键必须是「组.键」两段式
        IllegalArgumentException keyError = assertThrows(IllegalArgumentException.class,
                () -> SettingDefinition.of("nodot", SettingKind.INT, 1).build());
        assertTrue(keyError.getMessage().contains("必须形如「组.键」"));

        // select 必须给候选值
        IllegalArgumentException optionsError = assertThrows(IllegalArgumentException.class,
                () -> SettingDefinition.of("a.b", SettingKind.SELECT, "x").build());
        assertTrue(optionsError.getMessage().contains("没给 options 候选值"));

        // 候选标签数量必须与候选值一致
        IllegalArgumentException labelError = assertThrows(IllegalArgumentException.class,
                () -> SettingDefinition.of("a.b", SettingKind.SELECT, "x")
                        .options("x", "y").optionLabels("X").build());
        assertTrue(labelError.getMessage().contains("option_labels"));

        // 上下界写反
        IllegalArgumentException rangeError = assertThrows(IllegalArgumentException.class,
                () -> SettingDefinition.of("a.b", SettingKind.INT, 1).min(10).max(1).build());
        assertTrue(rangeError.getMessage().contains("大于 max"));

        // 默认值本身不合法（这里 100 超出 [1,10]）也要在声明阶段暴露
        ApiException defaultError = assertThrows(ApiException.class,
                () -> SettingDefinition.of("a.b", SettingKind.INT, 100).min(1).max(10).build());
        assertEquals("设置 a.b 不能大于 10（收到 100）", defaultError.getMessage());
    }

    /**
     * 写入区间与 select 候选校验：越界/候选外必须给出可照抄改正的中文提示。
     */
    @Test
    void checkRangeShouldEnforceBoundsAndOptions() {
        SettingDefinition bounded = SettingDefinition.of("agent.max_iterations", SettingKind.INT, 25)
                .min(1)
                .max(50)
                .build();

        ApiException lowError = assertThrows(ApiException.class, () -> bounded.coerce(0));
        assertEquals("设置 agent.max_iterations 不能小于 1（收到 0）", lowError.getMessage());

        ApiException highError = assertThrows(ApiException.class, () -> bounded.coerce(51));
        assertEquals("设置 agent.max_iterations 不能大于 50（收到 51）", highError.getMessage());

        // 合法值原样放行
        assertEquals(50, bounded.coerce(50));

        SettingDefinition select = SettingDefinition.of("theme.mode", SettingKind.SELECT, "dark")
                .options("dark", "light", "system")
                .optionLabels("深色", "浅色", "跟随系统")
                .build();

        ApiException optionError = assertThrows(ApiException.class, () -> select.coerce("blue"));
        assertEquals("设置 theme.mode 只能取以下候选值之一：dark、light、system；收到 'blue'",
                optionError.getMessage());
    }

    /**
     * 密钥打码：空值代表「未设置」，不能显示成 ****；短值整体遮住，长值只留头 3 尾 4。
     */
    @Test
    void maskSecretShouldHideMostOfValue() {
        assertNull(SecretStore.maskSecret(null));
        assertNull(SecretStore.maskSecret(""));
        assertEquals("****", SecretStore.maskSecret("short"));
        assertEquals("sk-****cdef", SecretStore.maskSecret("sk-1234567890abcdef"));
    }

    /**
     * 导出脱敏：env/headers 容器整体遮值、敏感键名遮值、普通值原样保留。
     */
    @Test
    void redactorShouldMaskSensitiveKeys() {
        // headers 下面的键名本身未必命中敏感词，所以整个容器一律遮掉值
        Object maskedHeaders = SettingsRedactor.redact(
                Map.of("headers", Map.of("X-Api-Key", "sk-live-1")), "mcp.servers");
        assertTrue(JsonUtils.toJson(maskedHeaders).contains(SettingsRedactor.REDACTED));
        assertFalse(JsonUtils.toJson(maskedHeaders).contains("sk-live-1"));

        // 数组沿用当前键名：整组 token 都应被遮掉
        Object maskedList = SettingsRedactor.redact(List.of("sk-1", "sk-2"), "api_key");
        assertTrue(JsonUtils.toJson(maskedList).contains(SettingsRedactor.REDACTED));

        // 普通设置值不受影响，避免导出文件变成一堆占位符
        assertEquals("deepseek-flash", SettingsRedactor.redact("deepseek-flash", "llm.model"));

        assertTrue(SettingsRedactor.isSensitiveKey("OPENAI_API_KEY"));
        assertTrue(SettingsRedactor.isSensitiveKey("my.token"));
        assertFalse(SettingsRedactor.isSensitiveKey("llm.model"));
    }
}
