// 模块说明：file_ops 工具（对应 Python file_ops_tool.py）。
//
// 为什么是「一个工具带多个 item」而不是四个工具：
//   移动/复制/删除的参数形状完全一样（源 + 目标），拆成四个会让提示词变长、模型更容易选错。
//   真正需要分开的是语义（是否可逆、是否需要 overwrite），用 op 字段表达即可。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.PathLock; // 项目内：按文件路径的互斥锁
import com.example.backendjava.tools.PathPolicy; // 项目内：路径操作策略（受保护目录 / 工作区白名单）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：Desktop 调用系统回收站（Java 9+ 的 moveToTrash）
import java.awt.Desktop;
// 标准库：IOException 文件系统异常
import java.io.IOException;
// 标准库：Files 移动/复制/删除/遍历
import java.nio.file.Files;
// 标准库：Path 源与目标路径
import java.nio.file.Path;
// 标准库：StandardCopyOption 复制元数据
import java.nio.file.StandardCopyOption;
// 标准库：ArrayList 保存计划与结果
import java.util.ArrayList;
// 标准库：Comparator 删除时从深到浅
import java.util.Comparator;
// 标准库：List 条目与路径
import java.util.List;
// 标准库：Map 弹窗参数
import java.util.Map;
// 标准库：Set 合法 op
import java.util.Set;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 文件管理：移动、复制、删除、新建目录。
 */
@Component
public class FileOpsTool extends AbstractGuardedTool {

    /** 操作名：移动。 */
    private static final String OP_MOVE = "move";

    /** 操作名：复制。 */
    private static final String OP_COPY = "copy";

    /** 操作名：删除。 */
    private static final String OP_DELETE = "delete";

    /** 合法操作集合，用于参数校验。 */
    private static final Set<String> VALID_OPS = Set.of(OP_MOVE, OP_COPY, OP_DELETE);

