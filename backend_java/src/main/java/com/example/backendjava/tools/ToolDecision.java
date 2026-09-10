// 模块说明：一次裁决的结果（对应 Python policy.py 的 Decision）。
package com.example.backendjava.tools;

/**
 * 一次工具调用的裁决结果。
 *
 * @param level  裁决等级
 * @param reason 原因或说明：DENY 时是拒绝理由（直接作为 FAIL 文案）；
 *               ASK 时是弹窗正文；ALLOW 时可为空
 * @param title  弹窗标题（仅 ASK 时有意义）
 */
public record ToolDecision(
        // 裁决等级
        ToolLevel level,
        // 原因/说明
        String reason,
        // 弹窗标题
        String title
) {

    /**
     * 构造一个「直接放行」的结果。
     *
     * @return ALLOW 裁决
     */
    public static ToolDecision allow() {
        return new ToolDecision(ToolLevel.ALLOW, "", "");
    }

    /**
     * 构造一个「拒绝」的结果。
     *
     * @param reason 拒绝原因
     * @return DENY 裁决
     */
    public static ToolDecision deny(String reason) {
        return new ToolDecision(ToolLevel.DENY, reason, "");
    }
}
