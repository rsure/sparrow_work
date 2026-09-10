// 模块说明：工具执行结果。统一用 OK/FAIL 前缀，方便模型理解成功与失败。
package com.example.backendjava.dto;

/**
 * 工具执行结果。
 *
 * @param ok      是否成功
 * @param content 结果正文；失败时是可读的失败原因
 */
public record ToolResult(
        // 是否成功
        boolean ok,
        // 结果正文
        String content
) {

    /**
     * 构造成功结果。
     *
     * @param content 结果正文
     * @return ok=true 的结果
     */
    public static ToolResult ok(String content) {
        return new ToolResult(true, "OK: " + content);
    }

    /**
     * 构造失败结果。
     *
     * @param content 失败原因
     * @return ok=false 的结果
     */
    public static ToolResult fail(String content) {
        return new ToolResult(false, "FAIL: " + content);
    }
}
