// 模块说明：MCP 客户端管理实现（对应 Python 侧 app/mcp/client.py + app/mcp/config.py）。
//
// 设计取舍与 Python 侧一致：
//   1. 只做「工具发现」，不保持长连接：每次发现建一个 client，列完工具立即关闭；
//   2. 单个 server 失败只影响它自己，其余 server 与内置工具照常工作；
//   3. 配置指纹变化（或手动 reload）时才重新连接。
package com.example.backendjava.service.impl;

// LangChain4j 工具描述：MCP server 声明的每个工具
import dev.langchain4j.agent.tool.ToolSpecification;
// LangChain4j MCP 客户端：通过传输层连接外部 server
import dev.langchain4j.mcp.client.DefaultMcpClient;
// LangChain4j MCP 客户端接口：listTools / close
import dev.langchain4j.mcp.client.McpClient;
// LangChain4j MCP 传输层接口：stdio / http / websocket 的公共父类型
import dev.langchain4j.mcp.client.transport.McpTransport;
// LangChain4j stdio 传输：启动子进程并通过标准输入输出通信
import dev.langchain4j.mcp.client.transport.stdio.StdioMcpTransport;
// LangChain4j Streamable HTTP 传输：当前推荐的远程 MCP 协议
import dev.langchain4j.mcp.client.transport.http.StreamableHttpMcpTransport;
// LangChain4j WebSocket 传输：兼容旧式远程 MCP server
import dev.langchain4j.mcp.client.transport.websocket.WebSocketMcpTransport;

// 第三方（Spring）：声明为本服务的 Bean 实现
import org.springframework.stereotype.Service;
// SLF4J 日志门面：记录连接失败原因
import org.slf4j.Logger;
// SLF4J 日志工厂：创建本类专属 Logger
import org.slf4j.LoggerFactory;

// 标准库：Duration 表示连接/调用超时
import java.time.Duration;
// 标准库：ArrayList 收集命令与工具
import java.util.ArrayList;
// 标准库：Comparator 按 server 名排序
import java.util.Comparator;
// 标准库：HashMap 保存 server 状态
import java.util.HashMap;
// 标准库：LinkedHashMap 保持快照字段顺序
import java.util.LinkedHashMap;
// 标准库：List 配置列表与工具清单
import java.util.List;
// 标准库：Locale 小写转换
import java.util.Locale;
// 标准库：Map 动态快照与配置对象
import java.util.Map;
// 标准库：Set 免确认名单与传输方式集合
import java.util.Set;
// 标准库：TreeSet 让免确认名单稳定排序
import java.util.TreeSet;
// 标准库：Pattern 校验 server 名与清洗工具名
import java.util.regex.Pattern;

// 项目内：设置注册表（读取 mcp.* 设置项）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：MCP 业务接口（本类实现它）
import com.example.backendjava.service.McpService;
// 项目内：JSON 工具（生成配置指纹）
import com.example.backendjava.util.JsonUtils;

/**
 * MCP 管理服务实现。
 */
@Service
public class McpServiceImpl implements McpService {

    /** 本类日志器：记录连接失败与配置问题。 */
    private static final Logger log = LoggerFactory.getLogger(McpServiceImpl.class);

    /** server 名允许的字符：它会拼进工具名，太野的字符会破坏工具名规则。 */
    private static final Pattern NAME_PATTERN = Pattern.compile("^[A-Za-z0-9_-]{1,32}$");

    /** LangChain 工具名上限（1~64 字符）。 */
    private static final int MAX_TOOL_NAME = 64;

    /** 受支持的传输方式：与 LangChain4j MCP 模块实际提供的传输一一对应。 */
    private static final Set<String> SUPPORTED_TRANSPORTS =
            Set.of("stdio", "sse", "streamable_http", "websocket");

    /** 单次连接/调用的默认超时（秒）：MCP server 可能要起子进程，给得比普通工具宽。 */
    private static final double DEFAULT_TIMEOUT = 60.0;

    /** 设置注册表：总开关、server 列表与免确认名单的唯一数据来源。 */
    private final SettingsRegistry settingsRegistry;

    /** 保护下面的缓存状态；连接过程本身在锁外进行（可能要几秒，不能阻塞读者）。 */
    private final Object lock = new Object();

    /** server 名 → 发现结果状态。 */
    private Map<String, ServerStatus> statusByServer = new HashMap<>();

    /** 配置级错误（JSON 写错、字段缺失），与 server 级错误分开。 */
    private List<String> configErrors = new ArrayList<>();

