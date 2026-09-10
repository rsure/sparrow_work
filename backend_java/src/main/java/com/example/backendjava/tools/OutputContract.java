// 模块说明：工具输出治理契约（对应 Python app/tools/output_contract.py）。
//
// 工具输出会直接进模型上下文。read_file 读一份 3 万行的日志、grep 命中几千条，
// 一次就能把上下文窗口顶满。这一层的定位是「上下文保险丝」：
// 模型默认只看前 N 个字符，完整内容落盘保存，需要细节时可按续读标记取回。
package com.example.backendjava.tools;

// 标准库：UUID 生成续读标记里的唯一后缀
import java.util.UUID;
// 标准库：ConcurrentHashMap 保存「最近一次截断」登记
import java.util.concurrent.ConcurrentHashMap;
// 标准库：Map 的键值访问
import java.util.Map;
// 日志：落盘失败时留下线索但不打断工具调用
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：设置注册表——截断开关与阈值的读取入口
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：设置行存储——把完整内容写进 app_settings 的临时键
import com.example.backendjava.settings.SettingRowStore;
// 项目内：JSON 工具——临时内容按 JSON 字符串存，读回时类型安全
import com.example.backendjava.util.JsonUtils;

/**
 * 工具输出截断与续读。
 */
@Component
public class OutputContract {

    /** 本模块专用日志器。 */
    private static final Logger log = LoggerFactory.getLogger(OutputContract.class);

    /** 续读键的固定前缀：与普通设置键（组.键）区分开，便于清理与过滤。 */
    public static final String CONTINUATION_PREFIX = "tool-out-";

    /** 单条续读内容最多存多少字符（约 2M 字符）：再大就不落盘，避免把设置库撑爆。 */
    private static final int MAX_CONTINUATION_CHARS = 2_000_000;

    /** 截断时追加的提示文案模板。 */
    private static final String TRUNCATE_NOTE =
            "\n\n…（输出过长已截断：原文 %d 字符，此处保留前 %d 字符。"
                    + "完整内容已保存，续读标记 %s；需要细节时请缩小查询范围后重试）";

    /** 续读标记取不回来时的提示。 */
    private static final String MISSING_NOTE =
            "\n\n…（完整内容已不可用：续读标记 %s 不存在，可能是设置库被清理过）";

    /** 设置注册表。 */
    private final SettingsRegistry settingsRegistry;

    /** 设置行存储：临时内容以 tool-out-* 为键写入 app_settings。 */
    private final SettingRowStore rowStore;

    /** 最近一次截断结果：{(sessionId + "|" + toolName): TruncateResult}。 */
    private final Map<String, TruncateResult> last = new ConcurrentHashMap<>();

    /**
     * 构造器。
     *
     * @param settingsRegistry 设置注册表
     * @param rowStore         设置行存储
     */
    public OutputContract(SettingsRegistry settingsRegistry, SettingRowStore rowStore) {
        this.settingsRegistry = settingsRegistry;
        this.rowStore = rowStore;
    }

    /**
     * 一次工具输出截断的结果。
     *
     * @param output          交给模型/前端的文本（未截断时就是原文）
     * @param totalChars      截断前的原始字符数
     * @param truncated       是否发生了截断
     * @param continuationRef 续读标记；未截断或落盘失败时为 null
     */
    public record TruncateResult(
            // 交给模型的文本
            String output,
            // 原始字符数
            int totalChars,
            // 是否截断
            boolean truncated,
            // 续读标记
            String continuationRef
    ) {
    }

    /**
     * 按当前设置执行截断。
     *
     * <p>任何异常都回落到「不截断」：治理层是保险丝，它自己出问题不该让工具调用失败。</p>
     *
     * @param text      工具原始输出（含 "OK: " / "FAIL: " 前缀）
     * @param toolName  工具名，登记「最近一次截断」用
     * @param sessionId 会话 id，同上
     * @return 截断结果
     */
    public TruncateResult apply(String text, String toolName, String sessionId) {
        boolean enabled = true;
        int maxChars = 8000;
        try {
            enabled = Boolean.TRUE.equals(settingsRegistry.getSetting("context.tool_output_truncate"));
            maxChars = ((Number) settingsRegistry.getSetting("context.max_tool_output_chars")).intValue();
        } catch (RuntimeException e) {
            // 读设置失败：保持默认值（开启 + 8000），治理层不打断业务
        }
        String source = text == null ? "" : text;
        if (!enabled) {
            return new TruncateResult(source, source.length(), false, null);
        }
        return truncate(source, maxChars, sessionId, toolName, true);
    }

