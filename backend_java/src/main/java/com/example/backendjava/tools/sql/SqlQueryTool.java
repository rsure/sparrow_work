// 模块说明：sql_query 工具（对应 Python sql_tool.py）。
//
// 为什么只读、而且只允许 SELECT：数据库文件常常就是「用户的全部业务数据」，
// 一次误判的 UPDATE/DELETE 就是不可恢复的损失。因此三层叠加：
//   1. SQL 语法层：只接受 SELECT / WITH / EXPLAIN 开头，出现分号（多语句）直接拒；
//   2. 连接层：以只读属性打开数据库，就算语法检查漏了，SQLite 也会报错；
//   3. 权限层：策略登记为 READ，并按 db_path 做路径范围校验。
package com.example.backendjava.tools.sql;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.PathPolicy; // 项目内：路径操作策略（受保护目录 / 工作区白名单）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：Properties 传给 JDBC 驱动的只读配置
import java.util.Properties;
// 标准库：ArrayList 收集结果行
import java.util.ArrayList;
// 标准库：List 结果行与待校验路径
import java.util.List;
// 标准库：Map 弹窗参数
import java.util.Map;
// 标准库：Locale 大小写转换
import java.util.Locale;
// 标准库：Path 数据库文件路径
import java.nio.file.Path;
// 标准库：Files 判断文件存在
import java.nio.file.Files;
// 标准库：Connection/DriverManager/ResultSet/ResultSetMetaData/SQLException/Statement
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
// 标准库：Pattern 做 SQL 关键词的边界匹配
import java.util.regex.Pattern;
// 第三方（SQLite JDBC）：SQLiteConfig 提供只读连接属性
import org.sqlite.SQLiteConfig;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 以只读方式查询本机 SQLite 数据库。
 */
@Component
public class SqlQueryTool extends AbstractGuardedTool {

    /** 默认返回多少行。 */
    private static final int DEFAULT_ROWS = 50;

    /** 一次最多取多少行，防止 SELECT * FROM 大表把上下文灌满。 */
    private static final int MAX_ROWS = 200;

    /** 单条查询的执行时限（秒）。 */
    private static final int QUERY_TIMEOUT_SECONDS = 5;

    /** 结果文本的字符上限。 */
    private static final int MAX_OUTPUT_CHARS = 8_000;

    /** 允许的语句开头（忽略大小写与开头的注释后仍需命中其中之一）。 */
    private static final List<String> ALLOWED_PREFIXES = List.of("select", "with", "explain");

