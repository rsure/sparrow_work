// 模块说明：工具操作类型枚举（对应 Python policy.py 的 Kind）。
package com.example.backendjava.tools;

/**
 * 操作类型：决定默认裁决等级。
 *
 * <p>与 Python 侧一一对应；新增类型时必须同时更新
 * {@link ToolPolicyRegistry#defaultLevel(ToolKind)}，否则会按 DENY 处理。</p>
 */
public enum ToolKind {

    /** 只读查询：列目录、读文件、检索。默认直接放行。 */
    READ("read"),

    /** 写磁盘：新建、覆盖、修改、删除、移动。 */
    WRITE("write"),

    /** 执行命令：跑脚本、跑测试、跑构建。 */
    EXEC("exec"),

    /** 联网：搜索、抓取网页、发 HTTP 请求。 */
    NET("net"),

    /** 外部 MCP server 提供的工具：能力不可知，默认拒绝，必须显式放行。 */
    MCP("mcp");

    /** 写进审计日志与路径策略时使用的字符串值。 */
    private final String value;

    /**
     * 枚举构造器。
     *
     * @param value 小写字符串值
     */
    ToolKind(String value) {
        this.value = value;
    }

    /** 返回小写字符串值（与 Python 侧一致）。 */
    public String value() {
        return value;
    }

    /**
     * 把字符串值解析成枚举；非法值返回 null。
     *
     * @param value 小写字符串值
     * @return 对应枚举；无法识别时 null
     */
    public static ToolKind fromValue(String value) {
        for (ToolKind kind : values()) {
            if (kind.value.equals(value)) {
                return kind;
            }
        }
        return null;
    }
}
