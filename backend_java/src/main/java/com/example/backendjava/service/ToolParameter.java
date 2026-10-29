// 模块说明：工具参数字段的领域声明（agent 工具向模型描述自己接收哪些字段）。
//
// 为什么不用 LangChain4j 的 JsonObjectSchema：service 层的接口只写领域方法、不暴露第三方类型
// （见 doc/java_langchan_doc/04-AI代码生成规范.md §4.2）。工具在这里用项目自己的类型声明字段，
// 由 tools/ToolSchemaMapper 翻译成模型库要的 JSON Schema，只有翻译那一处依赖模型库。
package com.example.backendjava.service;

/**
 * 一个工具参数（字段）的声明。
 *
 * @param name        字段名：必须与工具执行时读取的键名逐字一致（例如 command_args），写错模型就会被判为「没传」
 * @param kind        字段类型：决定 JSON Schema 里是 string、array(string) 还是 integer
 * @param description 给模型看的说明：写清含义、取值范围与示例，模型就是照这句话填值的
 * @param required    是否必填：true 表示漏传即调用失败；false 表示工具有默认值
 */
public record ToolParameter(String name, Kind kind, String description, boolean required) {

    /**
     * 参数字段类型。
     *
     * <p>只列工具真正用得到的三种：本项目的工具没有「对象嵌套参数」，
     * 少一种类型就少一条模型传错形状的路径。</p>
     */
    public enum Kind {
        /** 单值字符串：可执行文件名、绝对路径、一句话目的等。 */
        STRING,
        /** 字符串数组：一个元素一个参数，例如命令参数 ["run", "test:backend"]。 */
        STRING_ARRAY,
        /** 整数：例如超时秒数。 */
        INTEGER
    }
}
