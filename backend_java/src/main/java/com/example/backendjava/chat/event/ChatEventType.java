// 模块说明：SSE 事件名枚举。全后端「事件名字符串」的唯一来源。
//
// 为什么要有这个枚举：事件名是前后端契约（见 frontend/src/services/chat.ts 的 dispatchChatEvent）。
// 如果散落在各处写 "token" / "delta" / "done" 这样的字面量，拼错一个字母前端就静默丢事件，
// 而且编译期毫无提示 —— 本项目已经踩过这个坑（曾经发 "delta"，前端只认 "token"）。
// 约定：新增事件必须先在这里登记，再在 ChatEventPayloads 里加载荷。
package com.example.backendjava.chat.event;

/**
 * 对话 SSE 事件类型。
 *
 * <p>枚举常量名 = 前端 switch 的分支名，wireName 用于发送（两者保持一致，
 * 保留 wireName 是为了将来需要改线上名字时只改一处）。</p>
 */
public enum ChatEventType {

    /** 思考/准备阶段提示：让用户知道后端在做事，而不是卡住了。 */
    THINKING("thinking"),

    /** 模型增量文本：一段一段的正文。 */
    TOKEN("token"),

    /** 工具开始执行。 */
    TOOL_START("tool_start"),

    /** 工具执行结束（含截断信息，前端据此显示「展开全文」）。 */
    TOOL_END("tool_end"),

    /** 需要用户确认：发完这条事件后，当前 SSE 流必须立刻关闭。 */
    CONFIRM_REQUIRED("confirm_required"),

    /** 用户主动停止。 */
    STOPPED("stopped"),

    /** 一轮正常结束：携带答案与统计。 */
    DONE("done"),

    /** 出错：message 面向用户，detail 只在 debug 模式带。 */
    ERROR("error"),

    /** 用户的插话已被注入到工具结果中。 */
    STEER_INJECTED("steer_injected"),

    /** 预算（token/费用/时长）超限。 */
    BUDGET_EXCEEDED("budget_exceeded"),

    /** 拆解出的任务计划（`\doc` 与计划模式使用）。 */
    PLAN("plan"),

    /** 计划变更。 */
    PLAN_UPDATE("plan_update"),

    /** 子任务开始。 */
    TASK_START("task_start"),

    /** 子任务结束。 */
    TASK_END("task_end");

    /** 线上发送用的事件名，必须与前端 switch 的分支字面量一致。 */
    private final String wireName;

    /**
     * 构造事件类型。
     *
     * @param wireName 线上发送用的事件名
     */
    ChatEventType(String wireName) {
        this.wireName = wireName;
    }

    /**
     * 读取线上事件名。
     *
     * @return 形如 token / tool_start 的字符串
     */
    public String wireName() {
        return wireName;
    }
}
