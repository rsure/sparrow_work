// 模块说明：run_command 工具（对应 Python run_command_tool.py）。
//
// 这是风险最高的工具，安全靠四道闸：
//   1. 命令允许列表（fail-closed）：只放行 COMMAND_RULES 里登记的可执行文件与子命令；
//   2. 参数数组 + 不经过 shell：命令与参数分开传，杜绝 ; && | 注入；
//   3. 工作目录囚笼：cwd 必须落在允许的工作区内，且必须由模型显式给出；
//   4. 每次调用都要用户确认（由 AbstractGuardedTool / ToolRuntime 统一弹窗）+ 超时 + 输出截断。
package com.example.backendjava.tools.exec;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.PathPolicy; // 项目内：路径操作策略（受保护目录 / 工作区白名单）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：ArrayList 组装命令数组与输出块
import java.util.ArrayList;
// 标准库：List 参数数组
import java.util.List;
// 标准库：Map 允许列表与弹窗参数
import java.util.Map;
// 标准库：Set 子命令集合
import java.util.Set;
// 标准库：Locale 大小写转换
import java.util.Locale;
// 标准库：Path 解析工作目录
import java.nio.file.Path;
// 标准库：Files 判断目录
import java.nio.file.Files;
// 标准库：IOException 启动/读取输出失败
import java.io.IOException;
// 标准库：InputStream 读取进程输出
import java.io.InputStream;
// 标准库：StandardCharsets 按 UTF-8 解码输出
import java.nio.charset.StandardCharsets;
// 标准库：TimeUnit 等待命令结束
import java.util.concurrent.TimeUnit;
// 标准库：CompletableFuture 并发读取 stdout/stderr，避免缓冲区满导致死锁
import java.util.concurrent.CompletableFuture;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：参数声明的领域类型（字段名 / 类型 / 说明 / 是否必填），模型据此知道该传哪些键
import com.example.backendjava.service.ToolParameter;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 在本机执行一条已获授权的命令，并返回退出码与输出。
 */
@Component
public class RunCommandTool extends AbstractGuardedTool {

    /** 单次命令默认最长执行时间（秒）。 */
    private static final int TIMEOUT_SECONDS = 60;

    /** 超时硬上限（秒）：模型传再大也不超过它。 */
    private static final int MAX_TIMEOUT_SECONDS = 300;

    /** stdout / stderr 各自最多回传多少字符。 */
    private static final int MAX_OUTPUT_CHARS = 20_000;

    /**
     * 命令允许列表：{可执行文件名(小写, 不带路径) : 允许的子命令集合}。
     *
     * <p>空集合表示「这个程序任何参数都放行」，只给本身无破坏性、且参数必须由模型自由决定的
     * 程序用（如 where 后面要跟要查的文件名）。
     * 集合里的元素是该程序的第一个参数；不在集合里 → 拒绝。</p>
     *
     * <p>登记之前先确认它**真的是一个可执行文件**：进程由 ProcessBuilder 直接启动、
     * 刻意不经过 shell，所以 cmd / PowerShell 的内建命令（echo、dir 这类）根本没有对应的 exe，
     * 放行它们只会让模型拿到「找不到可执行文件」，白白浪费一轮。</p>
     */
    private static final Map<String, Set<String>> COMMAND_RULES = Map.of(
            // 只读的版本控制查询：允许看，不允许 commit / push / reset / clean
            "git", Set.of("status", "diff", "log", "show", "grep", "ls-files",
                    "rev-parse", "branch", "describe"),
            // 类型检查与测试：本项目的自检命令
            "pnpm", Set.of("typecheck", "test:backend", "run", "exec", "-v", "--version"),
            "npm", Set.of("run", "-v", "--version"),
            // Python 侧：只允许「通过 uv run 运行项目内的命令行」与同步依赖，不允许 -c 直接执行代码。
            // 注意：pytest 通常没装成全局命令，跑测试请用 uv run pytest，不要单独登记 pytest
            "uv", Set.of("run", "sync", "--version", "pip"),
            // 纯信息类：无副作用
            "where", Set.of(),
            "node", Set.of("-v", "--version")
    );

