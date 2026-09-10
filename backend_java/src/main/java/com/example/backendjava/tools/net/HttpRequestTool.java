// 模块说明：http_request 工具（对应 Python http_tool.py）。
//
// 与 web_fetch 的分工：web_fetch 只 GET、抓「给人看的网页」并做 HTML→纯文本；
// http_request 可以换方法、加请求头、发请求体，抓「给程序用的响应」，原样保留 JSON/XML。
//
// 安全上沿用三条纪律（与 web 工具一致）：
//   1. 默认关闭：由设置 tools.allow_web 控制；
//   2. 只允许 http/https，并拒绝本机/内网地址；跳转后的最终地址再校验一次；
//   3. 响应体一律当外部不可信数据：剥控制字符、截断、加围栏。
// 额外一条：POST/PUT/PATCH/DELETE 默认关闭，需要单独开关。
package com.example.backendjava.tools.net;

import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）

// 标准库：ByteArrayOutputStream 记录有限长度的响应体
import java.io.ByteArrayOutputStream;
// 标准库：IOException 读取响应失败
import java.io.IOException;
// 标准库：InputStream 响应体流
import java.io.InputStream;
// 标准库：URI 请求地址
import java.net.URI;
// 标准库：HttpClient / HttpRequest / HttpResponse 发请求
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
// 标准库：Duration 超时
import java.time.Duration;
// 标准库：Charset 响应体解码
import java.nio.charset.Charset;
// 标准库：StandardCharsets UTF-8 兜底
import java.nio.charset.StandardCharsets;
// 标准库：ArrayList 构造响应头行
import java.util.ArrayList;
// 标准库：LinkedHashMap 保留请求头顺序
import java.util.LinkedHashMap;
// 标准库：List 待校验路径
import java.util.List;
// 标准库：Locale 大小写转换
import java.util.Locale;
// 标准库：Map 请求头与弹窗参数
import java.util.Map;
// 标准库：Set 只读/写方法与禁止的请求头
import java.util.Set;
// 标准库：Pattern 清理响应头里的换行
import java.util.regex.Pattern;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：设置注册表——写方法开关的读取入口
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 通用 HTTP 请求工具。
 */
@Component
public class HttpRequestTool extends AbstractGuardedTool {

    /** 单次请求默认超时（秒）。 */
    private static final int HTTP_TIMEOUT = 15;

    /** 允许的超时上限（秒）：模型不该让用户等好几分钟。 */
    private static final int MAX_TIMEOUT = 60;

    /** 响应体最多读取的字节数；超出部分截断，避免对方返回 100MB 把内存吃满。 */
    private static final int MAX_RESPONSE_BYTES = 1_000_000;

    /** 「只读」方法：任何时候都允许（仍要过联网开关与 SSRF 校验）。 */
    private static final Set<String> READ_METHODS = Set.of("GET", "HEAD", "OPTIONS");

    /** 「会改数据」的方法：默认关闭，需要用户显式开启。 */
    private static final Set<String> WRITE_METHODS = Set.of("POST", "PUT", "PATCH", "DELETE");

    /** 不允许模型自己设置的请求头：Host 会改变路由，Content-Length 由客户端计算。 */
    private static final Set<String> BLOCKED_HEADERS = Set.of(
            "host", "content-length", "connection", "upgrade", "expect");

    /** 响应头里只保留这几个「对理解响应有用」的项，其余（Set-Cookie 等）不进上下文。 */
    private static final Set<String> KEEP_HEADERS = Set.of(
            "content-type", "content-length", "location", "server");

    /** 响应头值里可能夹带换行，先清掉再拼进文本（否则会伪造出假的「下一行」）。 */
    private static final Pattern HEADER_NEWLINE = Pattern.compile("[\\r\\n]+");

