// 模块说明：设置值脱敏——导出配置时把可能含密钥的字段换成占位符，避免「一键导出」变成泄密。
package com.example.backendjava.settings;

// 标准库：List 处理数组型设置值
import java.util.List;
// 标准库：Map 处理对象型设置值
import java.util.Map;
// 标准库：ArrayList/LinkedHashMap 保持原有顺序地重建容器
import java.util.ArrayList;
import java.util.LinkedHashMap;
// 标准库：正则 判断键名是否像「密钥」
import java.util.regex.Pattern;

/**
 * 按「键名像不像敏感字段」给设置值脱敏。
 *
 * <p>灵感来自诊断导出：即使当前设置项的声明里没有标 secret，用户也可能在
 * json 类型设置里塞了 token（例如 MCP 的 headers）。只要键名命中敏感词，
 * 就把值换掉，宁可多遮也不漏遮。</p>
 */
public final class SettingsRedactor {

    /** 脱敏占位符：与 Python 侧保持一致，便于两边导出文件互相导回。 */
    public static final String REDACTED = "***REDACTED***";

    /**
     * 敏感键名正则：apiKey / access_key / token / secret / password / credential /
     * authorization / bearer 等常见写法都覆盖。
     */
    private static final Pattern SECRET_KEY_PATTERN =
            Pattern.compile("(?i)(api[_-]?key|access[_-]?key|token|secret|password|passwd|credential|authorization|bearer)");

    /** 这些键下面挂的是「一组键值对」，整体视为敏感容器。 */
    private static final List<String> CONTAINER_KEYS = List.of("env", "headers");

    /** 工具类禁止实例化。 */
    private SettingsRedactor() {
    }

    /**
     * 递归脱敏一个设置值。
     *
     * @param value 原始值（来自 JSON：Map/List/String/数字/布尔/null）
     * @param key   当前值所属的键名，用于判断是否敏感
     * @return 脱敏后的值；不含敏感内容时原样返回
     */
    public static Object redact(Object value, String key) {
        // env / headers 的值通常是 {"OPENAI_API_KEY": "sk-..."}，
        // 键名本身未必命中敏感词，所以整个容器一律遮掉值、只留键名
        if (value instanceof Map<?, ?> map && key != null && CONTAINER_KEYS.contains(key)) {
            Map<String, Object> masked = new LinkedHashMap<>();
            for (Object subKey : map.keySet()) {
                masked.put(String.valueOf(subKey), REDACTED);
            }
            return masked;
        }
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                String subKey = String.valueOf(entry.getKey());
                result.put(subKey, redact(entry.getValue(), subKey));
            }
            return result;
        }
        if (value instanceof List<?> list) {
            // 数组沿用当前键名：["sk-1","sk-2"] 这类列表整体属于同一个敏感字段
            List<Object> result = new ArrayList<>(list.size());
            for (Object item : list) {
                result.add(redact(item, key));
            }
            return result;
        }
        if (value instanceof String text && key != null && SECRET_KEY_PATTERN.matcher(key).find()) {
            return REDACTED;
        }
        return value;
    }

    /**
     * 判断一个键名是否「像密钥」。
     *
     * @param key 键名；null 视为不敏感
     * @return true 表示命中敏感词
     */
    public static boolean isSensitiveKey(String key) {
        return key != null && SECRET_KEY_PATTERN.matcher(key).find();
    }
}
