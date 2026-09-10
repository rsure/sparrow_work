// 模块说明：诊断信息接口。summary 返回运行环境数字，export 返回已脱敏的 zip 包。
// 对应 Python 侧 app/services/diagnostic_service.py（OPS-3）。
package com.example.backendjava.service;

// 标准库：Map 用于诊断概要
import java.util.HashMap;
import java.util.Map;
// 标准库：LinkedHashMap 保持 meta / settings / schema 按 key 顺序输出，便于对照
import java.util.LinkedHashMap;
// 标准库：List / ArrayList 装表名与列定义
import java.util.List;
import java.util.ArrayList;
// 标准库：Collections 把「按 id 倒序」翻成「按时间正序」，轨迹按发生顺序写进包里
import java.util.Collections;
// 标准库：内存 zip 缓冲，避免在用户磁盘上留临时文件
import java.io.ByteArrayOutputStream;
// 标准库：写 zip 条目时抛的受检异常
import java.io.IOException;
// 标准库：显式 UTF-8 写包内文本，避免平台默认编码写坏中文
import java.nio.charset.StandardCharsets;
// 标准库：时间戳（包名与 meta 里的导出时间）
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
// 标准库：正则（密钥形态的兜底擦除）
import java.util.regex.Pattern;
// 标准库：zip 打包
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

// 依赖注入：按类型注入仓库 / 注册表 / JDBC 模板
import jakarta.annotation.Resource;
// Spring：把本类注册成受管 Bean
import org.springframework.stereotype.Service;
// Spring Data：按页取「最近 N 条轨迹」，避免一次性拉全表
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
// Spring JDBC：直接读 SQLite 元数据（表清单、列定义）
import org.springframework.jdbc.core.JdbcTemplate;

// 项目内：应用配置（版本 / 服务名）
import com.example.backendjava.config.AppProperties;
// 项目内：诊断接口的 DTO 容器
import com.example.backendjava.dto.DiagnosticDtos;
// 项目内：轨迹实体
import com.example.backendjava.entity.TraceEvent;
// 项目内：轨迹表仓库
import com.example.backendjava.repository.TraceEventRepository;
// 项目内：设置注册表（导出配置的唯一来源）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：设置值脱敏（按键名抹掉疑似密钥）
import com.example.backendjava.settings.SettingsRedactor;
// 项目内：JSON 工具（序列化包内文件）
import com.example.backendjava.util.JsonUtils;

/**
 * 诊断服务。
 *
 * <p>与 Python 侧对齐的三条红线：</p>
 * <ol>
 *   <li>{@code summary} 只回运行环境数字，不含任何敏感内容；</li>
 *   <li>{@code export} 里的设置必须脱敏（按键名 + 容器键 + 密钥形态兜底三道防线）；</li>
 *   <li>包体一次性在内存里打好，再整体返回，避免半截 zip。</li>
 * </ol>
 */
@Service
public class DiagnosticService {

    /** 应用配置：版本号、服务名。 */
    @Resource
    private AppProperties appProperties;

    /** 轨迹表仓库：统计条数、取最近 N 条。 */
    @Resource
    private TraceEventRepository traceEventRepository;

    /** 设置注册表：导出的「脱敏配置」从这里读。 */
    @Resource
    private SettingsRegistry settingsRegistry;

    /** JDBC 模板：直接读 SQLite 元数据（表清单与列定义）。 */
    @Resource
    private JdbcTemplate jdbcTemplate;

    /** 轨迹最多打包 / 统计多少条。 */
    private static final int TRACE_LIMIT = 2000;

    /** 脱敏占位符：与 Python 侧保持一致，便于两边导出文件互相导回。 */
    private static final String REDACTED = SettingsRedactor.REDACTED;

