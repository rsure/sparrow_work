// 模块说明：把工具的参数声明（ToolParameter 列表）翻译成 LangChain4j 的 JsonObjectSchema。
//
// 为什么要单独一个类：service 层接口不依赖模型库（见 04-AI代码生成规范 §4.2），
// 而 ToolSpecification 又必须拿到模型库的 schema。全项目只有这里做类型转换，
// 主对话（ChatServiceImpl）和子 Agent（SimpleSubAgentRunner）共用同一份翻译逻辑，
// 就不会出现「两处各拼一份 schema、慢慢长歪」的情况。
package com.example.backendjava.tools;

// 标准库：ArrayList 收集必填字段名
import java.util.ArrayList;
// 标准库：List 工具声明的参数字段列表
import java.util.List;
// 项目内：参数字段的领域声明（字段名 / 类型 / 说明 / 是否必填）
import com.example.backendjava.service.ToolParameter;
// 第三方（LangChain4j）：对象型 JSON Schema，ToolSpecification.parameters() 需要的类型
import dev.langchain4j.model.chat.request.json.JsonObjectSchema;
// 第三方（LangChain4j）：数组型 schema，对应 ToolParameter.Kind.STRING_ARRAY
import dev.langchain4j.model.chat.request.json.JsonArraySchema;
// 第三方（LangChain4j）：字符串 schema，对应 Kind.STRING 与数组成员
import dev.langchain4j.model.chat.request.json.JsonStringSchema;
// 第三方（LangChain4j）：整数 schema，对应 Kind.INTEGER
import dev.langchain4j.model.chat.request.json.JsonIntegerSchema;
// 第三方（LangChain4j）：schema 元素的公共父类型，拼 properties 时用它接收三种具体 schema
import dev.langchain4j.model.chat.request.json.JsonSchemaElement;

/**
 * 参数声明 → JSON Schema 的翻译器。
 */
public final class ToolSchemaMapper {

    /**
     * 工具类不需要实例：构造器私有，避免被误 new。
     */
    private ToolSchemaMapper() {
    }

    /**
     * 把工具声明的参数字段翻译成模型库的对象型 schema。
     *
     * <p>声明为空时返回「开放对象」（{@code additionalProperties: true}）：这是老工具的历史行为，
     * 它们的说明文字里已经写了字段名，模型照着填也能用。一旦工具声明了字段，就只描述这些字段，
     * 模型不会再自己编名字。</p>
     *
     * @param parameters 工具声明的参数字段，允许为空（表示不声明）
     * @return 可直接交给 ToolSpecification.parameters() 的 schema
     */
    public static JsonObjectSchema toJsonSchema(List<ToolParameter> parameters) {
        // 没声明字段 → 保持开放对象：任何字段都放行，不做校验
        if (parameters == null || parameters.isEmpty()) {
            return JsonObjectSchema.builder()
                    .additionalProperties(true)
                    .build();
        }
        JsonObjectSchema.Builder builder = JsonObjectSchema.builder();
        // 必填字段名先收集再一次性设置：builder.required(...) 是整体赋值，不是累加
        List<String> requiredNames = new ArrayList<>();
        for (ToolParameter parameter : parameters) {
            builder.addProperty(parameter.name(), toSchemaElement(parameter));
            if (parameter.required()) {
                requiredNames.add(parameter.name());
            }
        }
        if (!requiredNames.isEmpty()) {
            builder.required(requiredNames);
        }
        return builder.build();
    }

    /**
     * 把单个字段声明翻译成对应的 JSON Schema 元素。
     *
     * @param parameter 字段声明
     * @return 字符串 / 字符串数组 / 整数三种 schema 之一
     * @throws IllegalArgumentException 出现未覆盖的字段类型（说明 Kind 新增了值但这里没跟上）
     */
    private static JsonSchemaElement toSchemaElement(ToolParameter parameter) {
        return switch (parameter.kind()) {
            case STRING -> JsonStringSchema.builder()
                    .description(parameter.description())
                    .build();
            // 数组元素统一是字符串：命令行参数没有别的形状，模型也不会给它嵌套对象
            case STRING_ARRAY -> JsonArraySchema.builder()
                    .description(parameter.description())
                    .items(JsonStringSchema.builder().build())
                    .build();
            case INTEGER -> JsonIntegerSchema.builder()
                    .description(parameter.description())
                    .build();
        };
    }
}