    /**
     * 按阈值截断一段文本，并在需要时把完整内容落盘。
     *
     * <p>只保留**前** maxChars 个字符而不是头尾各留一半：工具输出的有效信息基本都在开头，
     * 砍掉尾部对模型判断「这是什么、成不成功」影响最小，也不会破坏 "OK:" / "FAIL:" 前缀。</p>
     *
     * <p>注意：Java 的 String.length() 按 UTF-16 码元计数，与 Python 的字符数在
     * 生僻字/emoji 上会略有差异；截断阈值只用于控制上下文长度，这点差异可以接受。</p>
     *
     * @param text      原始文本
     * @param maxChars  截断阈值（字符数）；<=0 视为不截断
     * @param sessionId 会话 id
     * @param toolName  工具名
     * @param persist   是否把完整内容落盘（测试可传 false）
     * @return 截断结果
     */
    public TruncateResult truncate(String text, int maxChars, String sessionId,
                                   String toolName, boolean persist) {
        String source = text == null ? "" : text;
        int total = source.length();
        if (maxChars <= 0 || total <= maxChars) {
            TruncateResult result = new TruncateResult(source, total, false, null);
            remember(sessionId, toolName, result);
            return result;
        }
        String ref = persist ? storeContinuation(source) : null;
        String note = ref != null
                ? String.format(TRUNCATE_NOTE, total, maxChars, ref)
                : String.format(MISSING_NOTE, ref == null ? "(未生成)" : ref);
        TruncateResult result = new TruncateResult(
                source.substring(0, maxChars) + note, total, true, ref);
        remember(sessionId, toolName, result);
        return result;
    }

    /**
     * 按续读标记取回完整输出。
     *
     * @param ref 续读标记（TruncateResult.continuationRef）
     * @return 完整文本；标记非法、不存在或已被清理时返回 null
     */
    public String readContinuation(String ref) {
        if (ref == null || !ref.startsWith(CONTINUATION_PREFIX)) {
            return null;
        }
        try {
            return rowStore.read(ref)
                    .map(value -> JsonUtils.parse(value, String.class))
                    .orElse(null);
        } catch (RuntimeException e) {
            log.warn("读取续读内容失败：{}", ref, e);
            return null;
        }
    }

    /**
     * 取走某个会话里某个工具「最近一次」的截断结果（取走即删除，避免串到下一轮）。
     *
     * @param sessionId 会话 id
     * @param toolName  工具名
     * @return 截断结果；该工具这轮没跑过时为 null
     */
    public TruncateResult takeLastTruncation(String sessionId, String toolName) {
        return last.remove(key(sessionId, toolName));
    }

    /**
     * 查看（不删除）最近一次截断结果，调试与测试用。
     *
     * @param sessionId 会话 id
     * @param toolName  工具名
     * @return 截断结果或 null
     */
    public TruncateResult peekLastTruncation(String sessionId, String toolName) {
        return last.get(key(sessionId, toolName));
    }

    /**
     * 清空「最近一次截断」登记表（仅测试用）。
     */
    public void resetForTest() {
        last.clear();
    }

    /**
     * 把完整输出写进设置库，返回续读标记；失败时返回 null（调用方照常截断）。
     *
     * @param text 完整输出文本
     * @return 形如 "tool-out-3f2a..." 的续读标记；超限或写库失败时为 null
     */
    private String storeContinuation(String text) {
        if (text.length() > MAX_CONTINUATION_CHARS) {
            log.warn("工具输出过大（{} 字符），跳过落盘续读", text.length());
            return null;
        }
        String ref = CONTINUATION_PREFIX + UUID.randomUUID().toString().replace("-", "");
        try {
            // 以 JSON 字符串存：读回时 JsonUtils.parse 能得到原样的 String
            rowStore.write(ref, JsonUtils.toJson(text));
            return ref;
        } catch (RuntimeException e) {
            // 落盘失败不影响截断本身：模型仍然能拿到前 N 个字符
            log.warn("工具输出落盘失败，本次无法续读", e);
            return null;
        }
    }

    /**
     * 登记「最近一次截断」；sessionId 或 toolName 为空时跳过。
     *
     * @param sessionId 会话 id
     * @param toolName  工具名
     * @param result    截断结果
     */
    private void remember(String sessionId, String toolName, TruncateResult result) {
        if (sessionId != null && !sessionId.isEmpty() && toolName != null && !toolName.isEmpty()) {
            last.put(key(sessionId, toolName), result);
        }
    }

    /**
     * 生成登记表的键。
     *
     * @param sessionId 会话 id
     * @param toolName  工具名
     * @return 键
     */
    private static String key(String sessionId, String toolName) {
        return sessionId + "|" + toolName;
    }
}
