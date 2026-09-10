// 模块说明：write_file 工具（对应 Python file_write_tool.py 的 write_file）。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.FileGuard; // 项目内：读后写校验（防止覆盖别人刚做的修改）
import com.example.backendjava.tools.PathLock; // 项目内：按文件路径的互斥锁
import com.example.backendjava.tools.PathPolicy; // 项目内：路径操作策略（受保护目录 / 工作区白名单）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolSession; // 项目内：线程本地的会话上下文
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：IOException 文件系统异常
import java.io.IOException;
// 标准库：Charset 写入时使用的编码
import java.nio.charset.Charset;
// 标准库：StandardCharsets UTF-8 兜底
import java.nio.charset.StandardCharsets;
// 标准库：Files 创建目录、复制备份、写文件
import java.nio.file.Files;
// 标准库：Path 目标路径
import java.nio.file.Path;
// 标准库：StandardCopyOption.REPLACE_EXISTING / COPY_ATTRIBUTES
import java.nio.file.StandardCopyOption;
// 标准库：List 待校验路径
import java.util.List;
// 标准库：Map 弹窗预览
import java.util.Map;
// 标准库：LocalDateTime / DateTimeFormatter 生成备份时间戳
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 新建/覆盖文本文件。
 */
@Component
public class WriteFileTool extends AbstractGuardedTool {

    /** 单次写入内容的长度上限（字符，约 1MB），防止模型一次生成超大文件。 */
    private static final int MAX_WRITE_CHARS = 1_000_000;