    /** 单次调用最多允许的条目数，防止模型一次「整理」几千个文件把确认弹窗撑爆。 */
    private static final int MAX_ITEMS = 200;

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public FileOpsTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "file_ops";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "对文件/文件夹做移动、复制或删除，支持一次处理多个条目（一次确认）。"
                + "适用：把 D:\\草稿 里的 md 移到 D:\\归档、复制一份做备份、删掉临时文件。"
                + "删除默认送系统回收站（可还原）；确实要彻底删除时传 permanent=true（会明确警告）。"
                + "目标已存在时默认拒绝，传 overwrite=true 才覆盖。只改名字/位置不会改动文件内容。";
    }

    /**
     * 把参数翻译成一次待裁决的写操作（预检失败会抛异常，由基类转成 FAIL）。
     *
     * @param args 工具入参：op / items / overwrite / permanent
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String op = ToolArgs.requiredString(args, "op").toLowerCase(java.util.Locale.ROOT);
        List<Map<String, Object>> items = ToolArgs.mapList(args, "items");
        boolean overwrite = ToolArgs.optionalBool(args, "overwrite", false);
        boolean permanent = ToolArgs.optionalBool(args, "permanent", false);

        if (!VALID_OPS.contains(op)) {
            throw new IllegalArgumentException("op 只能是 move/copy/delete，收到 " + op);
        }
        if (items.isEmpty()) {
            throw new IllegalArgumentException("items 为空");
        }
        if (items.size() > MAX_ITEMS) {
            throw new IllegalArgumentException("单次最多处理 " + MAX_ITEMS + " 个条目，收到 " + items.size());
        }

        List<String> plans = new ArrayList<>();
        List<Path> paths = new ArrayList<>();
        for (Map<String, Object> item : items) {
            Path src = ToolUtils.resolveAbsPath(String.valueOf(item.getOrDefault("src", "")));
            Object dstRaw = item.get("dst");
            Path dst = dstRaw == null || String.valueOf(dstRaw).isBlank()
                    ? null
                    : ToolUtils.resolveAbsPath(String.valueOf(dstRaw));
            plans.add(planOne(op, src, dst, overwrite, permanent));
            paths.add(src);
            if (dst != null) {
                paths.add(dst);
            }
        }
        return new ToolAction(
                name(),
                ToolKind.WRITE,
                op + " " + plans.size() + " 项",
                paths,
                Map.of("op", op, "plan", String.join("\n", plans)),
                "AI 将执行 " + plans.size() + " 项文件操作（" + op + "）：\n" + String.join("\n", plans)
        );
    }

    /**
     * 对单个动作做只读预检，返回给弹窗看的一句说明；错误通过抛异常表达。
     *
     * @param op         move / copy / delete
     * @param src        源路径（已 resolve）
     * @param dst        目标路径（move/copy 必填）
     * @param overwrite  目标已存在时是否允许覆盖
     * @param permanent  仅 delete 有效；true=直接删除
     * @return 描述本次动作的一句话
     */
    private static String planOne(String op, Path src, Path dst,
                                  boolean overwrite, boolean permanent) {
        if (!Files.exists(src)) {
            throw new IllegalArgumentException("源不存在: " + src);
        }
        String reason = PathPolicy.pathDecision(src, PathPolicy.OP_WRITE);
        if (reason != null) {
            throw new IllegalArgumentException(reason);
        }
        if (OP_DELETE.equals(op)) {
            // 删除的说明必须写清「能不能恢复」——用户就是靠这句话决定要不要点同意
            return "删除 " + src + " —— " + deleteHow(permanent);
        }
        if (dst == null) {
            throw new IllegalArgumentException(op + " 必须给出目标路径");
        }
        String dstReason = PathPolicy.pathDecision(dst, PathPolicy.OP_WRITE);
        if (dstReason != null) {
            throw new IllegalArgumentException(dstReason);
        }
        if (ToolUtils.sameOrUnder(dst, src)) {
            throw new IllegalArgumentException("目标 " + dst + " 位于源 " + src
                    + " 之内，这会造成自我覆盖/无限嵌套，已拒绝");
        }
        if (Files.exists(dst)) {
            if (!overwrite) {
                throw new IllegalArgumentException("目标已存在: " + dst
                        + "。要覆盖请传 overwrite=true；想保留请换一个目标名");
            }
            return "用 " + src + " 覆盖 " + dst;
        }
        return (OP_MOVE.equals(op) ? "移动" : "复制") + " " + src + " → " + dst;
    }

    /**
     * 执行文件操作：逐项加锁执行，单项失败不影响其余项。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 各项执行结果汇总
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        String op = ToolArgs.requiredString(args, "op").toLowerCase(java.util.Locale.ROOT);
        List<Map<String, Object>> items = ToolArgs.mapList(args, "items");
        boolean overwrite = ToolArgs.optionalBool(args, "overwrite", false);
        boolean permanent = ToolArgs.optionalBool(args, "permanent", false);
        List<String> done = new ArrayList<>();
        List<String> failed = new ArrayList<>();

        for (Map<String, Object> item : items) {
            Path src = null;
            try {
                src = ToolUtils.resolveAbsPath(String.valueOf(item.getOrDefault("src", "")));
                Object dstRaw = item.get("dst");
                Path dst = dstRaw == null || String.valueOf(dstRaw).isBlank()
                        ? null
                        : ToolUtils.resolveAbsPath(String.valueOf(dstRaw));
                // 只锁 src，不锁 dst：两项互为源/目标（A→B 与 B→A）时，
                // 「都锁」会按不同顺序取两把锁而互相等死；锁住源已经足够防住同一文件被同时搬走
                try (PathLock.LockHandle ignored = PathLock.lock(src)) {
                    if (OP_DELETE.equals(op)) {
                        if (permanent) {
                            deleteRecursively(src);
                        } else {
                            moveToTrash(src);
                        }
                        done.add("已删除 " + src);
                        continue;
                    }
                    if (dst == null) {
                        throw new IllegalArgumentException(op + " 必须给出目标路径");
                    }
                    // 目标父目录不存在时自动创建（与 write_file 的行为保持一致）
                    if (dst.getParent() != null) {
                        Files.createDirectories(dst.getParent());
                    }
                    if (Files.exists(dst) && overwrite) {
                        // 覆盖前先把旧目标送回收站：比直接删更安全
                        moveToTrash(dst);
                    }
                    if (OP_MOVE.equals(op)) {
                        Files.move(src, dst);
                    } else {
                        if (Files.isDirectory(src)) {
                            copyRecursively(src, dst);
                        } else {
                            // COPY_ATTRIBUTES：连修改时间等元数据一起复制
                            Files.copy(src, dst, StandardCopyOption.COPY_ATTRIBUTES);
                        }
                    }
                    done.add("已" + (OP_MOVE.equals(op) ? "移动" : "复制") + " " + src + " → " + dst);
                }
            } catch (RuntimeException | IOException e) {
                // 单项失败不影响其余项（与 index_path 的批量策略一致），最后统一汇总
                failed.add((src == null ? "(无法解析的源)" : src.toString()) + ": " + e.getMessage());
            }
        }

        StringBuilder body = new StringBuilder(op + " 完成 " + done.size() + "/" + items.size() + " 项");
        if (!done.isEmpty()) {
            body.append("\n").append(String.join("\n", done));
        }
        if (!failed.isEmpty()) {
            body.append("\n\n失败 ").append(failed.size()).append(" 项：\n");
            body.append(String.join("\n", failed.subList(0, Math.min(5, failed.size()))));
        }
        boolean ok = failed.isEmpty() || !done.isEmpty();
        return ok ? ToolResult.ok(body.toString()) : ToolResult.fail(body.toString());
    }

    /**
     * 拼出「这次删除可不可恢复」的说明。
     *
     * @param permanent true=直接删除（不进回收站）
     * @return 中文说明
     */
    private static String deleteHow(boolean permanent) {
        return permanent ? "⚠ 直接删除（不进回收站，无法恢复）" : "移入系统回收站（可从回收站还原）";
    }

    /**
     * 把文件/目录送入系统回收站；当前环境不支持回收站时明确报错。
     *
     * @param path 待删除路径
     * @throws IOException 无法送入回收站（调用方可提示用户改用 permanent=true）
     */
    private static void moveToTrash(Path path) throws IOException {
        try {
            Desktop desktop = Desktop.getDesktop();
            if (Desktop.isDesktopSupported()
                    && desktop.isSupported(Desktop.Action.MOVE_TO_TRASH)
                    && desktop.moveToTrash(path.toFile())) {
                return;
            }
        } catch (SecurityException | UnsupportedOperationException e) {
            // 无桌面环境（HeadlessException 是 UnsupportedOperationException 的子类）/权限不足：
            // 走下面的统一提示
        }
        throw new IOException("当前环境不支持系统回收站；如确认要永久删除，请传 permanent=true");
    }

    /**
     * 永久删除文件或目录树（从深到浅删除，避免「目录非空」）。
     *
     * @param path 待删除路径
     * @throws IOException 删除失败
     */
    private static void deleteRecursively(Path path) throws IOException {
        try (var walk = Files.walk(path)) {
            for (Path item : walk.sorted(Comparator.reverseOrder()).toList()) {
                Files.delete(item);
            }
        }
    }

    /**
     * 递归复制目录树。
     *
     * @param src 源目录
     * @param dst 目标目录（必须不存在或已由调用方处理）
     * @throws IOException 复制失败
     */
    private static void copyRecursively(Path src, Path dst) throws IOException {
        try (var walk = Files.walk(src)) {
            for (Path item : walk.toList()) {
                Path target = dst.resolve(src.relativize(item));
                if (Files.isDirectory(item)) {
                    Files.createDirectories(target);
                } else {
                    if (target.getParent() != null) {
                        Files.createDirectories(target.getParent());
                    }
                    Files.copy(item, target, StandardCopyOption.COPY_ATTRIBUTES);
                }
            }
        }
    }
}