    /**
     * 写操作关键词：尽管白名单已限定开头，仍做二次检查。
     *
     * <p>例如 {@code WITH t AS (SELECT 1) DELETE FROM x} 也是以 WITH 开头的。</p>
     */
    private static final Pattern FORBIDDEN_KEYWORDS = Pattern.compile(
            "(?i)(?<![\\w])(insert|update|delete|drop|alter|create|replace|"
                    + "attach|detach|pragma|vacuum|reindex|truncate)(?![\\w])");

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public SqlQueryTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "sql_query";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "以只读方式在本机 SQLite 数据库上执行一条 SELECT 查询。"
                + "适用：这张表有多少行、按月份汇总一下、看看表结构。"
                + "不适用：改数据（只读）、MySQL/PostgreSQL（只支持 SQLite 文件）、导出大结果集。"
                + "查表结构可用：SELECT name, sql FROM sqlite_master WHERE type='table'。";
    }

    /**
     * 把参数翻译成一次待裁决的只读操作。
     *
     * <p>路径参数必须放进 ToolAction.paths，否则 sql_query 会变成「可以打开任意路径文件」的口子。</p>
     *
     * @param args 工具入参：db_path / query / max_rows
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path path = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "db_path"));
        String query = ToolArgs.rawString(args, "query", "");
        String previewQuery = query.length() > 60 ? query.substring(0, 60) : query;
        return new ToolAction(
                name(),
                ToolKind.READ,
                path.toString(),
                List.of(path),
                Map.of("db_path", path.toString(), "query", previewQuery),
                "AI 将以只读方式查询数据库：" + path.getFileName()
        );
    }

    /**
     * 执行查询：语法校验 -> 路径校验 -> 只读连接 -> 限制行数 -> 格式化。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 列名 + 各行数据
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        String query = ToolArgs.rawString(args, "query", "");
        String reason = checkReadonlySql(query);
        if (reason != null) {
            return ToolResult.fail(reason);
        }
        Path path = action.paths().get(0);
        if (!Files.isRegularFile(path)) {
            return ToolResult.fail("找不到数据库文件：" + path);
        }
        // 路径范围校验再走一遍：工具可能被直接调用（不经统一关卡），不能只依赖 Action
        String blocked = PathPolicy.pathDecision(path, PathPolicy.OP_READ);
        if (blocked != null) {
            return ToolResult.fail(blocked);
        }
        int limit = Math.max(1, Math.min(MAX_ROWS, ToolArgs.optionalInt(args, "max_rows", DEFAULT_ROWS)));

        try {
            DriverManager.setLoginTimeout(5);
            SQLiteConfig config = new SQLiteConfig();
            // 只读模式：文件不存在直接报错，任何写操作直接失败
            config.setReadOnly(true);
            Properties properties = config.toProperties();
            try (Connection connection = DriverManager.getConnection("jdbc:sqlite:" + path, properties);
                 Statement statement = connection.createStatement()) {
                try {
                    // SQLite JDBC 用进度回调实现查询超时；不支持时忽略，不影响查询本身
                    statement.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
                } catch (SQLException ignored) {
                    // 某些驱动版本不支持；继续执行
                }
                statement.setMaxRows(limit + 1);
                try (ResultSet resultSet = statement.executeQuery(query)) {
                    return formatResult(resultSet, limit, path);
                }
            }
        } catch (SQLException e) {
            String message = e.getMessage() == null ? "" : e.getMessage();
            if (message.toLowerCase(Locale.ROOT).contains("interrupted")
                    || message.toLowerCase(Locale.ROOT).contains("timeout")) {
                return ToolResult.fail("查询超过 " + QUERY_TIMEOUT_SECONDS
                        + " 秒被中断，请加索引或缩小范围");
            }
            return ToolResult.fail("SQL 执行失败: " + message);
        } catch (RuntimeException e) {
            return ToolResult.fail("不是有效的 SQLite 数据库或文件已损坏: " + e.getMessage());
        }
    }

    /**
     * 把 ResultSet 格式化成「列: a | b | c」加逐行数据。
     *
     * @param resultSet 查询结果
     * @param limit     最多返回多少行
     * @param path      数据库路径（只用于结尾提示）
     * @return 工具结果
     * @throws SQLException 读取结果失败
     */
    private static ToolResult formatResult(ResultSet resultSet, int limit, Path path) throws SQLException {
        ResultSetMetaData meta = resultSet.getMetaData();
        int columnCount = meta.getColumnCount();
        if (columnCount == 0) {
            return ToolResult.ok("查询已执行，但没有返回任何列");
        }
        List<String> columns = new ArrayList<>(columnCount);
        for (int i = 1; i <= columnCount; i++) {
            columns.add(meta.getColumnLabel(i));
        }
        List<String> lines = new ArrayList<>();
        lines.add("列: " + String.join(" | ", columns));
        int shown = 0;
        boolean truncated = false;
        boolean tooLong = false;
        int currentLength = lines.get(0).length();
        while (resultSet.next()) {
            if (shown >= limit) {
                truncated = true;
                break;
            }
            List<String> cells = new ArrayList<>(columnCount);
            for (int i = 1; i <= columnCount; i++) {
                cells.add(formatCell(resultSet.getObject(i)));
            }
            String line = String.join(" | ", cells);
            if (currentLength + line.length() + 1 > MAX_OUTPUT_CHARS) {
                tooLong = true;
                break;
            }
            lines.add(line);
            currentLength += line.length() + 1;
            shown++;
        }
        if (shown == 0) {
            return ToolResult.ok("列: " + String.join(" | ", columns) + "\n（没有匹配的记录）");
        }
        StringBuilder text = new StringBuilder(String.join("\n", lines));
        if (truncated) {
            text.append("\n…（超过 ").append(limit).append(" 行，已截断；可加 WHERE 或聚合后再查）");
        }
        if (tooLong) {
            text.append("\n…（结果超过 ").append(MAX_OUTPUT_CHARS).append(" 字符，已截断）");
        }
        text.append("\n（共 ").append(shown).append(" 行，数据库：").append(path.getFileName()).append("）");
        return ToolResult.ok(text.toString());
    }

    /**
     * 把单元格值转成一行可读文本。
     *
     * @param value SQLite 返回的原始值（可能是 null / byte[] / 数字 / 字符串）
     * @return 用于拼接表格的字符串
     */
    private static String formatCell(Object value) {
        if (value == null) {
            return "NULL";
        }
        if (value instanceof byte[] bytes) {
            // 二进制（图片、压缩包）不进上下文，只报长度，否则会把上下文塞满乱码
            return "<" + bytes.length + " 字节二进制>";
        }
        return String.valueOf(value)
                .replace("\r\n", "\n")
                .replace("\n", " ⏎ ")
                .replace("|", "\\|");
    }

    /**
     * 校验一条 SQL 是否「只读且单条」。
     *
     * @param query 用户/模型给的 SQL
     * @return 允许时返回 null；不允许时返回原因
     */
    public static String checkReadonlySql(String query) {
        String text = stripLeadingComments(query == null ? "" : query);
        if (text.isBlank()) {
            return "SQL 不能为空";
        }
        // 分号：只在末尾允许一个；中间还有分号就是多语句，一律拒绝
        String body = text.stripTrailing();
        String inner = body.endsWith(";") ? body.substring(0, body.length() - 1) : body;
        if (inner.contains(";")) {
            return "一次只能执行一条 SQL（检测到多条语句）";
        }
        String lower = inner.toLowerCase(Locale.ROOT).stripLeading();
        boolean allowed = ALLOWED_PREFIXES.stream().anyMatch(lower::startsWith);
        if (!allowed) {
            return "只允许只读查询：语句必须以 SELECT / WITH / EXPLAIN 开头";
        }
        var matcher = FORBIDDEN_KEYWORDS.matcher(lower);
        if (matcher.find()) {
            return "只允许只读查询（检测到会改写数据的 "
                    + matcher.group(1).toUpperCase(Locale.ROOT) + " 语句）";
        }
        return null;
    }

    /**
     * 去掉字符串最前面的 {@code --} 行注释与 {@code /* *\/} 块注释。
     *
     * <p>模型很喜欢写「-- 看看用户表」再换行写 SELECT；直接取前 6 个字符判断开头
     * 会把合法查询误判成「不支持」。</p>
     *
     * @param sql 原始 SQL
     * @return 去掉前导注释与空白后的 SQL
     */
    private static String stripLeadingComments(String sql) {
        String text = sql.stripLeading();
        while (true) {
            if (text.startsWith("--")) {
                int newline = text.indexOf('\n');
                text = newline < 0 ? "" : text.substring(newline + 1).stripLeading();
                continue;
            }
            if (text.startsWith("/*")) {
                int end = text.indexOf("*/");
                text = end < 0 ? "" : text.substring(end + 2).stripLeading();
                continue;
            }
            return text;
        }
    }
}
