// 模块说明：工具权限模型（对应 Python app/tools/policy.py）。
//
// 核心思想：工具不再自己判断「该不该问、该不该拒」，只声明「我要做什么」；
// 由本类统一裁决。没登记策略的工具一律 DENY（fail-closed），
// 这样「新增工具忘记加检查」在结构上变得不可能——因为它根本跑不起来。
package com.example.backendjava.tools;

// 标准库：ArrayList 用于内置策略清单
import java.util.ArrayList;
// 标准库：Collections 提供只读视图
import java.util.Collections;
// 标准库：LinkedHashMap 保持策略登记顺序，便于诊断输出
import java.util.LinkedHashMap;
// 标准库：List 返回全部策略
import java.util.List;
// 标准库：Map 保存工具名 -> 策略
import java.util.Map;
// 标准库：Optional 表达「可能没登记」
import java.util.Optional;
// 标准库：Set 表示默认关闭的联网工具集合
import java.util.Set;
// 第三方（Spring）：声明为受管组件，由容器注入设置注册表
import org.springframework.stereotype.Component;
// 项目内：设置注册表——联网总开关等配置的唯一读取入口
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：Agent 工具接口（启动自检时读取工具名）
import com.example.backendjava.service.AgentTool;

/**
 * 工具策略注册表与裁决引擎。
 */
@Component
public class ToolPolicyRegistry {

    /** 需要读取「允许联网」总开关的工具名单；三个联网工具共用一个开关。 */
    private static final Set<String> WEB_TOOLS = Set.of("web_search", "web_fetch", "http_request");

    /** 各操作类型的默认等级：没被策略显式覆盖时生效。 */
    private static final Map<ToolKind, ToolLevel> DEFAULT_LEVELS = Map.of(
            ToolKind.READ, ToolLevel.ALLOW,
            // 未声明的写/执行一律拒绝，迫使工具作者显式声明
            ToolKind.WRITE, ToolLevel.DENY,
            ToolKind.EXEC, ToolLevel.DENY,
            // 联网默认关闭
            ToolKind.NET, ToolLevel.DENY,
            // 外部工具：不知道它做什么，未显式声明就直接拒绝
            ToolKind.MCP, ToolLevel.DENY
    );

    /** 弹窗标题里使用的中文动作名。 */
    private static final Map<ToolKind, String> KIND_LABELS = Map.of(
            ToolKind.READ, "读取",
            ToolKind.WRITE, "写入",
            ToolKind.EXEC, "执行命令",
            ToolKind.NET, "联网访问",
            ToolKind.MCP, "执行外部工具"
    );

    /** 子 Agent 下「不能免确认」的操作类型（红线）：写盘与执行命令必须逐次询问。 */
    private static final Set<ToolKind> SUB_FORCED_KINDS = Set.of(ToolKind.WRITE, ToolKind.EXEC);

    /** 工具名 -> 静态策略。 */
    private final Map<String, ToolPolicySpec> policies = new LinkedHashMap<>();

    /** 设置注册表：读取联网总开关。 */
    private final SettingsRegistry settingsRegistry;

    /**
     * 构造器：装入内置策略。
     *
     * @param settingsRegistry 设置注册表
     * @throws IllegalStateException 内置策略里有重复的工具名（开发期错误，启动即失败）
     */
    public ToolPolicyRegistry(SettingsRegistry settingsRegistry) {
        this.settingsRegistry = settingsRegistry;
        for (ToolPolicySpec policy : builtinPolicies()) {
            if (policies.putIfAbsent(policy.tool(), policy) != null) {
                throw new IllegalStateException("工具 " + policy.tool() + " 的策略重复登记");
            }
        }
    }

