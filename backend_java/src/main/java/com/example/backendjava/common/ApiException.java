// 模块说明：业务异常。Controller / Service 主动抛出，由全局异常处理器统一转成 ApiResponse。
package com.example.backendjava.common;

/**
 * 业务异常。
 *
 * <p>约定：{@code code} 与 Python 后端的业务码保持一致，例如 404=资源不存在、
 * 422=参数或文档解析失败、501=接口尚未实现。HTTP 状态码统一由
 * {@link GlobalExceptionHandler} 决定。</p>
 */
public class ApiException extends RuntimeException {

    /** 业务状态码；会原样写入 ApiResponse.code。 */
    private final int code;

    /**
     * 创建业务异常。
     *
     * @param code    业务状态码，如 404/422/501
     * @param message 可直接展示给用户的中文原因
     */
    public ApiException(int code, String message) {
        // 交给 RuntimeException 保存 message，便于日志打印
        super(message);
        this.code = code;
    }

    /**
     * 创建带底层原因的异常，便于排查解析失败、网络错误等。
     *
     * @param code    业务状态码
     * @param message 用户可读的失败原因
     * @param cause   原始异常；会进入日志堆栈，不会返回给前端
     */
    public ApiException(int code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    /** 返回业务状态码；全局异常处理器据此填充 ApiResponse.code。 */
    public int getCode() {
        return code;
    }
}