    /** 兜底擦除：形如 sk-abcdefghijklmnop 的长串（OpenAI / DeepSeek 等常见形态）。 */
    private static final Pattern SECRET_VALUE_PATTERN =
            Pattern.compile("\\b(sk|pk|ghp|xoxb)-[A-Za-z0-9_\\-]{12,}");

    /** 包名时间戳格式：diagnostic-20261026-123456.zip。 */
    private static final DateTimeFormatter STAMP_FORMATTER =
            DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    /** 包内 README，写给拿到包的人看。 */
    private static final String README =
            "本诊断包用于排查问题，已按键名脱敏并做过密钥形态擦除，但仍建议仅在内部流转。\n"
                    + "meta.json=版本与环境 · settings.json=脱敏配置 · schema.json=库结构 · "
                    + "trace/recent.jsonl=最近的执行轨迹 · logs/app.log=日志尾部\n";

    /**
     * 返回诊断页需要的数字，不含任何敏感内容。
     *
     * <p>字段名沿用 Python 侧契约（前端诊断页按这些键渲染），值反映 Java 后端的真实情况：
     * {@code python} 填 JVM 版本、{@code db_revision} 与 {@code log_file} 为 null——
     * Java 后端没有迁移版本号，且默认只把日志打到控制台。</p>
     *
     * @return 形如 {version, python, platform, packaged, db_revision, log_file,
     *         log_bytes, trace_events, tables} 的概要
     */
    public Map<String, Object> summary() {
        Map<String, Object> res = new HashMap<>();
        res.put("version", appProperties.getVersion());
        // 字段名沿用前端契约（对应 Python 的解释器版本）；Java 侧填 JVM 版本
        res.put("python", System.getProperty("java.version"));
        res.put("platform", platform());
        // Java 后端暂无「打包运行」标志，固定为开发态
        res.put("packaged", false);
        // Java 用 schema.sql + Hibernate ddl-auto 建表，没有迁移版本号
        res.put("db_revision", null);
        // 默认只输出到控制台，未配置日志文件
        res.put("log_file", null);
        res.put("log_bytes", 0L);
        res.put("trace_events", traceEventCount());
        res.put("tables", tableCount());
        return res;
    }

