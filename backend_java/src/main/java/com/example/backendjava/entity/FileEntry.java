// 模块说明：单个文件的扫描快照（对应 Python 侧 entity/file_Info.py 的 FileInfo）。
package com.example.backendjava.entity;

// 标准库：Map 用于序列化形状
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 单个文件的扫描结果快照（不可变）。
 *
 * @param path        文件绝对路径，全局唯一
 * @param name        文件名（含扩展名、不含目录）
 * @param fileSize    文件字节数
 * @param kind        文件大类：document / image / video / audio / archive / code / other
 * @param isDirectory 是否目录（扫描只产出文件，恒为 false，保留以统一序列化形状）
 * @param modifiedAt  最后修改时间（ISO-8601 字符串）
 */
public record FileEntry(
        String path,
        String name,
        long fileSize,
        String kind,
        boolean isDirectory,
        String modifiedAt
) {

    /**
     * 前端 FileEntry（services/file.ts）需要的 camelCase 形状，供流式/接口响应用。
     *
     * @return camelCase 字典
     */
    public Map<String, Object> toApiMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("path", path);
        map.put("name", name);
        map.put("fileSize", fileSize);
        map.put("kind", kind);
        map.put("isDirectory", isDirectory);
        map.put("modifiedAt", modifiedAt);
        map.put("indexed", false);
        return map;
    }

    /**
     * 落库（task_info.files_json）用的 snake_case 形状。
     *
     * @return snake_case 字典
     */
    public Map<String, Object> toSnakeMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("path", path);
        map.put("name", name);
        map.put("file_size", fileSize);
        map.put("kind", kind);
        map.put("is_directory", isDirectory);
        map.put("modified_at", modifiedAt);
        return map;
    }

    /**
     * {@link #toSnakeMap()} 的逆操作，用于读历史任务时从 files_json 还原文件列表。
     *
     * @param map snake_case 字典
     * @return 还原后的 FileEntry
     */
    public static FileEntry fromMap(Map<String, Object> map) {
        return new FileEntry(
                str(map.get("path")),
                str(map.get("name")),
                number(map.get("file_size")),
                str(map.get("kind")),
                Boolean.TRUE.equals(map.get("is_directory")),
                str(map.get("modified_at"))
        );
    }

    private static String str(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static long number(Object value) {
        return value instanceof Number n ? n.longValue() : 0L;
    }
}