    /** 明确禁止的参数：即使可执行文件在允许列表内，命中这些参数也一律拒绝。 */
    private static final Set<String> FORBIDDEN_ARGS = Set.of(
            "-c", "--command", "-e", "--eval",        // 直接执行代码片段
            "-rf", "-fr", "--force", "--hard",        // 强制 / 递归强制
            "-delete", "-exec",                       // find 的删除与执行
            "/c", "/k", "cmd", "powershell", "pwsh",  // 借壳绕过
            "sh", "bash"                              // 同上（非 Windows）
    );

    /**
     * 参数声明单例：模型看到的字段清单，字段名必须与 {@code buildAction} 里读取的键名
     * （command / command_args / cwd / timeout / purpose）逐字一致。只在类加载时构建一次。
     *
     * <p>为什么三个字段是必填：允许列表里每个程序都至少要带一个参数（子命令、{@code --version}、
     * 要查的文件名），漏掉 command_args 时工具只能报错重来。把它标成必填，模型第一轮就会带上；
     * 万一还是漏了，{@link #checkCommand} 的报错也会点名这个参数。</p>
     */
    private static final List<ToolParameter> PARAMETERS = List.of(
            // 允许列表要写进字段说明：模型看得到，就不会去试 powershell / node xxx.js
            new ToolParameter("command", ToolParameter.Kind.STRING,
                    "可执行文件名，必须在允许列表内：git / pnpm / npm / uv / where / node", true),
            new ToolParameter("command_args", ToolParameter.Kind.STRING_ARRAY,
                    "命令参数数组，一个参数一个元素，不要拼成一整串。"
                            + "第一个元素是子命令，例如 [\"run\", \"test:backend\"]、[\"--version\"]、"
                            + "[\"status\", \"--short\"]", true),
            new ToolParameter("cwd", ToolParameter.Kind.STRING,
                    "工作目录的绝对路径（不接受相对路径），必须位于允许的工作区内", true),
            new ToolParameter("timeout", ToolParameter.Kind.INTEGER,
                    "超时秒数，默认 60，最大 300", false),
            new ToolParameter("purpose", ToolParameter.Kind.STRING,
                    "一句话说明这条命令要做什么，会显示在用户确认弹窗里", false)
    );

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public RunCommandTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "run_command";
    }

    /**
     * 参数声明：覆盖接口默认的「不声明」，返回本工具真正读取的五个字段。
     *
     * <p>这份声明是「工具契约」的一部分：模型看到的调用格式由它生成。字段名与
     * {@link ToolArgs} 读取时用的键名不一致，模型传对了也会被当成「没传」——
     * 线上就是在这里丢的参数名，所以改动时两边要一起看。</p>
     *
     * @return 参数字段列表（不可变，可安全复用）
     */
    @Override
    public List<ToolParameter> parameters() {
        return PARAMETERS;
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "在本机执行一条已获授权的命令，并返回退出码与输出（用于跑测试、跑类型检查、跑脚本）。"
                + "参数：command（可执行文件名）、command_args（字符串数组，一个参数一个元素，第一个是子命令）、"
                + "cwd（工作目录绝对路径）、timeout（可选，秒）、purpose（可选，一句话目的）。"
                + "示例：command=pnpm, command_args=[\"run\", \"test:backend\"], cwd=D:\\\\path\\\\to\\\\repo。"
                + "适用：帮我跑一下测试、看看类型检查有没有过、跑个脚本统计一下。"
                + "不适用：需要交互输入的命令、长时间运行的服务、需要联网下载的命令。"
                + "命令必须来自允许列表（git/pnpm/npm/uv/where/node），且只放行其中点名的那几个子命令；"
                + "注意 pnpm run / uv run 会执行仓库里的脚本，所以每次调用仍会弹确认框。"
                + "执行前系统会请用户确认，用户拒绝则返回 FAIL。";
    }

    /**
     * 把参数翻译成一次待裁决的执行操作。
     *
     * @param args 工具入参：command / command_args / cwd / timeout / purpose
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String command = ToolArgs.requiredString(args, "command");
        List<String> commandArgs = ToolArgs.stringList(args, "command_args");
        String cwd = ToolArgs.requiredString(args, "cwd");
        String purpose = ToolArgs.optionalString(args, "purpose", "");
        int timeout = ToolArgs.optionalInt(args, "timeout", TIMEOUT_SECONDS);

        String reason = checkCommand(command, commandArgs);
        if (reason != null) {
            throw new IllegalArgumentException(reason);
        }
        Path workdir = resolveCwd(cwd);
        String shown = command + (commandArgs.isEmpty() ? "" : " " + String.join(" ", commandArgs));
        String detail = "AI 将在 " + workdir + " 执行命令：" + shown;
        if (!purpose.isBlank()) {
            detail += "\n目的：" + purpose;
        }
        return new ToolAction(
                name(),
                ToolKind.EXEC,
                shown,
                List.of(workdir),
                Map.of("command", shown, "cwd", workdir.toString(), "timeout", timeout),
                detail
        );
    }

    /**
     * 执行命令并回收结果；超时或启动失败都返回失败而不是抛异常。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 退出码 + 输出
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        String command = ToolArgs.requiredString(args, "command");
        List<String> commandArgs = ToolArgs.stringList(args, "command_args");
        String purpose = ToolArgs.optionalString(args, "purpose", "");
        // 上限裁剪：模型给再大也不超过 MAX_TIMEOUT_SECONDS，且不小于 1
        int timeout = Math.max(1, Math.min(
                ToolArgs.optionalInt(args, "timeout", TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS));
        try {
            Path workdir = resolveCwd(ToolArgs.requiredString(args, "cwd"));
            List<String> argv = new ArrayList<>();
            argv.add(command);
            argv.addAll(commandArgs);
            ProcessBuilder builder = new ProcessBuilder(argv);
            builder.directory(workdir.toFile());
            // 不经过 shell：参数里的 ; && | > 都只是普通字符，不会被当成命令分隔符
            builder.redirectErrorStream(false);
            Process process = builder.start();

            // 必须并发读取两个流：进程输出超过管道缓冲区时，不读会让它一直阻塞
            CompletableFuture<String> stdout = CompletableFuture.supplyAsync(
                    () -> readStream(process.getInputStream()));
            CompletableFuture<String> stderr = CompletableFuture.supplyAsync(
                    () -> readStream(process.getErrorStream()));

            boolean finished = process.waitFor(timeout, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return ToolResult.fail("命令执行超时（超过 " + timeout + " 秒），已终止");
            }
            int exitCode = process.exitValue();
            String out = stdout.join();
            String err = stderr.join();

            List<String> body = new ArrayList<>();
            if (!out.isBlank()) {
                body.add("[stdout]\n" + clip(out.stripTrailing()));
            }
            if (!err.isBlank()) {
                body.add("[stderr]\n" + clip(err.stripTrailing()));
            }
            if (body.isEmpty()) {
                body.add("(命令没有任何输出)");
            }
            String head = "退出码 " + exitCode + "，工作目录 " + workdir
                    + "，执行 " + String.join(" ", argv);
            String message = head + "\n" + String.join("\n", body);
            if (!purpose.isBlank()) {
                message = "目的：" + purpose + "\n" + message;
            }
            return exitCode == 0 ? ToolResult.ok(message) : ToolResult.fail(message);
        } catch (InterruptedException e) {
            // 恢复中断标记，让上层能感知任务被取消
            Thread.currentThread().interrupt();
            return ToolResult.fail("命令执行被中断");
        } catch (IOException e) {
            return ToolResult.fail("找不到可执行文件或无法启动命令: " + e.getMessage()
                    + "（请检查是否已安装并在 PATH 中）");
        } catch (RuntimeException e) {
            return ToolResult.fail("执行失败: " + e.getMessage());
        }
    }

    /**
     * 校验一条命令是否在允许列表内，并检查禁用参数。
     *
     * @param command 可执行文件名（允许带 .exe 后缀）
     * @param args    参数数组（保持模型给的顺序）
     * @return 允许时返回 null；不允许时返回原因
     */
    public static String checkCommand(String command, List<String> args) {
        String name = Path.of(command).getFileName().toString().toLowerCase(Locale.ROOT);
        if (name.endsWith(".exe")) {
            name = name.substring(0, name.length() - 4);
        }
        Set<String> allowedSub = COMMAND_RULES.get(name);
        if (allowedSub == null) {
            String known = String.join("、", COMMAND_RULES.keySet().stream().sorted().toList());
            return "命令 " + command + " 不在允许列表内（当前允许：" + known + "）";
        }
        // 禁用参数：任何位置出现都拒绝（python -c 这类等于任意代码执行）
        for (String arg : args) {
            if (FORBIDDEN_ARGS.contains(arg.toLowerCase(Locale.ROOT))) {
                return "参数 " + arg + " 被禁止（它等价于直接执行任意代码或强制破坏性操作）";
            }
        }
        if (!allowedSub.isEmpty()) {
            // 允许的子命令排一次序：下面的报错文案复用同一份，避免再排一次
            List<String> sortedAllowed = allowedSub.stream().sorted().toList();
            String allowedText = String.join("、", sortedAllowed);
            if (args.isEmpty()) {
                // 必须点名 command_args：否则模型以为是自己「子命令传错」，会继续换参数名重试
                return "参数 command_args 不能为空：命令 " + name + " 必须给出子命令（允许："
                        + allowedText + "），例如 command_args=[\"" + sortedAllowed.get(0) + "\"]";
            }
            String first = args.get(0).toLowerCase(Locale.ROOT);
            if (!allowedSub.contains(first)) {
                return name + " 的子命令 " + args.get(0) + " 不在允许列表内（command_args 的第一个元素就是子命令，允许："
                        + allowedText + "）";
            }
        }
        return null;
    }

    /**
     * 把模型给的 cwd 解析成绝对路径，并确认它落在允许的工作区内。
     *
     * @param raw 模型给的工作目录（必须是绝对路径）
     * @return 已 resolve 的绝对路径
     * @throws IllegalArgumentException 路径为空、不是绝对路径、不存在、不是目录或越界
     */
    static Path resolveCwd(String raw) {
        Path path = ToolUtils.resolveAbsPath(raw);
        if (!Files.isDirectory(path)) {
            throw new IllegalArgumentException("工作目录不存在或不是目录: " + path);
        }
        List<Path> roots = PathPolicy.workspaceRoots();
        if (roots.isEmpty()) {
            // 没配置工作区时退回「本仓库根目录」：与 Python 侧 Path(__file__).parents[3] 对齐
            Path parent = PathPolicy.BACKEND_ROOT.getParent();
            roots = List.of(parent == null ? PathPolicy.BACKEND_ROOT : parent);
        }
        boolean allowed = roots.stream().anyMatch(root -> ToolUtils.sameOrUnder(path, root));
        if (!allowed) {
            String allowedText = roots.stream().map(Path::toString)
                    .reduce((left, right) -> left + "、" + right).orElse("");
            throw new IllegalArgumentException("工作目录 " + path
                    + " 不在允许的工作区内（" + allowedText + "）");
        }
        return path;
    }

    /**
     * 读取进程输出流并按 UTF-8 解码；非法字节替换为 �，避免 Windows GBK 控制台炸掉。
     *
     * @param stream 进程输出流
     * @return 解码后的文本
     */
    private static String readStream(InputStream stream) {
        try {
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "[读取输出失败: " + e.getMessage() + "]";
        }
    }

    /**
     * 截断过长输出，并在末尾标明被截掉多少字符。
     *
     * @param text 原始输出
     * @return 截断后的文本
     */
    private static String clip(String text) {
        if (text.length() <= MAX_OUTPUT_CHARS) {
            return text;
        }
        return text.substring(0, MAX_OUTPUT_CHARS)
                + "\n…[输出被截断，共 " + text.length() + " 字符，只保留前 " + MAX_OUTPUT_CHARS + " 字符]";
    }
}
