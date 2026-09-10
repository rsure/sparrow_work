// 模块说明：工具安全策略枚举。用于决定工具是否需要用户确认、是否允许在子 Agent 中使用。
package com.example.backendjava.common;

/**
 * 工具策略。
 *
 * <p>Python 侧用 policy.py 给每个工具登记策略；Java 侧先用枚举把类别固定下来，
 * 后续可以扩展成“工具名 + 参数条件”的规则表。</p>
 */
public enum ToolPolicy {

    /** 只读：读文件、列目录、检索，不需要用户确认。 */
    READ_ONLY("只读操作，不需要用户确认"),

    /** 写盘：新建/覆盖/移动/删除文件，执行前必须让用户确认。 */
    WRITE("写盘操作，执行前必须让用户确认"),

    /** 执行：运行命令或脚本，执行前必须让用户确认。 */
    EXECUTE("执行命令，执行前必须让用户确认"),

    /** 联网：搜索、抓取网页、发 HTTP 请求，默认关闭。 */
    NETWORK("联网操作，默认关闭，需要用户显式开启"),

    /** 数据库：只读 SQL 查询，或需要确认的写库操作。 */
    DATABASE("数据库操作，按具体语句决定是否确认");

    /** 策略的中文说明，用于设置页展示与日志。 */
    private final String description;

    /**
     * 枚举构造器。
     *
     * @param description 中文说明
     */
    ToolPolicy(String description) {
        this.description = description;
    }

    /** 返回策略说明。 */
    public String getDescription() {
        return description;
    }

    /**
     * 是否需要用户确认。
     *
     * @return 写盘、执行、数据库默认需要确认；只读与联网不需要（联网由开关控制）
     */
    public boolean requiresConfirmation() {
        return this == WRITE || this == EXECUTE || this == DATABASE;
    }
}