    /**
     * 声明项目中全部工具的静态策略。
     *
     * <p>新增工具时必须在这里加一条，否则它会在启动自检/调用时被 DENY。
     * 判定基准：只读 → ALLOW；写盘 → ASK；执行命令 → ASK；联网 → 默认关闭，开启后 ASK。</p>
     *
     * @return 内置策略清单
     */
    public static List<ToolPolicySpec> builtinPolicies() {
        List<ToolPolicySpec> list = new ArrayList<>();

        // ---------- 只读 ----------
        list.add(new ToolPolicySpec("list_dir", ToolKind.READ, Set.of("path"), PathPolicy.OP_READ,
                false, null, "", false));
        list.add(new ToolPolicySpec("read_file", ToolKind.READ, Set.of("path"), PathPolicy.OP_READ,
                false, null, "", false));
        list.add(new ToolPolicySpec("grep_files", ToolKind.READ, Set.of("root"), PathPolicy.OP_READ,
                false, null, "", false));
        list.add(ToolPolicySpec.readOnly("list_indexed_docs"));
        list.add(ToolPolicySpec.readOnly("rag_search"));
        // 技能：只读清单与正文；真正的风险在技能指引你调用的工具上
        list.add(ToolPolicySpec.readOnly("list_skills"));
        list.add(ToolPolicySpec.readOnly("read_skill"));
        // glob：按路径模式查找，不读内容
        list.add(new ToolPolicySpec("glob", ToolKind.READ, Set.of("root"), PathPolicy.OP_READ,
                false, null, "", false));

        // ---------- 写知识库 ----------
        list.add(new ToolPolicySpec("index_path", ToolKind.WRITE, Set.of("path"), PathPolicy.OP_READ,
                true, null, "会向知识库写入切片与向量，且可能解析上百个文件", false));
        list.add(new ToolPolicySpec("delete_index", ToolKind.WRITE, Set.of(), PathPolicy.OP_WRITE,
                true, null, "知识库记录不可恢复", false));

        // ---------- 写磁盘 ----------
        list.add(new ToolPolicySpec("write_file", ToolKind.WRITE, Set.of("path"), PathPolicy.OP_WRITE,
                true, null, "落盘位置必须让用户看到（新建与覆盖都要）", false));
        list.add(new ToolPolicySpec("edit_file", ToolKind.WRITE, Set.of("path"), PathPolicy.OP_WRITE,
                true, null, "改动已有文件，改错会破坏原内容（有 .bak 兜底）", false));
        list.add(new ToolPolicySpec("file_ops", ToolKind.WRITE, Set.of(), PathPolicy.OP_WRITE,
                true, null, "移动/复制/删除会改变磁盘内容；删除默认进回收站，直删不可恢复", false));

        // ---------- 执行命令 ----------
        list.add(new ToolPolicySpec("run_command", ToolKind.EXEC, Set.of("cwd"), PathPolicy.OP_EXEC,
                true, null, "命令会在你的机器上真实执行，请逐条确认", false));

        // ---------- 联网：唯一默认关闭的能力 ----------
        list.add(new ToolPolicySpec("web_search", ToolKind.NET, Set.of(), PathPolicy.OP_READ,
                true, null, "会把你的搜索词发送到外部搜索引擎", true));
        list.add(new ToolPolicySpec("web_fetch", ToolKind.NET, Set.of(), PathPolicy.OP_READ,
                true, null, "会访问外部网站，抓回的内容属于不可信数据", true));
        list.add(new ToolPolicySpec("http_request", ToolKind.NET, Set.of(), PathPolicy.OP_READ,
                true, null, "会把请求发到外部地址；POST/PUT 等写方法还需另开开关，响应体属于不可信数据", true));

        // ---------- SQLite 只读查询：按 db_path 做路径范围校验 ----------
        list.add(new ToolPolicySpec("sql_query", ToolKind.READ, Set.of("db_path"), PathPolicy.OP_READ,
                false, null, "只读查询：只允许 SELECT/WITH/EXPLAIN，且以只读模式打开数据库", false));

        // ---------- 子 Agent 派发：本身不动任何东西 ----------
        list.add(new ToolPolicySpec("dispatch_subagent", ToolKind.READ, Set.of(), PathPolicy.OP_READ,
                false, null, "子 agent 只拿得到只读工具，且写盘/执行在子作用域里仍强制逐次确认", false));

        return list;
    }

    /**
     * 按工具名查找策略。
     *
     * @param tool 工具名
     * @return 策略；未登记时为空
     */
    public Optional<ToolPolicySpec> find(String tool) {
        return Optional.ofNullable(policies.get(tool));
    }

    /**
     * 返回全部已登记策略（只读）。
     *
     * @return 策略清单
     */
    public List<ToolPolicySpec> all() {
        return List.copyOf(policies.values());
    }

