// 模块说明：HTTP 查询参数 limit 的「默认值 + 上限」契约表。
//
// 为什么需要它：limit 以前是散的 —— controller 里写默认值（20/200/50/100/500），
// service 里再各自 clamp 一次（100/50/无上限/无下限），同仓出现 4 种写法。
// 结果就是「前端按默认值 200 请求，Java 后端悄悄截到 100，用户打开长会话少一半消息」。
// 现在这张表是 Java 侧唯一来源，Python 侧镜像在 backend/app/core/limits.py，
// 两边数字必须逐项一致，改一处就要同步改另一处。
package com.example.backendjava.common;

/**
 * limit 参数的默认值与上限。
 *
 * <p><b>两层的分工：</b></p>
 * <ul>
 *   <li>HTTP 入口（controller）：用 {@code @Min(1) @Max(...)} 声明上限，越界直接 400，
 *       不做任何「悄悄纠正」——客户端传错了就该被告知，而不是拿到一份被改过的数据；</li>
 *   <li>内部入口（service、工具调用）：用 {@link #clamp(int, int)} 兜底，保证不会把
 *       {@code Pageable.ofSize(0)} 这种非法翻页大小传给 Spring Data。</li>
 * </ul>
 *
 * <p><b>为什么每个端点一个上限而不是全局 100：</b>不同端点的合理窗口本来就不同 ——
 * 左栏会话列表一屏 20 条足够，历史回填要 200 条，轨迹排查一次要 500 条。
 * 统一成一个数字只会让某一类端点变难用，所以这里统一的是「一处定义」而不是「一个数值」。</p>
 */
public final class PageLimits {

    /** 最近会话列表默认条数：前端左栏一屏 20 条。 */
    public static final int DEFAULT_CHAT_SESSIONS = 20;

    /** 最近会话列表上限：再多也不会一次全查出来。 */
    public static final int MAX_CHAT_SESSIONS = 100;

    /** 历史消息默认条数：一次回填 200 条，够覆盖常见长度的会话。 */
    public static final int DEFAULT_CHAT_HISTORY = 200;

    /** 历史消息上限：与默认值相同 —— 超过 200 条的部分走「加载更早」而不是一次拉完。 */
    public static final int MAX_CHAT_HISTORY = 200;

    /** `@` 文件候选默认条数。 */
    public static final int DEFAULT_FILE_SEARCH = 20;

    /** `@` 文件候选上限：候选是给人选的，50 条以后用户也不会往下翻。 */
    public static final int MAX_FILE_SEARCH = 50;

    /** 审计记录默认条数。 */
    public static final int DEFAULT_AUDIT = 100;

    /** 审计记录上限：与 Python 侧 Query(ge=1, le=500) 保持一致。 */
    public static final int MAX_AUDIT = 500;

    /** 记忆条目默认条数。 */
    public static final int DEFAULT_MEMORY = 100;

    /** 记忆条目上限：与 Python 侧 Query(ge=1, le=500) 保持一致。 */
    public static final int MAX_MEMORY = 500;

    /** 轨迹会话列表默认条数。 */
    public static final int DEFAULT_TRACE_SESSIONS = 50;

    /** 轨迹会话列表上限。 */
    public static final int MAX_TRACE_SESSIONS = 200;

    /** 轨迹轮次列表默认条数。 */
    public static final int DEFAULT_TRACE_TURNS = 50;

    /** 轨迹轮次列表上限。 */
    public static final int MAX_TRACE_TURNS = 200;

    /** 轨迹事件默认条数：一次排查通常要看好几百条事件。 */
    public static final int DEFAULT_TRACE_EVENTS = 500;

    /** 轨迹事件上限：与 Python 侧 Query(ge=1, le=5000) 保持一致。 */
    public static final int MAX_TRACE_EVENTS = 5000;

    /** 文档列表默认条数。 */
    public static final int DEFAULT_RAG_DOCS = 50;

    /** 文档列表上限。 */
    public static final int MAX_RAG_DOCS = 200;

    /**
     * 私有构造器：本类只放常量，不允许实例化。
     */
    private PageLimits() {
    }

    /**
     * 给「非 HTTP 入口」做兜底：把 limit 夹到 {@code 1..max}。
     *
     * <p>HTTP 入口已经由 {@code @Min/@Max} 拦过，这里是为了防止 service 被工具或内部代码
     * 直接调用时传进 0 / 负数，导致 {@code Pageable.ofSize} 抛 {@code IllegalArgumentException}。</p>
     *
     * @param limit 调用方给的窗口大小
     * @param max   该端点的上限
     * @return 夹到 1~max 之后的窗口大小
     */
    public static int clamp(int limit, int max) {
        return Math.max(1, Math.min(limit, max));
    }
}
