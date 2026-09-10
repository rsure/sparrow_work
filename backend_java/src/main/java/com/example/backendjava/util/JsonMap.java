package com.example.backendjava.util;


import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Map 的只读包装，提供 getStr / getInt / getBool / getList 等语法糖。
 * 底层数据来自 Jackson 解析出的 LinkedHashMap，不引入任何 JSON 库依赖。
 */
public final class JsonMap {

    private final Map<?, ?> data;

    public JsonMap(Map<?, ?> data) {
        this.data = data == null ? Map.of() : data;
    }

    /** 从任意对象安全构造：非 Map 时得到空 JsonMap。 */
    public static JsonMap of(Object obj) {
        return obj instanceof Map<?, ?> m ? new JsonMap(m) : new JsonMap(Map.of());
    }

    public String getStr(String key) {
        Object v = data.get(key);
        return v == null ? "" : v.toString().trim();
    }

    public String getStr(String key, String defaultValue) {
        Object v = data.get(key);
        return v == null ? defaultValue : v.toString().trim();
    }

    public Integer getInt(String key) {
        Object v = data.get(key);
        if (v instanceof Number n) return n.intValue();
        try {
            return v == null ? null : Integer.parseInt(v.toString().trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public boolean getBool(String key) {
        Object v = data.get(key);
        return v instanceof Boolean b ? b : Boolean.parseBoolean(String.valueOf(v));
    }

    public List<String> getStrList(String key) {
        Object v = data.get(key);
        if (!(v instanceof List<?> list)) return List.of();
        return list.stream()
                .filter(Objects::nonNull)
                .map(Object::toString)
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .distinct()
                .toList();
    }

    public JsonMap getObj(String key) {
        return of(data.get(key));
    }

    public Map<?, ?> raw() {
        return data;
    }

    public boolean isEmpty() {
        return data.isEmpty();
    }
}