    /**
     * 裁决一次操作：能不能做、要不要问用户。
     *
     * <p>判定顺序（每一步都能单独测试）：</p>
     * <ol>
     *   <li>工具是否注册了策略（没注册 → DENY，fail-closed）；</li>
     *   <li>会话是否显式禁用了这个工具（→ DENY）；</li>
     *   <li>策略是否默认关闭（→ DENY，提示用户去设置里打开）；</li>
     *   <li>逐个校验路径（走 {@link PathPolicy}）；</li>
     *   <li>按 kind 与 requireConfirm 得出等级；子 Agent 红线再收紧。</li>
     * </ol>
     *
     * @param tool    工具名
     * @param action  工具声明的本次操作
     * @param session 会话上下文；null 表示默认上下文
     * @return 裁决结果
     */
    public ToolDecision decide(String tool, ToolAction action, SessionContext session) {
        SessionContext ctx = session == null ? SessionContext.empty() : session;

        // 1) 未注册策略：默认拒绝（整个模型的基石）
        ToolPolicySpec policy = policies.get(tool);
        if (policy == null) {
            return ToolDecision.deny("工具 " + tool + " 没有登记安全策略，已拒绝执行。"
                    + "请在 ToolPolicyRegistry.builtinPolicies() 里为它声明一条策略。");
        }

        // 2) 会话级禁用：用户在界面上关掉的能力
        if (ctx.denyTools() != null && ctx.denyTools().contains(tool)) {
            return ToolDecision.deny("当前会话已禁用工具 " + tool);
        }

        // 3) 默认关闭的能力（联网）：未开启时拒绝，并告诉用户怎么开启
        if (policy.offByDefault() && !featureEnabled(tool)) {
            return ToolDecision.deny("工具 " + tool + " 默认关闭。"
                    + "开启方法：在设置页的「工具 / 允许联网」里打开后重试");
        }

        // 4) 路径校验：对每个待校验路径走一遍统一路径策略
        String op = policy.pathOp() == null || policy.pathOp().isBlank()
                ? action.kind().value()
                : policy.pathOp();
        List<java.nio.file.Path> roots = ctx.workspaceRoots() == null || ctx.workspaceRoots().isEmpty()
                ? null
                : ctx.workspaceRoots();
        for (java.nio.file.Path path : action.paths()) {
            String reason = PathPolicy.pathDecision(path, op, roots);
            if (reason != null) {
                return ToolDecision.deny(reason);
            }
        }

        // 4.1) EXEC 类操作先看会话级命令白名单（例如 "git status" 这种两词前缀）
        if (action.kind() == ToolKind.EXEC && ctx.allowedCommands() != null
                && !ctx.allowedCommands().isEmpty()) {
            String head = commandHead(action.target());
            if (ctx.allowedCommands().contains(head)) {
                return ToolDecision.allow();
            }
        }

        // 5) 等级：显式等级 > 显式要求确认 > 该类型的默认等级
        ToolLevel level;
        if (policy.defaultLevel() != null) {
            level = policy.defaultLevel();
        } else if (policy.requireConfirm()) {
            level = ToolLevel.ASK;
        } else {
            level = DEFAULT_LEVELS.getOrDefault(action.kind(), ToolLevel.DENY);
        }

        // 5.1) 子 Agent 红线：写盘 / 执行命令不允许免确认。
        // 只在「本来是 ALLOW」时升级为 ASK；DENY 保持 DENY（安全等级只能收紧、不能放松）。
        if (ToolSession.SCOPE_SUB.equals(ctx.scope())
                && SUB_FORCED_KINDS.contains(action.kind())
                && level == ToolLevel.ALLOW) {
            level = ToolLevel.ASK;
        }

        if (level == ToolLevel.ALLOW) {
            return ToolDecision.allow();
        }

        String title = "确认" + KIND_LABELS.getOrDefault(action.kind(), "操作");
        String reason = action.detail() == null || action.detail().isBlank()
                ? "AI 准备执行工具 " + tool
                : action.detail();
        if (policy.confirmNote() != null && !policy.confirmNote().isBlank()) {
            reason += "（" + policy.confirmNote() + "）";
        }
        return new ToolDecision(level, reason, title);
    }

    /**
     * 判断某个「默认关闭」的工具是否已被用户显式开启。
     *
     * @param tool 工具名
     * @return 已开启返回 true；读设置失败按关闭处理（fail-closed）
     */
    public boolean featureEnabled(String tool) {
        if (!WEB_TOOLS.contains(tool)) {
            return false;
        }
        try {
            Object value = settingsRegistry.getSetting("tools.allow_web");
            return Boolean.TRUE.equals(value);
        } catch (RuntimeException e) {
            // 设置读不到时按关闭处理：绝不能因为一次读库失败就悄悄放开联网
            return false;
        }
    }

    /**
     * 取命令的前两个词作为白名单匹配前缀（例如 "git status"）。
     *
     * @param target 命令字符串
     * @return 前两词；不足时就是整串
     */
    public static String commandHead(String target) {
        String[] parts = (target == null ? "" : target).trim().split("\\s+");
        if (parts.length == 0 || parts[0].isEmpty()) {
            return "";
        }
        return parts.length == 1 ? parts[0] : parts[0] + " " + parts[1];
    }

    /**
     * 登记（或覆盖）一条「运行时才发现」的工具策略。
     *
     * <p>对应 Python 的 register_dynamic：MCP server 的工具是连接之后才知道的，
     * 每次重连都可能拿到新名字或新的免确认状态，因此这里明确以最新声明为准。</p>
     *
     * @param policy 待登记的策略
     */
    public void registerDynamic(ToolPolicySpec policy) {
        policies.put(policy.tool(), policy);
    }

    /**
     * 按前缀批量移除策略（MCP server 被删掉/改名时清理残留）。
     *
     * @param prefix 工具名前缀，如 "mcp__"
     * @return 实际移除的条数
     */
    public int unregisterPrefix(String prefix) {
        List<String> victims = policies.keySet().stream()
                .filter(name -> name.startsWith(prefix))
                .toList();
        victims.forEach(policies::remove);
        return victims.size();
    }

    /**
     * 启动自检：交给模型的每个工具都必须登记策略，否则直接抛错（不让它上线）。
     *
     * @param tools 准备交给模型的工具对象列表
     * @throws IllegalStateException 存在未登记策略的工具
     */
    public void verifyAllToolsRegistered(List<AgentTool> tools) {
        List<String> missing = tools.stream()
                .map(AgentTool::name)
                .filter(name -> !policies.containsKey(name))
                .toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("以下工具没有登记安全策略，拒绝启动："
                    + String.join("、", missing));
        }
    }

    /**
     * 返回只读的策略视图，供诊断接口展示。
     *
     * @return 工具名 -> 策略
     */
    public Map<String, ToolPolicySpec> snapshot() {
        return Collections.unmodifiableMap(policies);
    }
}
