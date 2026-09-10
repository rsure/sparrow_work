// 模块说明：单任务预算熔断（对应 Python app/tools/budget.py）。
//
// 「单任务」= 一轮用户请求（从 /chat/stream 到 done），不是整个会话。
// 每完成一次模型调用就累加 token/费用；下一次工具调用前检查是否越线。
// 只拦工具调用，不拦纯文本生成——没有工具的循环烧不了多少钱，拦它反而打断回答。
package com.example.backendjava.tools;

// 标准库：ConcurrentHashMap 保存 session_id -> 预算状态（工具可能在不同线程调用）
import java.util.concurrent.ConcurrentHashMap;
// 标准库：Map 的键值访问
import java.util.Map;
// 标准库：Optional 表达「没有超限」
import java.util.Optional;
// 标准库：Set 记录用户已选择「继续」的维度
import java.util.Set;
// 标准库：HashSet 构造可变的已释放集合
import java.util.HashSet;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：设置注册表——读取熔断开关与三个阈值
import com.example.backendjava.settings.SettingsRegistry;

/**
 * 工具调用前的预算检查与预算状态登记表。
 */
@Component
public class ToolBudgetRegistry {

    /** 兜底默认值：读不到设置时使用（宁可保守也不放任）。 */
    private static final long DEFAULT_MAX_TOKENS = 500_000L;

    /** 兜底默认费用上限（元）。 */
    private static final double DEFAULT_MAX_COST = 5.0;

    /** 兜底默认时长上限（分钟）。 */
    private static final double DEFAULT_MAX_MINUTES = 30.0;

    /** 进程内预算表：session_id -> TurnBudget。 */
    private final Map<String, TurnBudget> budgets = new ConcurrentHashMap<>();

    /** 设置注册表：熔断开关与阈值的唯一来源。 */
    private final SettingsRegistry settingsRegistry;

    /**
     * 构造器。
     *
     * @param settingsRegistry 设置注册表
     */
    public ToolBudgetRegistry(SettingsRegistry settingsRegistry) {
        this.settingsRegistry = settingsRegistry;
    }

    /**
     * 一轮对话的预算状态。
     */
    public static class TurnBudget {

        /** 所属会话 id。 */
        private final String sessionId;

        /** 本轮开始时间（System.nanoTime，单位：纳秒），用于时长维度。 */
        private final long startedAtNanos;

        /** 总开关：false 时完全跳过检查。 */
        private final boolean guardEnabled;

        /** token 上限（input + output）。 */
        private final long maxTokens;

        /** 费用上限（元）。 */
        private final double maxCost;

        /** 时长上限（秒）。 */
        private final double maxSeconds;

        /** 本轮累计输入 token。 */
        private long inputTokens;

        /** 本轮累计输出 token。 */
        private long outputTokens;

        /** 本轮累计费用（元）；单价未知时为 0。 */
        private double cost;

        /** 用户已经选过「继续」的维度，本轮内不再重复拦。 */
        private final Set<String> released = new HashSet<>();

        /** 用户已经选过「停止本轮」：后续工具调用一律直接拒绝，不再弹框。 */
        private volatile boolean blocked;

        /**
         * 构造一轮预算。
         *
         * @param sessionId     会话 id
         * @param guardEnabled  是否启用熔断
         * @param maxTokens     token 上限
         * @param maxCost       费用上限（元）
         * @param maxSeconds    时长上限（秒）
         */
        public TurnBudget(String sessionId, boolean guardEnabled, long maxTokens,
                          double maxCost, double maxSeconds) {
            this.sessionId = sessionId;
            this.startedAtNanos = System.nanoTime();
            this.guardEnabled = guardEnabled;
            this.maxTokens = maxTokens;
            this.maxCost = maxCost;
            this.maxSeconds = maxSeconds;
        }

        /** 返回所属会话 id。 */
        public String sessionId() {
            return sessionId;
        }

        /** 返回本轮累计 token 总数（input + output）。 */
        public long totalTokens() {
            return inputTokens + outputTokens;
        }

        /** 返回本轮累计费用（元）。 */
        public double cost() {
            return cost;
        }

        /** 返回是否已被用户停止。 */
        public boolean isBlocked() {
            return blocked;
        }

        /** 标记本轮已被用户停止。 */
        public void block() {
            this.blocked = true;
        }

        /**
         * 累加一次模型调用的用量与费用。
         *
         * @param input           输入 token 数
         * @param output          输出 token 数
         * @param priceInPerMillion  输入单价（元 / 百万 token）
         * @param priceOutPerMillion 输出单价（元 / 百万 token）
         */
        public synchronized void addUsage(long input, long output,
                                         double priceInPerMillion, double priceOutPerMillion) {
            inputTokens += Math.max(0, input);
            outputTokens += Math.max(0, output);
            // 单价按「元/百万 token」，所以这里除以 1e6
            cost += (input * priceInPerMillion + output * priceOutPerMillion) / 1_000_000.0;
        }