    /** 上次加载时的配置指纹；变了就重连。 */
    private String signature = "";

    /** 是否已经尝试过加载（即使 0 个 server 也要记住，避免每次都重扫）。 */
    private boolean loaded = false;

    /**
     * 构造器注入设置注册表。
     *
     * @param settingsRegistry 设置注册表
     */
    public McpServiceImpl(SettingsRegistry settingsRegistry) {
        this.settingsRegistry = settingsRegistry;
    }

    /**
     * 列出各 MCP server 的连接状态与工具清单。
     *
     * @return 形如 {"enabled","servers","errors","tool_count"} 的快照
     */
    @Override
    public Map<String, Object> snapshot() {
        ensureLoaded();
        return snapshotInternal();
    }

    /**
     * 强制重新连接全部 MCP server。
     *
     * @return 重载后的快照
     */
    @Override
    public Map<String, Object> reload() {
        return refresh(true);
    }

    /**
     * 试连一条 server 配置（不保存、不影响现有连接）。
     *
     * @param config 单条配置，结构同设置项 mcp.servers 的元素
     * @return 形如 {"ok","tools","error","duration_ms"} 的结果
     */
    @Override
    public Map<String, Object> test(Map<String, Object> config) {
        if (config == null) {
            // 请求体是 JSON null 时给出明确原因，避免 List.of(null) 抛 NPE
            return testResult(false, List.of(), "配置不能为空", 0);
        }
        ParseResult parsed = parseServers(List.of(config));
        if (!parsed.errors().isEmpty() || parsed.servers().isEmpty()) {
            String message = parsed.errors().isEmpty()
                    ? "配置不合法"
                    : String.join("；", parsed.errors());
            return testResult(false, List.of(), message, 0);
        }

        McpServerConfig server = parsed.servers().get(0);
        long started = System.nanoTime();
        try {
            List<ToolSpecification> tools = discover(server);
            List<Map<String, Object>> items = new ArrayList<>(tools.size());
            for (ToolSpecification tool : tools) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("name", serverToolName(server.name(), tool.name()));
                item.put("description", truncate(tool.description(), 160));
                items.add(item);
            }
            return testResult(true, items, "", elapsedMillis(started));
        } catch (RuntimeException e) {
            return testResult(false, List.of(),
                    e.getClass().getSimpleName() + ": " + e.getMessage(),
                    elapsedMillis(started));
        }
    }

    // ------------------------------------------------------------------ //
    // 一、加载与刷新
    // ------------------------------------------------------------------ //

    /**
     * 确保已加载；配置变了（或从未加载）时重连。
     */
    private void ensureLoaded() {
        SettingsSnapshot settings = readSettings();
        ParseResult parsed = parseServers(settings.serversRaw());
        String current = signatureOf(parsed.servers(), parsePatterns(settings.autoApproveRaw()),
                settings.enabled());
        synchronized (lock) {
            if (loaded && current.equals(signature)) {
                return;
            }
        }
        refresh(true);
    }

    /**
     * 重新发现全部 server 的工具，刷新缓存。
     *
     * @param force true=无条件重连；false=配置没变就跳过
     * @return 快照
     */
    private Map<String, Object> refresh(boolean force) {
        SettingsSnapshot settings = readSettings();
        ParseResult parsed = parseServers(settings.serversRaw());
        Set<String> patterns = parsePatterns(settings.autoApproveRaw());
        String newSignature = signatureOf(parsed.servers(), patterns, settings.enabled());

        synchronized (lock) {
            if (!force && loaded && newSignature.equals(signature)) {
                return snapshotInternal();
            }
        }

        if (!settings.enabled()) {
            // 总开关关闭：不连任何 server，状态与错误一并清空
            synchronized (lock) {
                statusByServer = new HashMap<>();
                configErrors = new ArrayList<>();
                signature = newSignature;
                loaded = true;
            }
            return snapshotInternal();
        }

        Map<String, ServerStatus> newStatuses = new HashMap<>();
        for (McpServerConfig server : parsed.servers()) {
            if (!server.enabled()) {
                newStatuses.put(server.name(), new ServerStatus(
                        server.name(), server.describe(), false, 0, List.of(),
                        "已在配置里停用", 0
                ));
                continue;
            }
            long started = System.nanoTime();
            try {
                List<ToolSpecification> tools = discover(server);
                List<Map<String, Object>> items = new ArrayList<>(tools.size());
                for (ToolSpecification tool : tools) {
                    Map<String, Object> item = new LinkedHashMap<>();
                    String wrappedName = serverToolName(server.name(), tool.name());
                    item.put("name", wrappedName);
                    // 与 Python 侧一致：raw_name 取包装名最后一段，用户能对上号
                    item.put("raw_name", wrappedName.substring(wrappedName.lastIndexOf("__") + 2));
                    item.put("description", truncate(tool.description(), 160));
                    items.add(item);
                }
                newStatuses.put(server.name(), new ServerStatus(
                        server.name(), server.describe(), true, tools.size(), items,
                        "", elapsedMillis(started)
                ));
                log.info("MCP server {} 就绪，发现 {} 个工具", server.name(), tools.size());
            } catch (RuntimeException e) {
                // 单 server 失败只影响它自己：其余 server 与内置工具照常
                String message = e.getClass().getSimpleName() + ": " + e.getMessage();
                log.warn("MCP server {} 连接失败：{}", server.name(), message);
                newStatuses.put(server.name(), new ServerStatus(
                        server.name(), server.describe(), false, 0, List.of(),
                        message, elapsedMillis(started)
                ));
            }
        }

        synchronized (lock) {
            statusByServer = newStatuses;
            configErrors = new ArrayList<>(parsed.errors());
            signature = newSignature;
            loaded = true;
        }
        return snapshotInternal();
    }

    /**
     * 拼出当前快照。
     *
     * @return 形如 {"enabled","servers","errors","tool_count"} 的快照
     */
    private Map<String, Object> snapshotInternal() {
        boolean enabled = readSettings().enabled();
        List<ServerStatus> statuses;
        List<String> errors;
        synchronized (lock) {
            statuses = new ArrayList<>(statusByServer.values());
            errors = new ArrayList<>(configErrors);
        }
        statuses.sort(Comparator.comparing(ServerStatus::name));

        List<Map<String, Object>> servers = new ArrayList<>(statuses.size());
        int toolCount = 0;
        for (ServerStatus status : statuses) {
            servers.add(status.toMap());
            toolCount += status.toolCount();
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("enabled", enabled);
        result.put("servers", servers);
        result.put("errors", errors);
        result.put("tool_count", toolCount);
        return result;
    }

    // ------------------------------------------------------------------ //
    // 二、连接
    // ------------------------------------------------------------------ //

    /**
     * 连上 server 并取回它声明的工具（列完立即关闭连接）。
     *
     * @param server server 配置
     * @return 工具描述列表
     * @throws RuntimeException 连接失败 / 协议错误 / 超时
     */
    private List<ToolSpecification> discover(McpServerConfig server) {
        McpTransport transport = buildTransport(server);
        long timeoutSeconds = Math.max(5L, Math.round(server.timeout()));
        McpClient client = DefaultMcpClient.builder()
                .transport(transport)
                .key(server.name())
                .clientName("backend-java")
                .clientVersion("0.1.0")
                .initializationTimeout(Duration.ofSeconds(timeoutSeconds))
                .toolExecutionTimeout(Duration.ofSeconds(timeoutSeconds))
                // 每次 reload 都希望拿到最新工具清单，不复用上一次的缓存
                .cacheToolList(false)
                .build();
        try {
            return client.listTools();
        } finally {
            try {
                // 只做发现、不保持长连接：关闭客户端同时释放子进程/HTTP 连接
                client.close();
            } catch (Exception e) {
                // AutoCloseable.close() 声明了受检异常，这里统一吞掉：关闭失败不影响发现结果
                log.debug("关闭 MCP client {} 失败：{}", server.name(), e.getMessage());
            }
        }
    }

    /**
     * 按配置构造传输层。
     *
     * @param server server 配置
     * @return 传输层实例
     * @throws UnsupportedOperationException sse 传输在 Java 侧暂不支持
     */
    private McpTransport buildTransport(McpServerConfig server) {
        switch (server.transport()) {
            case "stdio": {
                List<String> command = new ArrayList<>();
                command.add(server.command());
                command.addAll(server.args());
                StdioMcpTransport.Builder builder = StdioMcpTransport.builder()
                        .command(command)
                        .logEvents(false);
                // env 为空时不要传：传空 Map 会覆盖掉子进程的完整环境（PATH 就没了）
                if (!server.env().isEmpty()) {
                    builder.environment(server.env());
                }
                return builder.build();
            }
            case "streamable_http":
                return StreamableHttpMcpTransport.builder()
                        .url(server.url())
                        .customHeaders(server.headers())
                        .timeout(Duration.ofSeconds(Math.max(5L, Math.round(server.timeout()))))
                        .build();
            case "websocket":
                return WebSocketMcpTransport.builder()
                        .url(server.url())
                        .timeout(Duration.ofSeconds(Math.max(5L, Math.round(server.timeout()))))
                        .headersSupplier(() -> server.headers())
                        .build();
            case "sse":
                // LangChain4j 当前版本没有暴露 SSE 传输实现，明确告知而不是假装支持
                throw new UnsupportedOperationException(
                        "sse 传输在 Java 侧暂不支持，请改用 streamable_http");
            default:
                throw new IllegalArgumentException("不支持的传输方式：" + server.transport());
        }
    }

    // ------------------------------------------------------------------ //
    // 三、配置解析
    // ------------------------------------------------------------------ //

    /**
     * 读取三个 MCP 设置项；读不到时用最保守的默认值。
     *
     * @return 总开关、server 原始值、免确认名单原始值
     */
    private SettingsSnapshot readSettings() {
        boolean enabled;
        try {
            enabled = Boolean.TRUE.equals(settingsRegistry.getSetting("mcp.enabled"));
        } catch (RuntimeException e) {
            enabled = false;
        }
        if (!enabled) {
            return new SettingsSnapshot(false, List.of(), List.of());
        }
        Object servers;
        try {
            servers = settingsRegistry.getSetting("mcp.servers");
        } catch (RuntimeException e) {
            servers = List.of();
        }
        Object patterns;
        try {
            patterns = settingsRegistry.getSetting("mcp.auto_approve_tools");
        } catch (RuntimeException e) {
            patterns = List.of();
        }
        return new SettingsSnapshot(true, servers, patterns);
    }

    /**
     * 解析设置里的 server 列表，逐条容错：一条写错不影响其它条。
     *
     * @param raw 设置值（期望是对象数组）
     * @return 可用配置列表 + 错误说明列表
     */
    private ParseResult parseServers(Object raw) {
        List<McpServerConfig> servers = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        if (raw == null || (raw instanceof String text && text.isBlank())) {
            return new ParseResult(servers, errors);
        }
        if (!(raw instanceof List<?> items)) {
            errors.add("mcp.servers 必须是数组，收到 " + typeName(raw));
            return new ParseResult(servers, errors);
        }

        Set<String> seen = new TreeSet<>();
        for (int index = 0; index < items.size(); index++) {
            Object item = items.get(index);
            String where = "第 " + (index + 1) + " 条";
            if (!(item instanceof Map<?, ?> map)) {
                errors.add(where + "：必须是对象，收到 " + typeName(item));
                continue;
            }

            String name = textOf(map.get("name"));
            if (!NAME_PATTERN.matcher(name).matches()) {
                errors.add(where + "：name 只能包含字母、数字、下划线、连字符（1~32 位），收到 '"
                        + name + "'");
                continue;
            }
            if (!seen.add(name)) {
                // 重名会让工具名冲突、策略互相覆盖，必须拦
                errors.add(where + "：name `" + name + "` 与前面的配置重复");
                continue;
            }

            String transport = textOf(map.get("transport"));
            transport = transport.isEmpty() ? "stdio" : transport.toLowerCase(Locale.ROOT);
            // 常见别名归一：http 是 streamable_http 的通俗写法
            if ("http".equals(transport)) {
                transport = "streamable_http";
            }
            if (!SUPPORTED_TRANSPORTS.contains(transport)) {
                errors.add(where + "：transport 只支持 stdio/sse/streamable_http/websocket，收到 '"
                        + transport + "'");
                continue;
            }

            String command = textOf(map.get("command"));
            String url = textOf(map.get("url"));
            if ("stdio".equals(transport) && command.isEmpty()) {
                errors.add(where + "：stdio 传输必须提供 command");
                continue;
            }
            if (!"stdio".equals(transport) && url.isEmpty()) {
                errors.add(where + "：" + transport + " 传输必须提供 url");
                continue;
            }

            List<String> args;
            Object rawArgs = map.get("args");
            if (rawArgs == null) {
                args = List.of();
            } else if (rawArgs instanceof List<?> argList) {
                args = new ArrayList<>(argList.size());
                for (Object arg : argList) {
                    args.add(String.valueOf(arg));
                }
            } else {
                errors.add(where + "：args 必须是数组，收到 " + typeName(rawArgs));
                continue;
            }

            double timeout;
            Object rawTimeout = map.get("timeout");
            if (rawTimeout == null) {
                timeout = DEFAULT_TIMEOUT;
            } else {
                try {
                    timeout = Double.parseDouble(String.valueOf(rawTimeout).strip());
                } catch (NumberFormatException e) {
                    errors.add(where + "：timeout 必须是数字");
                    continue;
                }
            }
            // 下限 5 秒、上限 600 秒：再小基本连不上，再大属于配置错误
            timeout = Math.max(5.0, Math.min(timeout, 600.0));

            servers.add(new McpServerConfig(
                    name,
                    transport,
                    command,
                    List.copyOf(args),
                    stringMap(map.get("env")),
                    url,
                    stringMap(map.get("headers")),
                    boolOf(map.get("enabled"), true),
                    boolOf(map.get("auto_approve"), false),
                    timeout
            ));
        }
        return new ParseResult(servers, errors);
    }

    /**
     * 解析「免确认名单」：server / server:* / server:tool 三种写法。
     *
     * @param raw 设置值（字符串数组）
     * @return 规范化后的模式集合（小写）
     */
    private Set<String> parsePatterns(Object raw) {
        Set<String> patterns = new TreeSet<>();
        if (!(raw instanceof List<?> items)) {
            return patterns;
        }
        for (Object item : items) {
            String text = item == null ? "" : String.valueOf(item).strip().toLowerCase(Locale.ROOT);
            if (!text.isEmpty()) {
                patterns.add(text);
            }
        }
        return patterns;
    }

    /**
     * 把 JSON 对象安全转成「字符串 → 字符串」映射。
     *
     * @param raw 原始值，可能不是 Map
     * @return 规范化后的映射；非法输入返回空 Map
     */
    private Map<String, String> stringMap(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return Map.of();
        }
        Map<String, String> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (entry.getKey() != null && entry.getValue() != null) {
                result.put(String.valueOf(entry.getKey()), String.valueOf(entry.getValue()));
            }
        }
        return result;
    }

    /**
     * 计算影响工具集合的配置指纹。
     *
     * <p>env/headers 里可能有密钥，因此指纹只在内存里比较、绝不打印。</p>
     *
     * @param servers  解析后的配置
     * @param patterns 免确认名单
     * @param enabled  总开关
     * @return 可比较的字符串
     */
    private String signatureOf(List<McpServerConfig> servers, Set<String> patterns, boolean enabled) {
        Map<String, Object> fingerprint = new LinkedHashMap<>();
        fingerprint.put("enabled", enabled);
        List<Object> items = new ArrayList<>(servers.size());
        for (McpServerConfig server : servers) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", server.name());
            item.put("transport", server.transport());
            item.put("enabled", server.enabled());
            item.put("command", server.command());
            item.put("args", server.args());
            item.put("url", server.url());
            item.put("auto_approve", server.autoApprove());
            item.put("timeout", server.timeout());
            item.put("env", server.env());
            item.put("headers", server.headers());
            items.add(item);
        }
        fingerprint.put("servers", items);
        fingerprint.put("patterns", new ArrayList<>(patterns));
        return JsonUtils.toJson(fingerprint);
    }

    /**
     * 算出 MCP 工具在 LangChain 里的名字：mcp__&lt;server&gt;__&lt;tool&gt;。
     *
     * @param server server 名
     * @param tool   MCP 侧原始工具名
     * @return 符合 LangChain 命名规则的工具名
     */
    private String serverToolName(String server, String tool) {
        String raw = "mcp__" + server + "__" + tool;
        // 非法字符统一换成下划线（MCP 规范没限制工具名字符，但 LangChain 限制）
        String clean = raw.replaceAll("[^A-Za-z0-9_-]", "_");
        return clean.length() > MAX_TOOL_NAME ? clean.substring(0, MAX_TOOL_NAME) : clean;
    }

    /**
     * 构造「试连」结果。
     *
     * @param ok         是否成功
     * @param tools      工具清单
     * @param error      失败原因
     * @param durationMs 耗时（毫秒）
     * @return 结果 Map
     */
    private Map<String, Object> testResult(boolean ok,
                                           List<Map<String, Object>> tools,
                                           String error,
                                           long durationMs) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ok", ok);
        result.put("tools", tools);
        result.put("error", error);
        result.put("duration_ms", durationMs);
        return result;
    }

    /**
     * 计算从 started 到现在的毫秒数。
     *
     * @param startedNanos System.nanoTime() 的起点
     * @return 毫秒数
     */
    private long elapsedMillis(long startedNanos) {
        return Math.max(0L, (System.nanoTime() - startedNanos) / 1_000_000L);
    }

    /**
     * 截断描述文本。
     *
     * @param text  原文（可为 null）
     * @param limit 最大字符数
     * @return 截断后的文本
     */
    private String truncate(String text, int limit) {
        if (text == null) {
            return "";
        }
        return text.length() > limit ? text.substring(0, limit) : text;
    }

    /**
     * 安全转字符串并去空白。
     *
     * @param value 原始值
     * @return 字符串；null 转空串
     */
    private String textOf(Object value) {
        return value == null ? "" : String.valueOf(value).strip();
    }

    /**
     * 安全转布尔值。
     *
     * @param value        原始值
     * @param defaultValue 缺失时的默认值
     * @return 布尔值
     */
    private boolean boolOf(Object value, boolean defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof Boolean bool) {
            return bool;
        }
        if (value instanceof Number number) {
            // JSON 里写成 1/0 也按真/假处理，与 Python 的 bool(1) 保持一致
            return number.intValue() != 0;
        }
        return Boolean.parseBoolean(String.valueOf(value).strip());
    }

    /**
     * 取值的类型名，用于错误提示。
     *
     * @param value 原始值
     * @return 类型名
     */
    private String typeName(Object value) {
        return value == null ? "null" : value.getClass().getSimpleName();
    }

    /**
     * 一次设置读取的结果。
     *
     * @param enabled        总开关
     * @param serversRaw     server 原始值
     * @param autoApproveRaw 免确认名单原始值
     */
    private record SettingsSnapshot(
            // 总开关
            boolean enabled,
            // server 原始值
            Object serversRaw,
            // 免确认名单原始值
            Object autoApproveRaw
    ) {
    }

    /**
     * 配置解析结果。
     *
     * @param servers 可用配置
     * @param errors  错误说明
     */
    private record ParseResult(
            // 可用配置
            List<McpServerConfig> servers,
            // 错误说明
            List<String> errors
    ) {
    }

    /**
     * 一个 MCP server 的连接配置（解析后的规范化形态）。
     *
     * @param name         server 名（唯一标识，也是工具名第一段）
     * @param transport    传输方式：stdio / streamable_http / websocket / sse
     * @param command      stdio：要执行的命令
     * @param args         stdio：命令参数
     * @param env          stdio：追加的环境变量
     * @param url          远程传输：服务地址
     * @param headers      远程传输：请求头（常放 token）
     * @param enabled      是否启用
     * @param autoApprove  该 server 的工具是否默认免确认
     * @param timeout      连接/调用超时（秒）
     */
    private record McpServerConfig(
            // server 名
            String name,
            // 传输方式
            String transport,
            // stdio 命令
            String command,
            // stdio 参数
            List<String> args,
            // stdio 环境变量
            Map<String, String> env,
            // 远程地址
            String url,
            // 远程请求头
            Map<String, String> headers,
            // 是否启用
            boolean enabled,
            // 是否默认免确认
            boolean autoApprove,
            // 超时（秒）
            double timeout
    ) {

        /**
         * 给界面/日志用的一句话描述（不含 env/headers，避免密钥进日志）。
         *
         * @return 如 "stdio: npx -y server-filesystem D:/work"
         */
        String describe() {
            if ("stdio".equals(transport)) {
                String joined = args.isEmpty() ? "" : " " + String.join(" ", args);
                return "stdio: " + command + joined;
            }
            return transport + ": " + url;
        }
    }

    /**
     * 一个 server 的发现结果。
     *
     * @param name        server 名
     * @param description 传输方式描述（不含密钥）
     * @param ok          是否成功拿到工具列表
     * @param toolCount   工具数
     * @param tools       工具清单（名字 + 描述）
     * @param error       失败原因（ok=false 时非空）
     * @param durationMs  发现耗时（毫秒）
     */
    private record ServerStatus(
            // server 名
            String name,
            // 传输方式描述
            String description,
            // 是否成功
            boolean ok,
            // 工具数
            int toolCount,
            // 工具清单
            List<Map<String, Object>> tools,
            // 失败原因
            String error,
            // 耗时
            long durationMs
    ) {

        /**
         * 转成可下发的字典。
         *
         * @return 状态 Map
         */
        Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("name", name);
            map.put("description", description);
            map.put("ok", ok);
            map.put("tool_count", toolCount);
            map.put("tools", tools);
            map.put("error", error);
            map.put("duration_ms", durationMs);
            return map;
        }
    }
}
