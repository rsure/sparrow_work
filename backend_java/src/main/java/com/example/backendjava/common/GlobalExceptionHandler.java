// 模块说明：全局异常处理。把 Service / Controller 抛出的异常统一转成 ApiResponse，避免前端收到 HTML 错误页。
package com.example.backendjava.common;

// HTTP 状态码常量：400/500/501 等
import org.springframework.http.HttpStatus;
// 响应实体：把 HTTP 状态码 + JSON 响应体一起返回
import org.springframework.http.ResponseEntity;
// Jakarta 校验异常：@Valid 在方法参数上触发的约束失败
import jakarta.validation.ConstraintViolationException;
// Spring MVC 参数绑定异常：请求体不是合法 JSON 时抛出
import org.springframework.http.converter.HttpMessageNotReadableException;
// Spring MVC 缺少查询参数异常：@RequestParam(required=true) 未传时抛出
import org.springframework.web.bind.MissingServletRequestParameterException;
// Spring MVC 方法参数校验失败：@Valid @RequestBody 校验不通过时抛出
import org.springframework.web.bind.MethodArgumentNotValidException;
// Spring MVC 路径/查询参数类型不匹配：例如把 abc 传给 int 参数
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
// Spring MVC 6.1+ 的静态资源未找到异常：未匹配到 Controller 时抛出
import org.springframework.web.servlet.resource.NoResourceFoundException;
// 全局异常处理注解：作用于所有 @RestController
import org.springframework.web.bind.annotation.ExceptionHandler;
// 全局异常处理注解：声明本类为 ControllerAdvice
import org.springframework.web.bind.annotation.RestControllerAdvice;
// SLF4J 日志门面：记录未预期异常，便于排查
import org.slf4j.Logger;
// SLF4J 日志工厂：创建本类专属 Logger
import org.slf4j.LoggerFactory;

// 标准库：把字段错误拼成一句话
import java.util.stream.Collectors;

/**
 * 全局异常处理器。
 *
 * <p>统一约定：</p>
 * <ul>
 *   <li>业务异常 {@link ApiException}：HTTP 200 + {@code code} 为业务码（与 Python 侧一致）；</li>
 *   <li>参数错误：HTTP 400；</li>
 *   <li>未实现：HTTP 501；</li>
 *   <li>未知异常：HTTP 500，日志保留堆栈，响应只给用户可读的一句话。</li>
 * </ul>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 本类日志器：记录未知异常与校验失败，便于定位问题。 */
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * 处理主动抛出的业务异常。
     *
     * @param exception 业务异常
     * @return HTTP 200 + ApiResponse(code=业务码, message=异常消息)
     */
    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ApiResponse<Void>> handleApiException(ApiException exception) {
        // 业务异常通常是“可预期”的（如资源不存在），只记 warn，不打印完整堆栈
        log.warn("[api] code={} message={}", exception.getCode(), exception.getMessage());

        // 501 表示“接口还没实现”，用真实 HTTP 501 让前端/curl 一眼看出来；
        // 其它业务码（404/422 等）保持 HTTP 200，与 Python 侧的业务码约定一致。
        HttpStatus status = exception.getCode() == HttpStatus.NOT_IMPLEMENTED.value()
                ? HttpStatus.NOT_IMPLEMENTED
                : HttpStatus.OK;
        return ResponseEntity.status(status)
                .body(ApiResponse.error(exception.getCode(), exception.getMessage()));
    }

    /**
     * 处理 @Valid @RequestBody 的字段校验失败。
     *
     * @param exception Spring MVC 包装的校验异常
     * @return HTTP 400 + 拼接后的字段错误说明
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidation(MethodArgumentNotValidException exception) {
        // 把每个字段的错误拼成 "字段: 原因; 字段: 原因"，前端可直接展示
        String detail = exception.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .collect(Collectors.joining("; "));
        // 没有字段错误时给一个兜底文案，避免响应 message 为空
        String message = detail.isBlank() ? "请求参数校验失败" : detail;
        log.warn("[api] 参数校验失败：{}", message);
        return ResponseEntity.badRequest().body(ApiResponse.error(400, message));
    }

    /**
     * 处理方法参数上的约束校验失败（如 @RequestParam @Min）。
     *
     * @param exception Jakarta Validation 异常
     * @return HTTP 400 + 第一条约束错误
     */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolation(ConstraintViolationException exception) {
        // 取第一条错误即可；多条错误对用户来说通常只需要看第一条
        String message = exception.getConstraintViolations().stream()
                .findFirst()
                .map(violation -> violation.getPropertyPath() + ": " + violation.getMessage())
                .orElse("请求参数校验失败");
        log.warn("[api] 参数校验失败：{}", message);
        return ResponseEntity.badRequest().body(ApiResponse.error(400, message));
    }

    /**
     * 处理 JSON 请求体解析失败。
     *
     * @param exception JSON 解析异常
     * @return HTTP 400 + 明确提示
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResponse<Void>> handleUnreadableBody(HttpMessageNotReadableException exception) {
        log.warn("[api] 请求体解析失败：{}", exception.getMessage());
        return ResponseEntity.badRequest().body(ApiResponse.error(400, "请求体不是合法 JSON，或字段类型不匹配"));
    }

    /**
     * 处理缺少必填查询参数。
     *
     * @param exception 缺少参数异常
     * @return HTTP 400 + 缺少的参数名
     */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<ApiResponse<Void>> handleMissingParameter(MissingServletRequestParameterException exception) {
        String message = "缺少必填参数：" + exception.getParameterName();
        log.warn("[api] {}", message);
        return ResponseEntity.badRequest().body(ApiResponse.error(400, message));
    }

    /**
     * 处理路径/查询参数类型不匹配。
     *
     * @param exception 类型转换异常
     * @return HTTP 400 + 参数名与期望类型
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiResponse<Void>> handleTypeMismatch(MethodArgumentTypeMismatchException exception) {
        String message = "参数 " + exception.getName() + " 类型不正确";
        log.warn("[api] {}", message);
        return ResponseEntity.badRequest().body(ApiResponse.error(400, message));
    }

    /**
     * 处理“接口尚未实现”的占位异常。
     *
     * @param exception 未实现异常
     * @return HTTP 501 + 友好提示
     */
    @ExceptionHandler(UnsupportedOperationException.class)
    public ResponseEntity<ApiResponse<Void>> handleUnsupported(UnsupportedOperationException exception) {
        log.warn("[api] 功能尚未实现：{}", exception.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED)
                .body(ApiResponse.error(501, exception.getMessage()));
    }

    /**
     * 处理未匹配到任何 Controller 的请求。
     *
     * <p>Spring Boot 3.2+ 对不存在的路径会抛 NoResourceFoundException；
     * 如果不单独处理，它会被下面的兜底分支当成 500，前端会误以为后端故障。</p>
     *
     * @param exception 静态资源未找到异常
     * @return HTTP 404 + 请求路径
     */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNotFound(NoResourceFoundException exception) {
        String message = "接口不存在：" + exception.getResourcePath();
        log.warn("[api] {}", message);
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(ApiResponse.error(404, message));
    }

    /**
     * 兜底处理所有未预期异常。
     *
     * @param exception 未知异常
     * @return HTTP 500 + 不包含堆栈的通用提示
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleUnknown(Exception exception) {
        // 未知异常必须打印完整堆栈，否则线上无法定位
        log.error("[api] 未处理异常", exception);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.error(500, "服务器内部错误，请查看后端日志"));
    }
}
