// 模块说明：工具裁决等级枚举（对应 Python policy.py 的 Level）。
package com.example.backendjava.tools;

/**
 * 裁决等级。
 */
public enum ToolLevel {

    /** 直接执行，不打扰用户。 */
    ALLOW("allow"),

    /** 需要用户确认（由 ToolApprovalGateway 弹窗/中断）。 */
    ASK("ask"),

    /** 拒绝执行，不弹窗。 */
    DENY("deny");

    /** 写审计日志用的字符串值。 */
    private final String value;

    /**
     * 枚举构造器。
     *
     * @param value 小写字符串值
     */
    ToolLevel(String value) {
        this.value = value;
    }

    /** 返回小写字符串值。 */
    public String value() {
        return value;
    }
}
