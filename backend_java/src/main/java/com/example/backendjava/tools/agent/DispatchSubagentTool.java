// 模块说明：dispatch_subagent 工具（对应 Python subagent_tool.py）。
//
// 解决的问题：主对话跑到一半冒出一个「只要读东西就能回答」的子任务时，
// 派给独立的只读子 agent，主对话只收到结论，避免大量原始文件内容把主上下文顶掉。
//
// 它凭什么安全（三层叠加）：
//   1. 工具层：子 agent 只装配只读工具（由运行时的 ToolRegistry.listForScope(true) 保证）；
//   2. 权限层：SCOPE_SUB 下写盘/执行强制 ASK（见 ToolPolicyRegistry / ToolRuntime）；
//   3. 生命周期层：子 agent 使用独立会话 id 与检查点（由 SubAgentRunner 实现方保证）。
package com.example.backendjava.tools.agent;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolSession; // 项目内：线程本地的会话上下文

// 标准库：List 待校验路径
import java.util.List;
// 标准库：Map 弹窗参数
import java.util.Map;
// 标准库：TimeUnit 超时单位
import java.util.concurrent.TimeUnit;
// 标准库：ExecutorService / Executors 给子 agent 加超时
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
// 标准库：Future 取子 agent 结果
import java.util.concurrent.Future;
// 标准库：TimeoutException 子 agent 超时
import java.util.concurrent.TimeoutException;
// 第三方（Spring）：延迟获取可选 Bean
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：设置注册表——子 agent 开关与并发上限
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 把一个「只要读东西就能回答」的子任务派给隔离的只读子 agent，只回收结论。
 */
@Component
public class DispatchSubagentTool extends AbstractGuardedTool {

    /** 子任务描述的字符上限。 */
    private static final int MAX_TASK_CHARS = 2_000;

    /** 主对话补充背景的字符上限。 */
    private static final int MAX_CONTEXT_CHARS = 4_000;

    /** 单个子 agent 的执行时限（秒）。 */
    private static final long SUB_TIMEOUT_SECONDS = 120L;

    /** 回传给主对话的结论字符上限。 */
    private static final int MAX_ANSWER_CHARS = 4_000;

    /** 当前正在跑的子 agent 个数（受 agent.subagent_max_parallel 约束）。 */
    private static int active;

    /** 保护 active 的锁：工具可能在不同线程（线程池）里同时调用。 */
    private static final Object ACTIVE_LOCK = new Object();

    /** 子 agent 运行器；可能还没有实现 Bean。 */
    private final ObjectProvider<SubAgentRunner> runnerProvider;

    /** 设置注册表：开关与并发上限。 */
    private final SettingsRegistry settingsRegistry;

    /**
     * 构造器。
     *
     * @param runtime          工具执行关卡
     * @param runnerProvider   子 agent 运行器提供者
     * @param settingsRegistry 设置注册表
     */
    public DispatchSubagentTool(ToolRuntime runtime,
                                ObjectProvider<SubAgentRunner> runnerProvider,
                                SettingsRegistry settingsRegistry) {
        super(runtime);
        this.runnerProvider = runnerProvider;
        this.settingsRegistry = settingsRegistry;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "dispatch_subagent";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "把一个只要读东西就能回答的子任务派给隔离的只读子 agent，只回收结论。"
                + "适用：在多个文件/目录里汇总信息、反复检索后给出总结、需要大量试读才敢下判断的调研。"
                + "不适用：需要写文件或跑命令的活儿（子 agent 拿不到写/执行工具）、"
                + "一句话就能答的问题、需要跟用户来回确认的活儿。"
                + "写出结论后请用自己的话向用户复述关键点，不要把子 agent 的原话整段贴出来。";
    }

