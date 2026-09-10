// 模块说明：路径操作策略（对应 Python tool_utils.py 的 PATH_RULES / path_decision）。
//
// 为什么做成「声明式规则表」而不是一串 if：
//   工具会越来越多（写文件、改文件、删除、执行命令……），每加一个就抄一遍判断一定会漏。
//   把「哪些目录允许哪些操作」写成数据后，新增工具只要调用 pathDecision 就自动获得全部规则。
package com.example.backendjava.tools;

// 标准库：List 保存规则表与工作区白名单
import java.util.List;
// 标准库：Set 表示某条规则允许的操作集合
import java.util.Set;
// 标准库：Path 表示文件/目录路径
import java.nio.file.Path;
// 标准库：Files 判断代码位置是目录还是 jar
import java.nio.file.Files;

/**
 * 路径操作策略：受保护目录 + 工作区白名单的唯一判定入口。
 *
 * <p>判定顺序（先紧后松）：</p>
 * <ol>
 *   <li>命中受保护目录规则：该规则允许这个操作才放行（例如后端源码只许读）；</li>
 *   <li>未命中规则：若配置了工作区白名单，要求路径落在白名单内；没配置则放行。</li>
 * </ol>
 *
 * <p>系统目录已经在 {@link ToolUtils#resolveAbsPath(String)} 统一拦截，这里不再重复。</p>
 */
public final class PathPolicy {

    /** 允许的操作名：读文件内容、列目录、搜索。 */
    public static final String OP_READ = "read";

    /** 允许的操作名：新建 / 覆盖 / 修改 / 删除 / 移动文件。 */
    public static final String OP_WRITE = "write";

    /** 允许的操作名：以该路径为工作目录或参数去执行命令。 */
    public static final String OP_EXEC = "exec";

    /**
     * 本后端工程根目录：用来禁止 AI 改写后端自身源码。
     *
     * <p>优先用系统属性 {@code app.backend.root} 覆盖；否则从本类的 class 文件位置推断：
     * IDE/Maven 运行时是 {@code backend_java/target/classes}，向上两级就是 backend_java；
     * 打成的 jar 位于 backend 目录，取 jar 所在目录。都推断不出来时退回进程工作目录。</p>
     */
    public static final Path BACKEND_ROOT = detectBackendRoot();

    /**
     * 运行期允许写入/执行的目录白名单；空列表表示「除系统目录与受保护目录外均可写」。
     *
     * <p>由工作区模块在切换到某个工作区时调用 {@link #refreshWorkspaceRoots(List)} 刷新。
     * 用 volatile 保证一个线程切换后，其它工具线程立刻看到新值。</p>
     */
    private static volatile List<Path> workspaceRoots = List.of();

    /** 受保护目录表：按顺序匹配，第一条命中的规则生效，所以更具体的规则要放在前面。 */
    private static final List<PathRule> PATH_RULES = List.of(
            new PathRule(
                    BACKEND_ROOT,
                    Set.of(OP_READ),
                    BACKEND_ROOT + " 是本后端自身的源码目录，允许读取、禁止改写与执行")
    );

    /** 工具类禁止实例化。 */
    private PathPolicy() {
    }

    /**
     * 一条路径策略：某个目录（含其子树）允许做哪些操作。
     *
     * @param root   规则作用的根目录（绝对路径），其下所有子孙都受本规则约束
     * @param allow  允许的操作集合，取值见 OP_READ / OP_WRITE / OP_EXEC
     * @param reason 拒绝时给模型看的原因（要写清「这是什么目录、为什么不能动」）
     */
    public record PathRule(
            // 规则作用的根目录
            Path root,
            // 允许的操作集合
            Set<String> allow,
            // 拒绝原因
            String reason
    ) {
    }

    /**
     * 按当前工作区白名单判断路径能否执行某类操作。
     *
     * @param path 已经过 resolve 的绝对路径
     * @param op   操作类型，取值 OP_READ / OP_WRITE / OP_EXEC
     * @return 允许时返回 null；不允许时返回中文原因（可直接作为 FAIL 文案）
     */
    public static String pathDecision(Path path, String op) {
        return pathDecision(path, op, workspaceRoots);
    }

    /**
     * 用显式传入的白名单判断路径能否执行某类操作（会话级覆盖全局配置时使用）。
     *
     * @param path  已经过 resolve 的绝对路径
     * @param op    操作类型
     * @param roots 本次判定使用的工作区白名单；null 表示使用全局白名单
     * @return 允许时返回 null；不允许时返回中文原因
     */
    public static String pathDecision(Path path, String op, List<Path> roots) {
        // 1) 先看受保护目录：命中后按规则表决定，不受工作区白名单影响
        for (PathRule rule : PATH_RULES) {
            if (ToolUtils.sameOrUnder(path, rule.root())) {
                if (rule.allow().contains(op)) {
                    return null;
                }
                return path + " 位于受保护目录 " + rule.root()
                        + "，禁止 " + op + " 操作（" + rule.reason() + "）";
            }
        }

        // 2) 没命中受保护规则：工作区白名单只约束「有副作用」的操作，读一律放行
        List<Path> effectiveRoots = roots == null ? workspaceRoots : roots;
        if (OP_READ.equals(op) || effectiveRoots.isEmpty()) {
            return null;
        }
        for (Path root : effectiveRoots) {
            if (ToolUtils.sameOrUnder(path, root)) {
                return null;
            }
        }
        String allowed = effectiveRoots.stream().map(Path::toString)
                .reduce((left, right) -> left + "、" + right).orElse("");
        return path + " 不在允许的工作区（" + allowed + "）内，禁止 " + op + " 操作";
    }

    /**
     * 推断后端工程根目录。
     *
     * @return 绝对路径；推断失败时返回进程工作目录
     */
    private static Path detectBackendRoot() {
        String override = System.getProperty("app.backend.root");
        if (override != null && !override.isBlank()) {
            return Path.of(override).toAbsolutePath().normalize();
        }
        try {
            Path location = Path.of(PathPolicy.class.getProtectionDomain()
                    .getCodeSource().getLocation().toURI());
            if (Files.isDirectory(location)
                    && location.getFileName() != null
                    && "classes".equals(location.getFileName().toString())
                    && location.getParent() != null
                    && location.getParent().getParent() != null) {
                // target/classes -> target -> backend_java
                return location.getParent().getParent().toAbsolutePath().normalize();
            }
            if (location.getParent() != null) {
                // jar 文件：取 jar 所在目录（打包后为 backend/）
                return location.getParent().toAbsolutePath().normalize();
            }
        } catch (Exception ignored) {
            // 代码来源不可读（自定义 ClassLoader 等）：走下面的兜底
        }
        return Path.of(System.getProperty("user.dir", ".")).toAbsolutePath().normalize();
    }

    /**
     * 刷新工作区白名单（切换工作区 / 工作区配置变更时调用）。
     *
     * @param roots 新的根目录列表；null 按空列表处理（等价于「不限制」）
     */
    public static void refreshWorkspaceRoots(List<Path> roots) {
        workspaceRoots = roots == null
                ? List.of()
                : roots.stream()
                        .filter(java.util.Objects::nonNull)
                        .map(path -> path.toAbsolutePath().normalize())
                        .toList();
    }

    /**
     * 返回当前工作区白名单的只读快照。
     *
     * @return 白名单；不会为 null
     */
    public static List<Path> workspaceRoots() {
        return workspaceRoots;
    }
}
