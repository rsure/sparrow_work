// 模块说明：工具入参读取小工具。AgentTool 统一收 Map<String,Object>，这里集中做类型校验。
package com.example.backendjava.tools;

// 标准库（集合组）：ArrayList/LinkedHashMap 构造结果，List/Map 表示工具入参形状
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工具参数读取工具。
 *
 * <p>所有方法在参数缺失/类型不对时抛 {@link IllegalArgumentException}，消息直接回给模型，
 * 因此文案要写清「哪个参数、期望什么、实际收到什么」。</p>
 */
public final class ToolArgs {

    /** 工具类禁止实例化。 */
    private ToolArgs() {
    }

    /**
     * 读取必填字符串参数。
     *
     * @param args 工具入参
     * @param key  参数名
     * @return 去首尾空格后的字符串
     * @throws IllegalArgumentException 参数缺失或为空
     */
    public static String requiredString(Map<String, Object> args, String key) {
        String value = optionalString(args, key, "");
        if (value.isBlank()) {
            throw new IllegalArgumentException("参数 " + key + " 不能为空");
        }
        return value;
    }

    /**
     * 读取可选字符串参数。
     *
     * @param args         工具入参
     * @param key          参数名
     * @param defaultValue 缺失时的默认值
     * @return 字符串值
     */
    public static String optionalString(Map<String, Object> args, String key, String defaultValue) {
        Object value = args == null ? null : args.get(key);
        if (value == null) {
            return defaultValue;
        }
        return String.valueOf(value).strip();
    }

    /**
     * 读取可选字符串参数，但**保留原样**（不 strip）。
     *
     * <p>写文件、替换文本这类参数的首尾空白与换行是内容的一部分，
     * 一旦 strip 就会把用户/模型的原文改掉。</p>
     *
     * @param args         工具入参
     * @param key          参数名
     * @param defaultValue 缺失时的默认值
     * @return 原样字符串
     */
    public static String rawString(Map<String, Object> args, String key, String defaultValue) {
        Object value = args == null ? null : args.get(key);
        return value == null ? defaultValue : String.valueOf(value);
    }

    /**
     * 读取可选整数参数；字符串数字也会被解析。
     *
     * @param args         工具入参
     * @param key          参数名
     * @param defaultValue 缺失或无法解析时的默认值
     * @return 整数值
     */
    public static int optionalInt(Map<String, Object> args, String key, int defaultValue) {
        Object value = args == null ? null : args.get(key);
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value).strip());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("参数 " + key + " 应为整数，收到 " + value);
        }
    }

    /**
     * 读取可选布尔参数；字符串 "true"/"false" 也会被识别。
     *
     * @param args         工具入参
     * @param key          参数名
     * @param defaultValue 缺失时的默认值
     * @return 布尔值
     */
    public static boolean optionalBool(Map<String, Object> args, String key, boolean defaultValue) {
        Object value = args == null ? null : args.get(key);
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof Boolean bool) {
            return bool;
        }
        String text = String.valueOf(value).strip().toLowerCase(java.util.Locale.ROOT);
        if ("true".equals(text)) {
            return true;
        }
        if ("false".equals(text)) {
            return false;
        }
        throw new IllegalArgumentException("参数 " + key + " 应为布尔值，收到 " + value);
    }

    /**
     * 读取字符串数组参数（例如 run_command 的 command_args）。
     *
     * @param args 工具入参
     * @param key  参数名
     * @return 字符串列表；缺失时为空列表
     */
    public static List<String> stringList(Map<String, Object> args, String key) {
        Object value = args == null ? null : args.get(key);
        if (value == null) {
            return List.of();
        }
        if (!(value instanceof List<?> list)) {
            throw new IllegalArgumentException("参数 " + key + " 应为数组，收到 " + value);
        }
        List<String> result = new ArrayList<>(list.size());
        for (Object item : list) {
            result.add(String.valueOf(item));
        }
        return result;
    }

    /**
     * 读取对象数组参数（例如 file_ops 的 items）。
     *
     * @param args 工具入参
     * @param key  参数名
     * @return 每个元素都是 Map 的列表；缺失时为空列表
     */
    public static List<Map<String, Object>> mapList(Map<String, Object> args, String key) {
        Object value = args == null ? null : args.get(key);
        if (value == null) {
            return List.of();
        }
        if (!(value instanceof List<?> list)) {
            throw new IllegalArgumentException("参数 " + key + " 应为数组，收到 " + value);
        }
        List<Map<String, Object>> result = new ArrayList<>(list.size());
        for (Object item : list) {
            if (!(item instanceof Map<?, ?> map)) {
                throw new IllegalArgumentException("参数 " + key + " 的每一项都应为对象，收到 " + item);
            }
            Map<String, Object> normalized = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                normalized.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            result.add(normalized);
        }
        return result;
    }
}