    /**
     * 构造只读操作（派发本身不改动任何东西）。
     *
     * @param args 工具入参：task / context
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String task = ToolArgs.rawString(args, "task", "").strip();
        String context = ToolArgs.rawString(args, "context", "").strip();
        String target = task.isEmpty()
                ? "(空任务)"
                : (task.length() > 80 ? task.substring(0, 80) : task);
        return new ToolAction(
                name(),
                ToolKind.READ,
                target,
                List.of(),
                Map.of("task", task.length() > 200 ? task.substring(0, 200) : task,
                        "context", context.length() > 80 ? context.substring(0, 80) : context),
                "AI 将派出一个只读子 agent 处理这个子任务，只回收结论"
        );
    }

    /**
     * 执行派发：开关/参数校验 -> 抢占并发槽 -> 带超时运行 -> 截断结论。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 子 agent 的结论
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        if (!enabled()) {
            return ToolResult.fail("子 agent 功能没有开启：请到「设置 → Agent 行为 → 启用子 agent」"
                    + "打开后再试；这一步也可以自己直接用只读工具完成");
        }
        String task = ToolArgs.rawString(args, "task", "").strip();
        if (task.isEmpty()) {
            return ToolResult.fail("子任务描述不能为空：请写清要读哪些地方、回答什么问题");
        }
        if (task.length() > MAX_TASK_CHARS) {
            return ToolResult.fail("子任务描述太长（" + task.length() + " 字，上限 "
                    + MAX_TASK_CHARS + " 字），请精简后再派");
        }
        String rawContext = ToolArgs.rawString(args, "context", "").strip();
        // 截断后放进 final 变量：下面的 lambda 必须捕获「不再变化」的局部变量
        final String context = rawContext.length() > MAX_CONTEXT_CHARS
                ? rawContext.substring(0, MAX_CONTEXT_CHARS)
                : rawContext;

        int maxParallel = maxParallel();
        if (!acquireSlot(maxParallel)) {
            return ToolResult.fail("同时运行的子 agent 已达上限（" + maxParallel + " 个）。"
                    + "请等其中一个结束再派，或者自己用只读工具把这个子任务做掉");
        }
        SubAgentRunner runner = runnerProvider.getIfAvailable();
        if (runner == null) {
            releaseSlot();
            return ToolResult.fail("子 agent 运行器尚未接入（AgentRuntime / SubAgentRunner 未实现），"
                    + "请自己用只读工具完成这个子任务");
        }

        String sessionId = ToolSession.currentSessionId();
        ExecutorService executor = Executors.newSingleThreadExecutor();
        try {
            Future<String> future = executor.submit(() -> runner.run(task, context, sessionId));
            String answer = future.get(SUB_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (answer == null || answer.isBlank()) {
                return ToolResult.fail("子 agent 没有写出任何结论（可能它以为任务已经完成），"
                        + "可以换一种问法再派一次");
            }
            String trimmed = answer.strip();
            if (trimmed.length() > MAX_ANSWER_CHARS) {
                trimmed = trimmed.substring(0, MAX_ANSWER_CHARS)
                        + "\n…（结论超过 " + MAX_ANSWER_CHARS + " 字，已截断）";
            }
            // 刻意不把子 agent 的中间步骤贴出来：主对话要的是结论，过程灌进来就失去了隔离的意义
            return ToolResult.ok("子 agent 的结论（只读调研，未改动任何文件）：\n" + trimmed);
        } catch (TimeoutException e) {
            return ToolResult.fail("子 agent 超过 " + SUB_TIMEOUT_SECONDS + " 秒仍未结束，已中止。"
                    + "请把子任务拆得更小（例如一次只查一个目录），或自己直接做");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return ToolResult.fail("子 agent 执行被中断");
        } catch (Exception e) {
            return ToolResult.fail("子 agent 执行失败：" + e.getMessage());
        } finally {
            executor.shutdownNow();
            releaseSlot();
        }
    }

    /**
     * 子 agent 功能是否开启（设置 agent.subagent_enabled）。
     *
     * @return true 表示允许执行派发
     */
    private boolean enabled() {
        try {
            return Boolean.TRUE.equals(settingsRegistry.getSetting("agent.subagent_enabled"));
        } catch (RuntimeException e) {
            // 读不到设置按关闭处理：子 agent 是额外能力，不该因为读库失败默认开启
            return false;
        }
    }

    /**
     * 读设置 agent.subagent_max_parallel：同时最多几个子 agent。
     *
     * @return 1~8 之间的整数（读不到时按 2）
     */
    private int maxParallel() {
        try {
            int value = ((Number) settingsRegistry.getSetting("agent.subagent_max_parallel")).intValue();
            return Math.max(1, Math.min(8, value));
        } catch (RuntimeException e) {
            return 2;
        }
    }

    /**
     * 抢占一个并发槽位。
     *
     * @param maxParallel 并发上限
     * @return true 表示抢到，可以开跑；false 表示已达上限
     */
    private static boolean acquireSlot(int maxParallel) {
        synchronized (ACTIVE_LOCK) {
            if (active >= maxParallel) {
                return false;
            }
            active++;
            return true;
        }
    }

    /**
     * 归还并发槽位（无论成功、失败、超时都必须调用）。
     */
    private static void releaseSlot() {
        synchronized (ACTIVE_LOCK) {
            active = Math.max(0, active - 1);
        }
    }

    /**
     * 当前正在跑的子 agent 个数（测试与排查用）。
     *
     * @return 活跃数量
     */
    public static int activeCount() {
        synchronized (ACTIVE_LOCK) {
            return active;
        }
    }

    /**
     * 把并发计数器归零（仅测试用）。
     */
    public static void resetForTest() {
        synchronized (ACTIVE_LOCK) {
            active = 0;
        }
    }
}
