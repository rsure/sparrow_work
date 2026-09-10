// 模块说明：一轮对话的「记事本」——把散落各处的数据攒成 done 事件需要的样子。
//
// 为什么单独一个类：done 事件要 9 个字段，来源五花八门（模型回调、工具执行、计时器、用量）。
// 如果都写在 ChatServiceImpl 里，那个方法会变成 300 行；拆出来之后每个来源只调一个 add 方法。
package com.example.backendjava.chat.runtime;

// 标准库：集合与并发计数
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

// 本项目：工具轨迹类型（done 与历史消息共用）
import com.example.backendjava.dto.ChatDtos.ToolCallTrace;

/**
 * 单轮统计记录器。
 *
 * <p>非线程安全的情况下也用 synchronized：模型回调线程与工具线程可能同时写。</p>
 */
public class TurnRecorder {

    /** 本轮开始时间（毫秒，System.currentTimeMillis）。 */
    private final long startedAt = System.currentTimeMillis();

    /** 已产出的答案文本。 */
    private final StringBuilder answer = new StringBuilder();

    /** 工具调用轨迹。 */
    private final List<ToolCallTrace> toolCalls = new ArrayList<>();

    /** 本轮涉及的文件（用 Set 去重，保留出现顺序）。 */
    private final Set<String> files = new LinkedHashSet<>();

    /** 注入的插话条数。 */
    private int steerCount;

    /** 模型用量。 */
    private Map<String, Object> usage = Map.of();

    /** 实际使用的模型名。 */
    private String model = "";

    /** 本轮是否被用户停止。 */
    private boolean stopped;

    /**
     * 追加模型增量文本。
     *
     * @param text 增量文本
     */
    public synchronized void appendAnswer(String text) {
        answer.append(text);
    }

    /**
     * 记录一次工具调用。
     *
     * @param name   工具名
     * @param input  入参
     * @param output 输出
     */
    public synchronized void addToolCall(String name, Map<String, Object> input, String output) {
        toolCalls.add(new ToolCallTrace(name, input, output, null));
    }

    /**
     * 记录一个涉及的文件路径。
     *
     * @param path 文件绝对路径
     */
    public synchronized void addFile(String path) {
        if (path != null && !path.isBlank()) {
            files.add(path);
        }
    }

    /**
     * 记录用量。
     *
     * @param usage 用量字段：input_tokens / output_tokens / total_tokens / cost
     */
    public synchronized void setUsage(Map<String, Object> usage) {
        this.usage = usage == null ? Map.of() : usage;
    }

    /**
     * 记录模型名。
     *
     * @param model 模型名
     */
    public synchronized void setModel(String model) {
        this.model = model == null ? "" : model;
    }

    /**
     * 标记本轮被停止。
     */
    public synchronized void markStopped() {
        this.stopped = true;
    }

    /**
     * 插话计数加一。
     */
    public synchronized void incSteer() {
        this.steerCount++;
    }

    /**
     * 读取已产出的答案。
     *
     * @return 答案文本
     */
    public synchronized String answer() {
        return answer.toString();
    }

    /**
     * 读取工具轨迹的只读副本。
     *
     * @return 轨迹列表
     */
    public synchronized List<ToolCallTrace> toolCalls() {
        return List.copyOf(toolCalls);
    }

    /**
     * 读取涉及文件。
     *
     * @return 文件路径列表
     */
    public synchronized List<String> files() {
        return List.copyOf(files);
    }

    /**
     * 读取用量。
     *
     * @return 用量 Map
     */
    public synchronized Map<String, Object> usage() {
        return usage;
    }

    /**
     * 读取模型名。
     *
     * @return 模型名
     */
    public String model() {
        return model;
    }

    /**
     * 读取插话条数。
     *
     * @return 条数
     */
    public int steerCount() {
        return steerCount;
    }

    /**
     * 是否已被停止。
     *
     * @return true 表示用户点了停止
     */
    public boolean isStopped() {
        return stopped;
    }

    /**
     * 本轮已耗时。
     *
     * @return 毫秒数
     */
    public long elapsedMs() {
        return System.currentTimeMillis() - startedAt;
    }
}