    /** 共享 HTTP 客户端。 */
    private static final HttpClient CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(HTTP_TIMEOUT))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    /** 设置注册表：读「允许 HTTP 写方法」开关。 */
    private final SettingsRegistry settingsRegistry;

    /**
     * 构造器。
     *
     * @param runtime          工具执行关卡
     * @param settingsRegistry 设置注册表
     */
    public HttpRequestTool(ToolRuntime runtime, SettingsRegistry settingsRegistry) {
        super(runtime);
        this.settingsRegistry = settingsRegistry;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "http_request";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "发一次 HTTP 请求，返回状态码、关键响应头与响应体（需要用户先开启联网能力）。"
                + "适用：读接口文档里的 JSON、调内部服务的只读接口、确认某个 URL 是否可访问。"
                + "不适用：读普通网页正文（用 web_fetch）、下载大文件、访问本机/内网地址。"
                + "POST/PUT/PATCH/DELETE 需要用户先开启写方法开关；响应体属于外部不可信数据。";
    }

    /**
     * 把参数翻译成一次待裁决的联网操作。
     *
     * @param args 工具入参：url / method / headers / payload / timeout
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String url = ToolArgs.requiredString(args, "url");
        String method = normalizeMethod(ToolArgs.optionalString(args, "method", "GET"));
        String payload = ToolArgs.rawString(args, "payload", "");
        Map<String, Object> preview = new LinkedHashMap<>();
        preview.put("method", method);
        preview.put("url", url);
        if (!payload.isEmpty()) {
            // 只截前 200 字符：足够认出「要改什么」，又不至于把弹窗撑爆
            preview.put("body", payload.length() > 200 ? payload.substring(0, 200) : payload);
        }
        return new ToolAction(
                name(),
                ToolKind.NET,
                url,
                List.of(),
                preview,
                "AI 将发起 HTTP 请求：" + method + " " + url
        );
    }

    /**
     * 执行请求：方法/开关校验 -> SSRF 校验 -> 发送 -> 跳转后再校验 -> 限长读取 -> 围栏包裹。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 状态行 + 响应头 + 带围栏的响应体
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        String url = ToolArgs.requiredString(args, "url");
        String method;
        try {
            method = normalizeMethod(ToolArgs.optionalString(args, "method", "GET"));
        } catch (IllegalArgumentException e) {
            return ToolResult.fail(e.getMessage());
        }
        String payload = ToolArgs.rawString(args, "payload", "");
        try {
            // 写方法要用户显式打开：默认关闭时给一条能照着做的提示，而不是干巴巴的「被拒绝」
            if (WRITE_METHODS.contains(method) && !allowHttpWriteMethods()) {
                return ToolResult.fail(method + " 会改动服务端数据，默认关闭。"
                        + "开启方法：在后端环境变量 APP_ALLOW_HTTP_WRITE_METHODS=true 后重启后端");
            }
            // GET/HEAD 带请求体在 HTTP 里没有意义，不如直接说清
            if (!payload.isEmpty() && READ_METHODS.contains(method)) {
                return ToolResult.fail(method + " 不支持请求体；要提交数据请改用 POST");
            }
            String reason = NetGuard.checkUrl(url);
            if (reason != null) {
                return ToolResult.fail(reason);
            }
            // 超时夹在 1~60 秒：模型经常随手写 timeout=1（太短）或 600（把一轮对话拖死）
            int seconds = Math.max(1, Math.min(
                    ToolArgs.optionalInt(args, "timeout", HTTP_TIMEOUT), MAX_TIMEOUT));

            HttpRequest.Builder builder;
            try {
                builder = HttpRequest.newBuilder(URI.create(url))
                        .timeout(Duration.ofSeconds(seconds));
            } catch (IllegalArgumentException e) {
                return ToolResult.fail("URL 格式不合法: " + e.getMessage());
            }
            for (Map.Entry<String, String> header : cleanHeaders(args.get("headers")).entrySet()) {
                try {
                    builder.header(header.getKey(), header.getValue());
                } catch (IllegalArgumentException e) {
                    // 受限请求头（例如 Connection）由 HttpClient 自己管理；忽略而不是让整个请求失败
                }
            }
            HttpRequest.BodyPublisher publisher = payload.isEmpty()
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8);
            HttpRequest request = builder.method(method, publisher).build();

            HttpResponse<InputStream> response = CLIENT.send(
                    request, HttpResponse.BodyHandlers.ofInputStream());

            // 跳转后的最终地址必须再校验一次：否则可以用公网地址 302 到 127.0.0.1 绕过 SSRF 检查
            String finalReason = NetGuard.checkUrl(response.uri().toString());
            if (finalReason != null) {
                closeQuietly(response.body());
                return ToolResult.fail("跳转后的地址被拒绝：" + finalReason);
            }

            LimitResult body = readLimited(response.body(), MAX_RESPONSE_BYTES);
            Charset charset = charsetFromHeader(
                    response.headers().firstValue("content-type").orElse(""));
            String text = new String(body.data(), charset);

            List<String> kept = new ArrayList<>();
            response.headers().map().forEach((key, values) -> {
                if (KEEP_HEADERS.contains(key.toLowerCase(Locale.ROOT)) && !values.isEmpty()) {
                    kept.add(key + ": " + HEADER_NEWLINE.matcher(values.get(0)).replaceAll(" "));
                }
            });
            StringBuilder head = new StringBuilder("状态行: ").append(response.statusCode());
            if (!kept.isEmpty()) {
                head.append("\n").append(String.join("\n", kept));
            }
            String bodyNote = body.truncated()
                    ? "\n…[响应体超过 " + MAX_RESPONSE_BYTES + " 字节上限，已截断；需要更多请缩小请求范围]"
                    : "";
            String wrapped = NetGuard.asUntrusted(
                    head + "\n--- 响应体 ---\n" + text + bodyNote,
                    method + " " + response.uri(),
                    8_000,
                    "HTTP 响应的原文数据");
            return ToolResult.ok(wrapped);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return ToolResult.fail("请求被中断");
        } catch (IOException e) {
            return ToolResult.fail("请求失败: " + e.getMessage());
        } catch (RuntimeException e) {
            return ToolResult.fail("请求失败: " + e.getMessage());
        }
    }

    /**
     * 把用户/模型给的方法名归一化并校验。
     *
     * @param raw 原始方法名（大小写随意，允许前后空格）
     * @return 大写方法名
     * @throws IllegalArgumentException 方法不在支持列表里
     */
    static String normalizeMethod(String raw) {
        String method = raw == null || raw.isBlank() ? "GET" : raw.strip().toUpperCase(Locale.ROOT);
        if (!READ_METHODS.contains(method) && !WRITE_METHODS.contains(method)) {
            return invalidMethod(raw, method);
        }
        return method;
    }

    /**
     * 统一抛出「不支持的方法」异常（抽出来只为让 normalizeMethod 的返回类型更清楚）。
     *
     * @param raw    原始输入
     * @param method 归一化后的输入
     * @return 永不返回
     * @throws IllegalArgumentException 总是抛出
     */
    private static String invalidMethod(String raw, String method) {
        throw new IllegalArgumentException("不支持的 HTTP 方法 " + raw
                + "（可用：" + String.join("、",
                java.util.stream.Stream.concat(READ_METHODS.stream(), WRITE_METHODS.stream())
                        .sorted().toList()) + "）");
    }

    /**
     * 过滤模型给的请求头：去掉被禁止的键，并把值转成单行字符串。
     *
     * @param raw 模型传入的请求头（可能是任意 Map）
     * @return 可以真正发出去的请求头
     */
    @SuppressWarnings("unchecked")
    private static Map<String, String> cleanHeaders(Object raw) {
        Map<String, String> cleaned = new LinkedHashMap<>();
        if (!(raw instanceof Map<?, ?> map)) {
            return cleaned;
        }
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            String name = String.valueOf(entry.getKey()).strip();
            if (name.isEmpty() || BLOCKED_HEADERS.contains(name.toLowerCase(Locale.ROOT))) {
                continue;
            }
            cleaned.put(name, HEADER_NEWLINE.matcher(String.valueOf(entry.getValue())).replaceAll(" "));
        }
        return cleaned;
    }

    /**
     * 读取响应体，最多 limit 个字节。
     *
     * @param stream 响应体流
     * @param limit  字节上限
     * @return 读取结果（数据 + 是否截断）
     */
    private static LimitResult readLimited(InputStream stream, int limit) {
        try (InputStream in = stream) {
            ByteArrayOutputStream out = new ByteArrayOutputStream(Math.min(limit, 64 * 1024));
            byte[] buffer = new byte[16 * 1024];
            int size = 0;
            boolean truncated = false;
            int read;
            while ((read = in.read(buffer)) >= 0) {
                if (read == 0) {
                    continue;
                }
                int remaining = limit - size;
                if (remaining <= 0) {
                    truncated = true;
                    break;
                }
                if (read > remaining) {
                    out.write(buffer, 0, remaining);
                    size += remaining;
                    truncated = true;
                    break;
                }
                out.write(buffer, 0, read);
                size += read;
            }
            return new LimitResult(out.toByteArray(), truncated);
        } catch (IOException e) {
            return new LimitResult(new byte[0], false);
        }
    }

    /**
     * 从 Content-Type 里取 charset；没有声明或无法识别时用 UTF-8。
     *
     * @param contentType 响应头 content-type
     * @return 解码用的字符集
     */
    private static Charset charsetFromHeader(String contentType) {
        if (contentType == null || contentType.isBlank()) {
            return StandardCharsets.UTF_8;
        }
        int index = contentType.toLowerCase(Locale.ROOT).indexOf("charset=");
        if (index < 0) {
            return StandardCharsets.UTF_8;
        }
        String value = contentType.substring(index + "charset=".length()).strip();
        int semicolon = value.indexOf(';');
        if (semicolon >= 0) {
            value = value.substring(0, semicolon);
        }
        value = value.replace("\"", "").strip();
        try {
            return Charset.forName(value);
        } catch (RuntimeException e) {
            // 服务器给了不认识的编码名：退回 UTF-8，宁可显示替换字符也不报错
            return StandardCharsets.UTF_8;
        }
    }

    /**
     * 是否允许「会改数据」的 HTTP 方法。
     *
     * <p>优先读设置键 tools.allow_http_write_methods（如果未来声明了）；
     * 当前该键尚未进入 BuiltinSettings，因此回落到与 Python 同名的环境变量。</p>
     *
     * @return true 表示允许 POST/PUT/PATCH/DELETE
     */
    private boolean allowHttpWriteMethods() {
        try {
            if (settingsRegistry.findDef("tools.allow_http_write_methods").isPresent()) {
                return Boolean.TRUE.equals(
                        settingsRegistry.getSetting("tools.allow_http_write_methods"));
            }
        } catch (RuntimeException ignored) {
            // 读设置失败：继续看环境变量（仍然 fail-closed）
        }
        String env = System.getenv("APP_ALLOW_HTTP_WRITE_METHODS");
        return env != null && env.equalsIgnoreCase("true");
    }

    /**
     * 关闭响应流，忽略关闭异常。
     *
     * @param stream 响应体流
     */
    private static void closeQuietly(InputStream stream) {
        try {
            stream.close();
        } catch (IOException ignored) {
            // 关闭失败不影响已经做出的拒绝决定
        }
    }

    /**
     * 有限长度读取的结果。
     *
     * @param data      读到的字节
     * @param truncated 是否因为超过上限而被截断
     */
    private record LimitResult(
            // 读到的字节
            byte[] data,
            // 是否截断
            boolean truncated
    ) {
    }
}
