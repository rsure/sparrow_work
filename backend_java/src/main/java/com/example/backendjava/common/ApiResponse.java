// 模块说明：统一响应外壳。所有 Controller 都返回这个结构，前端只需处理一种 JSON 形状。
package com.example.backendjava.common;

/**
 * 统一响应体，对应 Python 侧 app/schemas/common.py 的 ApiResponse。
 *
 * @param code    业务状态码：0=成功；非 0=业务失败（401/404/422/501 等）
 * @param message 提示文案：成功固定为 ok；失败时是可直接展示给用户的中文原因
 * @param data    业务数据；失败时通常为 null
 * @param <T>     业务数据类型，例如 HealthData、List&lt;Document&gt;
 */
public record ApiResponse<T>(
        // 业务状态码；与 HTTP 状态码解耦，避免前端要同时处理两套错误语义
        int code,
        // 提示文案；直接展示给用户，不要放堆栈或内部路径
        String message,
        // 业务数据；成功时由具体接口填充
        T data
) {

    /**
     * 构造成功响应。
     *
     * @param data 业务数据
     * @param <T>  数据类型
     * @return code=0、message=ok 的响应
     */
    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(0, "ok", data);
    }

    /**
     * 构造无数据的成功响应（用于删除、保存等只需要知道成功与否的接口）。
     *
     * @param <T> 数据类型占位
     * @return code=0、message=ok、data=null 的响应
     */
    public static <T> ApiResponse<T> ok() {
        return new ApiResponse<>(0, "ok", null);
    }

    /**
     * 构造失败响应。
     *
     * @param code    业务状态码，建议与 Python 侧保持一致（404/422/501 等）
     * @param message 可直接展示给用户的失败原因
     * @param <T>     数据类型占位
     * @return code 非 0、data=null 的响应
     */
    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }
}
