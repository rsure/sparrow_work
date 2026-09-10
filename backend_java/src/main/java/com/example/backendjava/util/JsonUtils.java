package com.example.backendjava.util;


import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.util.List;
import java.util.Map;

/**
 * Jackson 常用工具类（静态方法，线程安全）。
 *
 * <p>设计原则：</p>
 * <ul>
 *   <li>单例 {@link ObjectMapper}：ObjectMapper 是线程安全的，全局一个即可；</li>
 *   <li>所有反序列化失败统一抛 {@link JsonUtilsException}（RuntimeException 子类），
 *       调用方不必每处 try-catch；需要"失败返回默认值"时用 xxxOrDefault 系列；</li>
 *   <li>注册 JavaTimeModule，支持 LocalDateTime / Instant 等；</li>
 *   <li>反序列化忽略未知字段，避免上游加字段就炸。</li>
 * </ul>
 */
public final class JsonUtils {

    /** 全局单例 ObjectMapper。 */
    private static final ObjectMapper MAPPER = new ObjectMapper()
            // 支持 java.time.*
            .registerModule(new JavaTimeModule())
            // 时间序列化为 ISO-8601 字符串，而不是时间戳
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            // 反序列化时忽略 JSON 里多出来的字段
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    /** 工具类禁止实例化。 */
    private JsonUtils() {
    }

    // ------------------------------------------------------------------ //
    // 1. 拿到原始 ObjectMapper（少量需要自定义的场景）
    // ------------------------------------------------------------------ //

    /**
     * 返回全局 ObjectMapper（只读使用，不要修改其配置）。
     */
    public static ObjectMapper mapper() {
        return MAPPER;
    }

    // ------------------------------------------------------------------ //
    // 2. 序列化
    // ------------------------------------------------------------------ //

    /**
     * 对象 → JSON 字符串。
     *
     * @throws JsonUtilsException 序列化失败时
     */
    public static String toJson(Object obj) {
        try {
            return MAPPER.writeValueAsString(obj);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }

    /**
     * 对象 → 美化后的 JSON 字符串（仅日志/调试用）。
     */
    public static String toPrettyJson(Object obj) {
        try {
            return MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(obj);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }

    /**
     * 对象 → JSON 字节（写入 HTTP 响应用）。
     */
    public static byte[] toBytes(Object obj) {
        try {
            return MAPPER.writeValueAsBytes(obj);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }

    // ------------------------------------------------------------------ //
    // 3. 反序列化（强类型）
    // ------------------------------------------------------------------ //

    /**
     * JSON 字符串 → 指定类型。
     *
     * @throws JsonUtilsException 解析失败时
     */
    public static <T> T parse(String json, Class<T> type) {
        try {
            return MAPPER.readValue(json, type);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 解析失败: " + e.getMessage(), e);
        }
    }

    /**
     * JSON 字符串 → 泛型类型（如 List&lt;Foo&gt;、Map&lt;String, Object&gt;）。
     *
     * @throws JsonUtilsException 解析失败时
     */
    public static <T> T parse(String json, TypeReference<T> typeRef) {
        try {
            return MAPPER.readValue(json, typeRef);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 解析失败: " + e.getMessage(), e);
        }
    }

    // ------------------------------------------------------------------ //
    // 4. 反序列化（容错版：失败或 null/blank 返回默认值）
    // ------------------------------------------------------------------ //

    /**
     * 同 {@link #parse(String, Class)}，但失败时返回 {@code defaultValue}，不抛异常。
     */
    public static <T> T parseOrDefault(String json, Class<T> type, T defaultValue) {
        if (json == null || json.isBlank()) {
            return defaultValue;
        }
        try {
            return MAPPER.readValue(json, type);
        } catch (Exception e) {
            return defaultValue;
        }
    }

    /**
     * 同 {@link #parse(String, TypeReference)}，但失败时返回 {@code defaultValue}，不抛异常。
     */
    public static <T> T parseOrDefault(String json, TypeReference<T> typeRef, T defaultValue) {
        if (json == null || json.isBlank()) {
            return defaultValue;
        }
        try {
            return MAPPER.readValue(json, typeRef);
        } catch (Exception e) {
            return defaultValue;
        }
    }

    // ------------------------------------------------------------------ //
    // 5. 常用便捷转换
    // ------------------------------------------------------------------ //

    /**
     * JSON 字符串 → {@code List<Object>}；失败返回空列表。
     */
    public static List<Object> parseList(String json) {
        return parseOrDefault(json, new TypeReference<List<Object>>() {}, List.of());
    }

    /**
     * JSON 字符串 → {@code Map<String, Object>}；失败返回空 Map。
     */
    public static Map<String, Object> parseMap(String json) {
        return parseOrDefault(json, new TypeReference<Map<String, Object>>() {}, Map.of());
    }

    /**
     * 对象 → Map（先序列化再反序列化，适合做 DTO ⇄ Map 转换）。
     */
    public static Map<String, Object> toMap(Object obj) {
        return parseMap(toJson(obj));
    }

    /**
     * Map → 指定类型（适合从 Map 配置构造 DTO）。
     */
    public static <T> T fromMap(Map<String, ?> map, Class<T> type) {
        return parse(toJson(map), type);
    }

    // ------------------------------------------------------------------ //
    // 6. 树模型 / 字段读取
    // ------------------------------------------------------------------ //

    /**
     * JSON 字符串 → 树模型（适合动态结构、只看某几个字段）。
     */
    public static JsonNode readTree(String json) {
        try {
            return MAPPER.readTree(json);
        } catch (Exception e) {
            throw new JsonUtilsException("JSON 解析失败: " + e.getMessage(), e);
        }
    }

    /**
     * 判断字符串是否是合法 JSON（对象/数组/值都算）。
     */
    public static boolean isValidJson(String json) {
        if (json == null || json.isBlank()) {
            return false;
        }
        try {
            MAPPER.readTree(json);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ------------------------------------------------------------------ //
    // 7. 异常
    // ------------------------------------------------------------------ //

    /**
     * JSON 操作异常（RuntimeException，避免调用方到处 throws）。
     */
    public static class JsonUtilsException extends RuntimeException {
        public JsonUtilsException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    public static List<JsonMap> parseMapList(String json) {
        return parseList(json).stream()
                .filter(o -> o instanceof Map)
                .map(JsonMap::of)
                .toList();
    }
}