        /**
         * 判断是否越过任一维度阈值（已选择「继续」的维度跳过）。
         *
         * @return 超限信息；都没超时为空
         */
        public synchronized Optional<BudgetHit> exceeded() {
            if (!guardEnabled) {
                return Optional.empty();
            }
            if (!released.contains("tokens") && totalTokens() > maxTokens) {
                return Optional.of(new BudgetHit("tokens", totalTokens(), maxTokens));
            }
            if (!released.contains("cost") && cost > maxCost) {
                return Optional.of(new BudgetHit("cost", round4(cost), maxCost));
            }
            double elapsedSeconds = (System.nanoTime() - startedAtNanos) / 1_000_000_000.0;
            if (!released.contains("duration") && elapsedSeconds > maxSeconds) {
                return Optional.of(new BudgetHit("duration",
                        round2(elapsedSeconds / 60.0), round2(maxSeconds / 60.0)));
            }
            return Optional.empty();
        }

        /**
         * 用户选择「继续」后释放该维度（本轮内不再拦）。
         *
         * @param dimension tokens / cost / duration
         */
        public synchronized void release(String dimension) {
            released.add(dimension);
        }

        /**
         * 保留两位小数，用于分钟数的展示。
         *
         * @param value 原始值
         * @return 四舍五入到两位小数
         */
        private static double round2(double value) {
            return Math.round(value * 100.0) / 100.0;
        }

        /**
         * 保留四位小数，用于费用展示。
         *
         * @param value 原始值
         * @return 四舍五入到四位小数
         */
        private static double round4(double value) {
            return Math.round(value * 10_000.0) / 10_000.0;
        }
    }

    /**
     * 一次预算超限的描述。
     *
     * @param dimension 维度：tokens / cost / duration
     * @param current   当前值
     * @param limit     阈值
     */
    public record BudgetHit(
            // 超限维度
            String dimension,
            // 当前值
            double current,
            // 阈值
            double limit
    ) {
    }

    /**
     * 开启一轮的预算计时（Agent 运行时在每轮开始时调用）。
     *
     * @param sessionId 会话 id
     * @return 新建的 TurnBudget（同时登记到进程内表）
     */
    public TurnBudget startBudget(String sessionId) {
        boolean enabled = true;
        long maxTokens = DEFAULT_MAX_TOKENS;
        double maxCost = DEFAULT_MAX_COST;
        double maxMinutes = DEFAULT_MAX_MINUTES;
        try {
            enabled = Boolean.TRUE.equals(settingsRegistry.getSetting("cost.guard_enabled"));
            maxTokens = ((Number) settingsRegistry.getSetting("cost.max_tokens_per_task")).longValue();
            maxCost = ((Number) settingsRegistry.getSetting("cost.max_cost_per_task")).doubleValue();
            maxMinutes = ((Number) settingsRegistry.getSetting("cost.max_duration_minutes")).doubleValue();
        } catch (RuntimeException e) {
            // 读设置失败：用保守默认值继续，绝不因为配置读失败而放弃成本保护
        }
        TurnBudget budget = new TurnBudget(sessionId, enabled, maxTokens, maxCost, maxMinutes * 60.0);
        budgets.put(sessionId, budget);
        return budget;
    }

    /**
     * 取某会话当前这一轮的预算状态。
     *
     * @param sessionId 会话 id
     * @return 预算；没有活跃预算时为空
     */
    public Optional<TurnBudget> getBudget(String sessionId) {
        if (sessionId == null || sessionId.isEmpty()) {
            return Optional.empty();
        }
        return Optional.ofNullable(budgets.get(sessionId));
    }

    /**
     * 把一次模型调用的用量记进本轮预算（没有活跃预算时静默忽略）。
     *
     * @param sessionId 会话 id
     * @param inputTokens 输入 token
     * @param outputTokens 输出 token
     * @param priceIn 输入单价（元/百万 token）
     * @param priceOut 输出单价（元/百万 token）
     */
    public void addUsage(String sessionId, long inputTokens, long outputTokens,
                         double priceIn, double priceOut) {
        getBudget(sessionId).ifPresent(budget ->
                budget.addUsage(inputTokens, outputTokens, priceIn, priceOut));
    }

    /**
     * 清掉某会话的预算状态（会话被删除 / 新建对话时调用）。
     *
     * @param sessionId 会话 id
     */
    public void clearBudget(String sessionId) {
        if (sessionId != null) {
            budgets.remove(sessionId);
        }
    }

    /**
     * 清空全部预算状态（仅测试用：用例之间必须隔离）。
     */
    public void resetForTest() {
        budgets.clear();
    }
}