    /** 备份文件名的中文时间戳格式。 */
    private static final DateTimeFormatter BACKUP_STAMP = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public WriteFileTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "write_file";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "新建一个文本文件并写入内容（txt/md/json/csv/代码等）；父目录不存在会自动创建。"
                + "适用：帮我新建一个 xxx 文件、把总结保存成 md、生成一份配置文件。"
                + "无论新建还是覆盖，落盘前系统都会请用户确认；覆盖已有文件时额外自动备份为 .bak。"
                + "目标文件已存在时必须传 overwrite=true 才允许覆盖。只想改已有文件的一部分请用 edit_file。";
    }

    /**
     * 把参数翻译成一次待裁决的写操作。
     *
     * @param args 工具入参：path / content / overwrite
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path path = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "path"));
        String content = ToolArgs.rawString(args, "content", "");
        boolean overwrite = ToolArgs.optionalBool(args, "overwrite", false);
        String actionWord = overwrite ? "覆盖" : "新建";
        return new ToolAction(
                name(),
                ToolKind.WRITE,
                path.toString(),
                List.of(path),
                Map.of("path", path.toString(),
                        "content", preview(content, 300),
                        "overwrite", overwrite),
                "AI 将" + actionWord + "文件：" + path + "（" + content.length() + " 字符）"
        );
    }

    /**
     * 执行写入：安全检查 -> 路径锁 -> 读后写校验 -> 备份 -> 落盘 -> 更新登记。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 写入结果
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        Path path = action.paths().get(0);
        String content = ToolArgs.rawString(args, "content", "");
        boolean overwrite = ToolArgs.optionalBool(args, "overwrite", false);
        try {
            // 1) 位置与格式约束（位置策略 + 二进制后缀 + 目标是目录）
            String reason = precheckWrite(path);
            if (reason != null) {
                return ToolResult.fail(reason);
            }
            // 2) 从这里到写入完成都在「这个路径的独占锁」里：
            //    只锁最后那一次 write 不够，两个线程可以同时通过上面的存在性判断
            try (PathLock.LockHandle ignored = PathLock.lock(path)) {
                String stale = FileGuard.checkWrite(ToolSession.currentSessionId(), path,
                        runtime().writeStaleGuardEnabled());
                if (stale != null) {
                    return ToolResult.fail(stale);
                }
                if (content.length() > MAX_WRITE_CHARS) {
                    return ToolResult.fail("内容过长（" + content.length()
                            + " 字符，上限 " + MAX_WRITE_CHARS + "）");
                }
                if (Files.exists(path) && !overwrite) {
                    return ToolResult.fail("文件已存在: " + path
                            + "。确实要整份覆盖请用 overwrite=true（会请用户确认）；"
                            + "只改局部内容请用 edit_file");
                }

                String backupMessage = "";
                Charset encoding = StandardCharsets.UTF_8;
                boolean keepBom = false;
                // 覆盖已有文件时才备份、才沿用原编码（避免 GBK 文件被改成 UTF-8 后其它程序读出乱码）
                if (Files.exists(path)) {
                    if (!ToolUtils.isBinaryFile(path)) {
                        Charset detected = ToolUtils.detectTextEncoding(path);
                        encoding = detected == null ? StandardCharsets.UTF_8 : detected;
                        keepBom = ToolUtils.hasUtf8Bom(path);
                    }
                    backupMessage = "，原文件已备份到 " + backup(path);
                }

                boolean createdDir = path.getParent() != null && !Files.exists(path.getParent());
                if (path.getParent() != null) {
                    Files.createDirectories(path.getParent());
                }
                // Files.write 不会做换行转换；内容里的 \n 原样落盘
                byte[] body = content.getBytes(encoding);
                if (keepBom) {
                    // 原文件带 UTF-8 BOM：写回时补上，保持文件原样
                    byte[] withBom = new byte[body.length + 3];
                    withBom[0] = (byte) 0xEF;
                    withBom[1] = (byte) 0xBB;
                    withBom[2] = (byte) 0xBF;
                    System.arraycopy(body, 0, withBom, 3, body.length);
                    body = withBom;
                }
                Files.write(path, body);
                FileGuard.recordWrite(ToolSession.currentSessionId(), path);

                String dirMessage = createdDir ? "，并新建了目录 " + path.getParent() : "";
                String actionWord = backupMessage.isEmpty() ? "已新建" : "已覆盖";
                return ToolResult.ok(actionWord + " " + path + "（"
                        + ToolUtils.humanSize(Files.size(path))
                        + "，编码 " + encoding.name() + "）" + dirMessage + backupMessage);
            }
        } catch (RuntimeException | IOException e) {
            return ToolResult.fail("写入失败: " + e.getMessage());
        }
    }

    /**
     * 写盘前的两项检查：安全策略（能否写这个位置）+ 格式约束（能否按文本写）。
     *
     * @param path 已 resolve 的绝对路径
     * @return 不允许写入时返回原因；允许时返回 null
     */
    private String precheckWrite(Path path) {
        String reason = PathPolicy.pathDecision(path, PathPolicy.OP_WRITE);
        if (reason != null) {
            return reason;
        }
        if (ToolUtils.RICH_DOC_SUFFIXES.contains(ToolUtils.suffixOf(path))) {
            return "不支持直接写 " + ToolUtils.suffixOf(path)
                    + " 文件（这是二进制格式），可以改写成 .md / .txt";
        }
        if (Files.isDirectory(path)) {
            return path + " 是一个目录，不能当文件写入";
        }
        return null;
    }

    /**
     * 把已有文件复制一份 "<文件名>.<时间戳>.bak" 放在同目录。
     *
     * @param path 已存在的文件
     * @return 备份文件路径
     * @throws IOException 复制失败
     */
    private Path backup(Path path) throws IOException {
        String stamp = LocalDateTime.now().format(BACKUP_STAMP);
        Path bak = path.resolveSibling(path.getFileName() + "." + stamp + ".bak");
        Files.copy(path, bak, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.COPY_ATTRIBUTES);
        return bak;
    }

    /**
     * 截断长文本，用于确认弹窗展示（避免把整份文件内容塞进事件）。
     *
     * @param text  原文
     * @param limit 最多保留的字符数
     * @return 截断后的文本
     */
    private static String preview(String text, int limit) {
        return text.length() <= limit
                ? text
                : text.substring(0, limit) + "…（共 " + text.length() + " 字符）";
    }
}
