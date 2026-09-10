// 模块说明：内置的全部设置声明（对应 Python 侧 settings_registry.py 的 BUILTIN_DEFS）。
//
// 这些是「产品自带的设置项」：声明一次，就自动拥有默认值、写入校验与设置页渲染能力。
// 新增设置项的唯一做法是在这里加一条声明，不要在业务代码里写 if (key.equals("...")) 兜底。
//
// 为什么没有 workspaces.* 两条：工作区在 Java 侧是独立表（workspace），
// 当前生效 id 也只作为内部键存在，不再属于「可由设置页直接编辑的普通设置」。
package com.example.backendjava.settings;

// 标准库：List 保存全部声明的有序集合
import java.util.List;
// 标准库：Map 表示 json 类型设置的空对象默认值
import java.util.Map;

/**
 * 内置设置声明清单。
 *
 * <p>顺序按设置键字母序排列，便于与 Python 侧逐条对照；注册表内部还会再排一次序。</p>
 */
public final class BuiltinSettings {

    /** 工具类禁止实例化。 */
    private BuiltinSettings() {
    }

    /**
     * 返回内置的全部设置声明。
     *
     * @return 67 条声明（按键名字母序）；调用方不应修改该列表
     */
    public static List<SettingDefinition> definitions() {
        return List.of(
                SettingDefinition.of("agent.max_iterations", SettingKind.INT, 25).label("单轮步数上限").category("agent").min(1).max(50).description("单轮对话的工具迭代上限；模型一次 + 工具一次各算一步").build(),
                SettingDefinition.of("agent.steering_enabled", SettingKind.BOOL, true).label("允许执行中插话").category("agent").description("执行过程中允许用户插话干预下一步").build(),
                SettingDefinition.of("agent.subagent_enabled", SettingKind.BOOL, false).label("启用子 agent").category("agent").description("开启后主对话多一个 dispatch_subagent 工具：把「只需要读」的子任务派给隔离的只读子 agent，主对话只回收结论。子 agent 不能写盘、不能执行命令、不能联网").build(),
                SettingDefinition.of("agent.subagent_max_parallel", SettingKind.INT, 2).label("子 agent 并发上限").category("agent").min(1).max(8).description("同时最多跑几个子 agent；超出的派发会被直接拒绝，让主对话自己串行处理").build(),
                SettingDefinition.of("context.auto_compress", SettingKind.BOOL, true).label("自动压缩上下文").category("context").description("对话过长时是否自动摘要压缩早期消息").build(),
                SettingDefinition.of("context.compress_threshold", SettingKind.FLOAT, 0.7).label("压缩触发比例").category("context").min(0.1).max(0.95).description("上下文占用达到模型窗口该比例时触发压缩").build(),
                SettingDefinition.of("context.keep_recent_n", SettingKind.INT, 10).label("压缩时保留消息数").category("context").min(1).max(100).description("压缩时保留最近多少条消息不参与摘要").build(),
                SettingDefinition.of("context.max_tool_output_chars", SettingKind.INT, 8000).label("工具输出上限（字符）").category("context").min(1000).max(200000).description("单次工具输出的截断阈值（字符数）；超出部分截断并落盘，可续读").build(),
                SettingDefinition.of("context.tool_output_truncate", SettingKind.BOOL, true).label("截断超长输出").category("context").description("是否对超长的工具输出做截断处理").build(),
                SettingDefinition.of("cost.guard_enabled", SettingKind.BOOL, true).label("启用预算熔断").category("cost").since("M5").description("单任务预算熔断总开关：超阈值时在下一次工具调用前暂停并询问继续/停止；关闭后不再拦截（不推荐，等于放弃成本保护）").build(),
                SettingDefinition.of("cost.max_cost_per_task", SettingKind.FLOAT, 5.0).label("单任务费用上限（元）").category("cost").min(0.0).max(1000.0).since("M5").description("单个任务的费用上限（元）；按当前模型单价把 token 折算成金额").build(),
                SettingDefinition.of("cost.max_duration_minutes", SettingKind.INT, 30).label("单任务时长上限（分钟）").category("cost").min(1).max(600).since("M5").description("单个任务的最长时长（分钟）；超时同样在下次工具调用前询问继续/停止").build(),
                SettingDefinition.of("cost.max_tokens_per_task", SettingKind.INT, 500000).label("单任务 token 上限").category("cost").min(1000).max(5000000).since("M5").description("单个任务（一轮用户请求到 done）的 token 上限；取真实 usage 累加值").build(),
                SettingDefinition.of("input.enter_to_send", SettingKind.BOOL, true).label("Enter 直接发送").category("input").since("M2").description("输入框 Enter 直接发送（关闭后 Enter 换行、需 Ctrl/⌘+Enter 发送）；Shift+Enter 始终是换行，中文输入法选词时的 Enter 永远不会误发").build(),
                SettingDefinition.of("llm.base_url", SettingKind.STRING, "").label("接口地址").category("model").description("OpenAI 兼容端点的接口地址；留空表示用供应商官方地址").build(),
                SettingDefinition.of("llm.custom_models", SettingKind.JSON, List.of()).label("自定义模型").category("model").description("自定义模型列表（JSON 数组），用来补充注册表里没有的新模型。每项形如 {\"provider\":\"deepseek\",\"model\":\"deepseek-v9\",\"label\":\"V9\",\"context_window\":1000000,\"supports_tools\":true,\"price_in\":2,\"price_out\":8}；context_window 必填（压缩阈值靠它），缺了该项会被忽略").build(),
                SettingDefinition.of("llm.custom_providers", SettingKind.JSON, List.of()).label("自定义端点").category("model").description("自定义 OpenAI 兼容端点列表（JSON 数组），多个中转站可并存、各自密钥独立。每项形如 {\"id\":\"myapi\",\"label\":\"我的中转\",\"base_url\":\"https://x.example/v1\"}").build(),
                SettingDefinition.of("llm.max_tokens", SettingKind.INT, 0).label("单轮输出上限").category("model").min(0).max(200000).description("单轮生成上限；0 表示不传，用供应商默认值").build(),
                SettingDefinition.of("llm.model", SettingKind.STRING, "deepseek-flash").label("模型名称").category("model").description("API 调用时用的具体模型名，可直接手写任意名字（新模型不必等我们改代码）：内置清单见设置页「模型」下拉，清单里没有的名字会自动登记到「自定义模型」").build(),
                SettingDefinition.of("llm.provider", SettingKind.SELECT, "deepseek").label("模型供应商").category("model").options("deepseek", "openai", "anthropic", "google", "ollama").optionLabels("DeepSeek", "OpenAI", "Anthropic", "Google", "Ollama 本地").description("当前使用的模型供应商；切换后新对话立即生效，无需重启后端").build(),
                SettingDefinition.of("llm.temperature", SettingKind.FLOAT, 0.0).label("随机性（温度）").category("model").min(0.0).max(2.0).description("生成随机性：0 最稳定，越大越发散").build(),
                SettingDefinition.of("mcp.auto_approve_tools", SettingKind.JSON, List.of()).label("免确认的 MCP 工具").category("mcp").since("M4").description("免确认名单（JSON 数组）：写 server 名表示该 server 的全部工具免确认，写 server:tool 只免单个工具。默认全部需要确认").build(),
                SettingDefinition.of("mcp.enabled", SettingKind.BOOL, true).label("启用 MCP").category("mcp").since("M4").description("MCP 总开关：关闭后不再连接任何外部 server，内置工具不受影响").build(),
                SettingDefinition.of("mcp.servers", SettingKind.JSON, List.of()).label("MCP 服务列表").category("mcp").since("M4").description("MCP server 列表（JSON 数组）。每项形如 {\"name\":\"filesystem\",\"transport\":\"stdio\",\"command\":\"npx\",\"args\":[\"-y\",\"@modelcontextprotocol/server-filesystem\",\"D:/work\"]}；远程用 {\"transport\":\"streamable_http\",\"url\":\"https://...\",\"headers\":{...}}").build(),
                SettingDefinition.of("memory.dedup_threshold", SettingKind.FLOAT, 0.85).label("记忆去重阈值").category("memory").min(0.5).max(1.0).since("M4.5").description("相似度超过此值就判为重复、不再保存（默认 0.85 按实际相似度分布校准过）；调高会存下更多近似重复项").build(),
                SettingDefinition.of("memory.embedding_backend", SettingKind.SELECT, "local").label("向量化后端").category("memory").options("local", "remote").optionLabels("本地哈希（快、免费、只认字面）", "远端 embedding（懂语义，需要密钥与网络）").since("M6").description("本地哈希零依赖但不懂语义；远端走 OpenAI 兼容的 /embeddings 接口，失败时自动降级本地").build(),
                SettingDefinition.of("memory.embedding_model", SettingKind.STRING, "text-embedding-3-small").label("远端向量模型").category("memory").since("M6").description("OpenAI 兼容端点的 embedding 模型名（如 text-embedding-3-small / bge-m3）").build(),
                SettingDefinition.of("memory.embedding_provider", SettingKind.STRING, "").label("远端向量化供应商").category("memory").since("M6").description("用哪个已配置的供应商调 embedding（如 openai / custom-xxx）；留空表示当前对话供应商").build(),
                SettingDefinition.of("memory.enabled", SettingKind.BOOL, true).label("工作空间记忆").category("memory").since("M4.5").description("记忆总开关。关闭后不再抽取也不再注入，对话行为与没有这个功能时完全一致").build(),
                SettingDefinition.of("memory.extract_enabled", SettingKind.BOOL, true).label("自动抽取记忆").category("memory").since("M4.5").description("每轮对话结束后自动抽取值得记住的信息（会多花一次模型调用，失败不影响对话）").build(),
                SettingDefinition.of("memory.inject_enabled", SettingKind.BOOL, true).label("新对话注入记忆").category("memory").since("M4.5").description("新对话的第一条消息会把本工作区的相关记忆附给模型（只给模型看，不会出现在回答里）").build(),
                SettingDefinition.of("memory.max_per_workspace", SettingKind.INT, 500).label("单工作区记忆上限").category("memory").min(0).max(5000).since("M6").description("超过上限时按「重要度低、最久没用、最早创建」的顺序清理；0 表示不限制").build(),
                SettingDefinition.of("memory.merge_enabled", SettingKind.BOOL, true).label("合并近似记忆").category("memory").since("M6").description("相似度超过去重阈值时不丢弃，而是合并进已有记忆（保留更完整的正文、重要度取大）；关闭则退回「直接跳过」").build(),
                SettingDefinition.of("memory.min_importance", SettingKind.INT, 1).label("记忆重要度门槛").category("memory").min(1).max(5).since("M4.5").description("检索时只保留重要度不低于此值的记忆；设为 3 以上可以明显减少噪声").build(),
                SettingDefinition.of("memory.top_k", SettingKind.INT, 5).label("注入记忆条数").category("memory").min(1).max(20).since("M4.5").description("每条新对话最多注入几条记忆；调小可以省 token").build(),
                SettingDefinition.of("memory.ttl_days", SettingKind.INT, 180).label("低价值记忆保留天数").category("memory").min(0).max(3650).since("M6").description("重要度 ≤2 且这么久没被检索命中的记忆会被清理；0 表示不按时间淘汰（重要度 3 以上永不因过期删除）").build(),
                SettingDefinition.of("office.enabled", SettingKind.BOOL, true).label("用本地 Office 引擎读文档").category("office").since("M5").description("打开后 .docx/.doc/.xlsx/.xls/.pptx/.ppt 由本地 Office 引擎解析（能读出表格、页、方框）；关闭或不填端口时回落到旧解析器（只读文本，图片与版式会丢）").build(),
                SettingDefinition.of("office.max_cols", SettingKind.INT, 40).label("单个工作表最多读多少列").category("office").min(5).max(200).since("M5").description("作用同 office.max_rows，限制列数；宽表通常只需要前几十列就能判断内容").build(),
                SettingDefinition.of("office.max_rows", SettingKind.INT, 5000).label("单个工作表最多读多少行").category("office").min(100).max(50000).since("M5").description("防止一次把十万行表格读进模型上下文；超出部分截断并标注行号").build(),
                SettingDefinition.of("office.port", SettingKind.INT, 0).label("Office 引擎端口").category("office").min(0).max(65535).since("M5").description("0=自动探测 39099~39108；固定端口时请与桌面壳拉起引擎用的端口一致，否则后端探不到引擎、会一直按降级处理").build(),
                SettingDefinition.of("office.timeout_ms", SettingKind.INT, 15000).label("引擎调用超时").category("office").min(1000).max(120000).since("M5").description("单次引擎调用的超时（毫秒）；超时不会报错，而是返回已经读到的那部分，并在结尾标注截断").build(),
                SettingDefinition.of("ops.auto_update_check", SettingKind.BOOL, true).label("启动时检查更新").category("diagnostic").since("M5").description("桌面版启动后是否自动检查新版本（OPS-4）。桌面壳在启动时读这个开关，改完下一次启动生效；关掉后仍可在「关于」页手动检查").build(),
                SettingDefinition.of("ops.log_level", SettingKind.SELECT, "info").label("日志级别").category("diagnostic").options("debug", "info", "warning", "error").optionLabels("调试", "常规", "警告", "仅错误").since("M5").description("后端日志级别（写入用户数据目录下的 logs/app.log）；排查问题时切到 debug，平时用 info").build(),
                SettingDefinition.of("permission.mode", SettingKind.SELECT, "ask").label("权限模式").category("permission").options("ask", "workspace", "allow").optionLabels("每次询问", "本工作区内免询问", "完全授权").since("M5").description("有风险操作的授权方式：ask=每次询问（默认），workspace=本工作区首次批准后同类操作自动放行，allow=完全授权（硬护栏仍然拦截）").build(),
                SettingDefinition.of("skill.auto_inject", SettingKind.BOOL, true).label("自动提示可用技能").category("skill").since("M4").description("是否把「技能名 + 描述」注入系统提示词让模型自动判断使用；关闭后仍可用 `/技能名` 显式调用").build(),
                SettingDefinition.of("skill.dirs", SettingKind.JSON, List.of()).label("技能目录").category("skill").since("M4").description("额外的技能根目录（JSON 数组，支持 ~ 开头）；默认目录是用户数据目录下的 app-backend/skills").build(),
                SettingDefinition.of("skill.disabled", SettingKind.JSON, List.of()).label("禁用的技能").category("skill").since("M4").description("按名字禁用某些技能（JSON 数组，如 [\"my-skill\"]）；清单里仍会显示，但不会被调用").build(),
                SettingDefinition.of("skill.enabled", SettingKind.BOOL, true).label("启用技能").category("skill").since("M4").description("技能系统总开关：关闭后技能不再注入提示词，`/技能名` 也不会被识别").build(),
                SettingDefinition.of("task.conflict_policy", SettingKind.SELECT, "merge").label("文件冲突处理").category("task").options("merge", "serialize", "block").optionLabels("合并为一个子任务", "串行并逐步校验", "不自动执行").since("M4").description("多个子任务要写同一文件时怎么办：merge=合并成一个子任务（推荐）/ serialize=串行且逐步校验 / block=不自动执行").build(),
                SettingDefinition.of("task.decompose_enabled", SettingKind.BOOL, true).label("自动拆分复杂任务").category("task").since("M4").description("是否把复杂请求自动拆成子任务逐个执行；关闭后所有请求都按单轮处理").build(),
                SettingDefinition.of("task.max_parallel_subtasks", SettingKind.INT, 1).label("同时跑几个子任务").category("task").min(1).max(4).since("M5").description("按'会不会写同一个文件'分成若干车道，车道之间并行、车道内部串行；1=完全串行（默认，最稳），大于 1 时真正并行执行多条车道").build(),
                SettingDefinition.of("task.max_subtasks", SettingKind.INT, 5).label("最多拆几个子任务").category("task").min(2).max(8).since("M4").description("单个任务最多拆成几个子任务；拆得太碎反而更难收敛").build(),
                SettingDefinition.of("task.replan_enabled", SettingKind.BOOL, false).label("允许失败后重新规划").category("task").since("M5").description("某个子任务失败后，让模型重新给出一份完整计划（需要你确认后才执行）；关闭时失败就停在原计划上").build(),
                SettingDefinition.of("task.snapshot_rollback_enabled", SettingKind.BOOL, true).label("失败时回滚文件").category("task").since("M5").description("每个子任务开始前把它声明要改的文件备份到应用数据目录；该子任务失败或校验不通过时按子任务粒度还原，避免半成品留在工作区").build(),
                SettingDefinition.of("task.verify_command", SettingKind.STRING, "").label("校验命令").category("task").since("M4").description("校验命令（在工作区根目录执行，如 pnpm run typecheck）；留空表示不校验").build(),
                SettingDefinition.of("task.verify_loop_enabled", SettingKind.BOOL, true).label("子任务完成后校验").category("task").since("M4").description("子任务完成后是否运行校验命令；校验失败会把报错回补给模型重试一次").build(),
                SettingDefinition.of("task.write_stale_guard", SettingKind.BOOL, true).label("防止覆盖他人修改").category("task").since("M4").description("防丢失更新：读取文件后若磁盘内容被改过，再次写入会被拒绝并要求重新读取").build(),
                SettingDefinition.of("theme.accent", SettingKind.STRING, "#38bdf8").label("主色").category("theme").since("M2").description("主色（十六进制，如 #38bdf8）：按钮、链接、选中态与焦点环都用它").build(),
                SettingDefinition.of("theme.code_theme", SettingKind.SELECT, "auto").label("代码高亮主题").category("theme").options("auto", "github-dark", "github").optionLabels("跟随明暗", "GitHub 深色", "GitHub 浅色").since("M2").description("代码高亮主题：auto=跟随明暗模式，其余为固定主题").build(),
                SettingDefinition.of("theme.custom", SettingKind.JSON, Map.of()).label("自定义配色（高级）").category("theme").since("M2").description("高级：逐项覆盖主题 token（键为 CSS 变量名，如 {\"--color-bg\":\"#0b1120\"}）").build(),
                SettingDefinition.of("theme.font_size", SettingKind.INT, 14).label("正文字号").category("theme").min(12).max(18).since("M2").description("正文字号（像素）；代码块字号会按它自动减 1").build(),
                SettingDefinition.of("theme.mode", SettingKind.SELECT, "dark").label("明暗模式").category("theme").options("dark", "light", "system").optionLabels("深色", "浅色", "跟随系统").since("M2").description("明暗模式：dark=深色，light=浅色，system=跟随系统（滚动条与原生控件同步切换）").build(),
                SettingDefinition.of("theme.preset", SettingKind.SELECT, "slate").label("配色预设").category("theme").options("slate", "midnight", "paper", "nord").optionLabels("蓝灰（默认）", "深蓝", "纸白", "北欧").since("M2").description("配色预设：slate=蓝灰（默认）、midnight=深蓝、paper=纸白、nord=北欧冷淡").build(),
                SettingDefinition.of("theme.radius", SettingKind.INT, 14).label("圆角").category("theme").min(0).max(24).since("M2").description("卡片与气泡圆角（像素，0=直角，14=默认）").build(),
                SettingDefinition.of("tools.allow_web", SettingKind.BOOL, false).label("允许联网").category("tools").description("是否允许 Agent 联网（web_search / web_fetch）；默认关闭").build(),
                SettingDefinition.of("trace.enabled", SettingKind.BOOL, true).label("留存执行轨迹").category("diagnostic").description("是否留存结构化的 Agent 执行轨迹（每轮的工具调用、确认、预算、耗时）。关掉后不产生任何写入；诊断包里的轨迹也会是空的").build(),
                SettingDefinition.of("trace.keep_days", SettingKind.INT, 7).label("轨迹保留天数").category("diagnostic").min(0).max(365).since("M5").description("轨迹保留天数：启动时自动删除更早的记录；0 表示永不清理").build()
        );
    }
}
