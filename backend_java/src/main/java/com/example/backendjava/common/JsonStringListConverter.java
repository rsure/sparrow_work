// 模块说明：把 List<String> 以 JSON 数组形式存进单个 TEXT 列（工作区根目录列表用）。
package com.example.backendjava.common;

// 标准库：List 是转换的两端类型之一
import java.util.List;
// 标准库：ArrayList 保证取出的是可变列表，避免调用方 add 时炸掉
import java.util.ArrayList;
// 标准库：Arrays 用于兼容旧数据的逗号分隔解析
import java.util.Arrays;
// 第三方（JPA）：AttributeConverter 声明「实体属性 ⇄ 数据库列」的转换器
import jakarta.persistence.AttributeConverter;
// 第三方（JPA）：@Converter 注册为可被 @Convert 引用的转换器
import jakarta.persistence.Converter;
// 第三方（Jackson）：TypeReference 保留 List<String> 的泛型信息
import com.fasterxml.jackson.core.type.TypeReference;
// 项目内：JSON 工具（序列化/反序列化/失败兜底）
import com.example.backendjava.util.JsonUtils;

/**
 * List&lt;String&gt; ⇄ JSON 数组文本 的 JPA 转换器。
 *
 * <p>为什么不用逗号分隔：工作区路径里完全可能出现逗号（例如
 * {@code D:\work\a,b}），用逗号当分隔符会把一个路径拆成两个，属于会静默损坏
 * 用户数据的问题。JSON 数组能原样保存任意路径。</p>
 */
@Converter
public class JsonStringListConverter implements AttributeConverter<List<String>, String> {

    /**
     * 实体 → 数据库：序列化成 JSON 数组文本。
     *
     * @param attribute 工作区根目录列表；null 视为空列表
     * @return JSON 数组文本，永不为 null（列上有 NOT NULL 约束）
     */
    @Override
    public String convertToDatabaseColumn(List<String> attribute) {
        if (attribute == null) {
            return "[]";
        }
        return JsonUtils.toJson(attribute);
    }

    /**
     * 数据库 → 实体：解析 JSON 数组；解析失败时回退按逗号切分，兼容升级前的旧数据。
     *
     * @param dbData 列里存的文本
     * @return 可变列表，永不为 null
     */
    @Override
    public List<String> convertToEntityAttribute(String dbData) {
        if (dbData == null || dbData.isBlank()) {
            return new ArrayList<>();
        }
        try {
            List<String> parsed = JsonUtils.parse(dbData, new TypeReference<List<String>>() {
            });
            return parsed == null ? new ArrayList<>() : new ArrayList<>(parsed);
        } catch (RuntimeException e) {
            // 旧版本用逗号拼接，这里兜底解析一次，避免升级后工作区直接变空
            return new ArrayList<>(Arrays.asList(dbData.split(",")));
        }
    }
}