    /**
     * 生成诊断包。
     *
     * <p>包内容与 Python 侧一致：meta.json / settings.json / schema.json /
     * trace/recent.jsonl / logs/app.log / README.txt。密钥不会出现在包里。</p>
     *
     * @return zip 字节与建议文件名
     */
    public DiagnosticDtos.DiagnosticPackage export() {
        String stamp = LocalDateTime.now().format(STAMP_FORMATTER);
        String filename = "diagnostic-" + stamp + ".zip";

        // 三个 JSON 文件与轨迹，序列化后统一做一次密钥形态的兜底擦除
        String metaText = scrub(JsonUtils.toPrettyJson(meta()));
        String settingsText = scrub(JsonUtils.toPrettyJson(settingsSnapshot()));
        String schemaText = scrub(JsonUtils.toPrettyJson(schemaSnapshot()));
        String traceText = scrub(traceJsonl());

        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(buffer)) {
            putEntry(zip, "meta.json", metaText);
            putEntry(zip, "settings.json", settingsText);
            putEntry(zip, "schema.json", schemaText);
            putEntry(zip, "trace/recent.jsonl", traceText);
            // 日志尾部：Java 默认不落盘，写空字节，保持包结构完整
            zip.putNextEntry(new ZipEntry("logs/app.log"));
            zip.write(logTail());
            zip.closeEntry();
            putEntry(zip, "README.txt", README);
        } catch (IOException e) {
            // 写内存流几乎不会失败；真失败说明是编程错误，直接抛出
            throw new IllegalStateException("生成诊断包失败：" + e.getMessage(), e);
        }
        return new DiagnosticDtos.DiagnosticPackage(buffer.toByteArray(), filename);
    }

    // ------------------------------------------------------------------ //
    // 包内各文件的快照
    // ------------------------------------------------------------------ //

    /**
     * 版本与环境信息（对应 Python 侧 {@code _meta()}）。
     *
     * @return 有序字典
     */
    private Map<String, Object> meta() {
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("exported_at", LocalDateTime.now().truncatedTo(ChronoUnit.SECONDS).toString());
        meta.put("app_name", appProperties.getName());
        meta.put("app_version", appProperties.getVersion());
        // 字段名沿用 Python 侧；Java 后端填 JVM 版本
        meta.put("python", System.getProperty("java.version"));
        meta.put("platform", platform());
        meta.put("packaged", false);
        meta.put("db_revision", null);
        meta.put("log_file", null);
        return meta;
    }

    /**
     * 取全部非密钥设置并脱敏（对应 Python 侧 {@code _settings_snapshot()}）。
     *
     * <p>安全红线：任何密钥都不得进包。{@link SettingsRegistry#getAllSettings()}
     * 本身就不含密钥行；这里再按键名与容器键各抹一道，兜住用户自定义 provider /
     * MCP headers 里塞的 token。</p>
     *
     * @return 脱敏后的设置字典；读设置失败时返回空字典，不让导出整体失败
     */
    private Map<String, Object> settingsSnapshot() {
        Map<String, Object> raw;
        try {
            raw = settingsRegistry.getAllSettings();
        } catch (RuntimeException e) {
            // 读设置失败时宁可少打一个文件，也不要让整个导出 500
            raw = Map.of();
        }
        Map<String, Object> redacted = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : raw.entrySet()) {
            redacted.put(entry.getKey(),
                    SettingsRedactor.redact(entry.getValue(), entry.getKey()));
        }
        return redacted;
    }

    /**
     * 读出库里的表与列定义（对应 Python 侧 {@code _schema_snapshot()}）。
     *
     * <p>直接查 SQLite 的 {@code sqlite_master} 与 {@code PRAGMA table_info}，
     * 比走 JPA 元模型更轻，也不用为每个实体单独写映射。</p>
     *
     * @return {表名: [{name, type, nullable}]}
     */
    private Map<String, List<Map<String, Object>>> schemaSnapshot() {
        Map<String, List<Map<String, Object>>> schema = new LinkedHashMap<>();
        for (String table : tableNames()) {
            List<Map<String, Object>> columns = new ArrayList<>();
            try {
                for (Map<String, Object> col :
                        jdbcTemplate.queryForList("PRAGMA table_info(" + quoteIdent(table) + ")")) {
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("name", col.get("name"));
                    c.put("type", col.get("type"));
                    // notnull：0=可空，1=非空
                    c.put("nullable", "0".equals(String.valueOf(col.get("notnull"))));
                    columns.add(c);
                }
            } catch (RuntimeException e) {
                // 单张表读结构失败不阻断整个导出：留一张空列清单继续
            }
            schema.put(table, columns);
        }
        return schema;
    }

    /**
     * 把最近的轨迹转成 JSONL（一行一条，便于 grep）。
     *
     * @return JSONL 文本；没有轨迹时返回空串
     */
    private String traceJsonl() {
        List<TraceEvent> events = recentTraceEvents();
        StringBuilder sb = new StringBuilder();
        for (TraceEvent event : events) {
            sb.append(JsonUtils.toJson(toTraceMap(event))).append('\n');
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ //
    // 小工具
    // ------------------------------------------------------------------ //

    /**
     * 当前操作系统与版本描述（对应 Python 侧 {@code platform.platform()} 的用途）。
     *
     * @return 形如 Windows 11 10.0 的文本
     */
    private static String platform() {
        return System.getProperty("os.name") + " " + System.getProperty("os.version");
    }

    /**
     * 最近轨迹条数（上限 2000，与 Python 侧 {@code _TRACE_LIMIT} 对齐）。
     *
     * @return 条数；读库失败时返回 0
     */
    private long traceEventCount() {
        try {
            return Math.min(traceEventRepository.count(), TRACE_LIMIT);
        } catch (RuntimeException e) {
            return 0;
        }
    }

    /**
     * 库里用户表数量（排除 SQLite 内部表）。
     *
     * @return 表数量；读库失败时返回 0
     */
    private int tableCount() {
        try {
            Integer count = jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                    Integer.class);
            return count == null ? 0 : count;
        } catch (RuntimeException e) {
            return 0;
        }
    }

    /**
     * 库里全部用户表名（按名字升序）。
     *
     * @return 表名列表；读库失败时返回空列表
     */
    private List<String> tableNames() {
        try {
            return jdbcTemplate.queryForList(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
                    String.class);
        } catch (RuntimeException e) {
            return List.of();
        }
    }

    /**
     * 取最近 {@link #TRACE_LIMIT} 条轨迹，按时间正序返回。
     *
     * <p>先按 id 倒序取一页（最便宜），再翻正，避免拉全表。</p>
     *
     * @return 轨迹列表；读库失败时返回空列表
     */
    private List<TraceEvent> recentTraceEvents() {
        try {
            List<TraceEvent> desc = traceEventRepository.findAll(
                    PageRequest.of(0, TRACE_LIMIT, Sort.by(Sort.Direction.DESC, "id")))
                    .getContent();
            List<TraceEvent> asc = new ArrayList<>(desc);
            Collections.reverse(asc);
            return asc;
        } catch (RuntimeException e) {
            return List.of();
        }
    }

    /**
     * 把轨迹实体转成 JSON 对象；payload 存的是 JSON 文本，这里解析成嵌套对象，
     * 与 Python 侧「payload 是对象」保持一致。
     *
     * @param event 轨迹实体
     * @return 有序字典
     */
    private Map<String, Object> toTraceMap(TraceEvent event) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", event.getId());
        map.put("session_id", event.getSessionId());
        map.put("turn_id", event.getTurnId());
        map.put("type", event.getType());
        // 解析失败时退回原始字符串，保证 JSONL 仍然合法
        map.put("payload", JsonUtils.parseOrDefault(event.getPayload(), Object.class, event.getPayload()));
        map.put("created_at", event.getCreatedAt());
        return map;
    }

    /**
     * 对最终文本做密钥形态的兜底擦除（第二道防线）。
     *
     * <p>为什么在「已经按键名脱敏」之后还要做一次：用户自定义 provider 的键名可能叫
     * {@code k}，MCP 的 args 里也可能直接写 {@code --token=sk-xxx}，按键名判断漏掉的，
     * 这一层能兜住。</p>
     *
     * @param text 原始文本
     * @return 擦除后的文本；null 原样返回
     */
    private static String scrub(String text) {
        if (text == null) {
            return null;
        }
        return SECRET_VALUE_PATTERN.matcher(text)
                .replaceAll(match -> match.group(1) + "-" + REDACTED);
    }

    /**
     * 日志尾部。Java 后端默认只输出到控制台，未配置日志文件，因此恒为空字节。
     *
     * @return 空字节数组
     */
    private byte[] logTail() {
        return new byte[0];
    }

    /**
     * 往 zip 里写一个文本条目（UTF-8）。
     *
     * @param zip  目标 zip
     * @param name 条目名（相对路径）
     * @param text 文本内容
     * @throws IOException 写流失败时
     */
    private static void putEntry(ZipOutputStream zip, String name, String text) throws IOException {
        zip.putNextEntry(new ZipEntry(name));
        zip.write(text.getBytes(StandardCharsets.UTF_8));
        zip.closeEntry();
    }

    /**
     * 给 SQL 标识符加双引号并转义内部引号，防止表名里的引号破坏 PRAGMA 语句。
     *
     * @param name 标识符
     * @return 加引号后的标识符
     */
    private static String quoteIdent(String name) {
        return "\"" + name.replace("\"", "\"\"") + "\"";
    }
}
