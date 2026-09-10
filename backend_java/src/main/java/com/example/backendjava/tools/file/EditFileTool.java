// 模块说明：edit_file 工具（对应 Python file_write_tool.py 的 edit_file）。
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
// 标准库：Charset 读写时使用的编码
import java.nio.charset.Charset;
// 标准库：Files 读写文件
import java.nio.file.Files;
// 标准库：Path 目标路径
import java.nio.file.Path;
// 标准库：StandardCopyOption 备份时覆盖同名 .bak
import java.nio.file.StandardCopyOption;
// 标准库：List 待校验路径
import java.util.List;
// 标准库：Map 弹窗预览
import java.util.Map;
// 标准库：LocalDateTime / DateTimeFormatter 备份时间戳
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 修改已有文本文件：把 old_text 原样替换为 new_text（精确匹配，区分大小写）。
 */
@Component
public class EditFileTool extends AbstractGuardedTool {

    /** 备份文件名里的时间戳格式。 */
    private static final DateTimeFormatter BACKUP_STAMP = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    /** UTF-8 BOM 对应的字符（U+FEFF）；用常量避免源码里出现不可见字符。 */
    private static final char BOM_CHAR = '\uFEFF';

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public EditFileTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "edit_file";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "修改已有文本文件：把其中的 old_text 原样替换为 new_text（精确匹配，区分大小写）。"
                + "先用 read_file 读到原文，复制要改的那一段作为 old_text（带足够上下文让它唯一），"
                + "再给出改好的 new_text。new_text 传空字符串表示删除这段内容。"
                + "old_text 出现多次时默认拒绝；确实要全部替换时传 replace_all=true。"
                + "修改前系统会请用户确认，并自动备份为 .bak。不能修改 pdf/docx/图片等非纯文本文件。";
    }

    /**
     * 把参数翻译成一次待裁决的写操作。
     *
     * @param args 工具入参：path / old_text / new_text / replace_all
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path path = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "path"));
        String oldText = ToolArgs.rawString(args, "old_text", "");
        String newText = ToolArgs.rawString(args, "new_text", "");
        return new ToolAction(
                name(),
                ToolKind.WRITE,
                path.toString(),
                List.of(path),
                Map.of("path", path.toString(),
                        "old_text", preview(oldText),
                        "new_text", preview(newText)),
                "AI 将修改文件：" + path
        );
    }

    /**
     * 执行修改：校验 -> 锁 -> 读原文 -> 唯一匹配 -> 备份 -> 写回。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 替换次数与备份位置
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        Path path = action.paths().get(0);
        String oldText = ToolArgs.rawString(args, "old_text", "");
        String newText = ToolArgs.rawString(args, "new_text", "");
        boolean replaceAll = ToolArgs.optionalBool(args, "replace_all", false);
        try {
            if (!Files.isRegularFile(path)) {
                return ToolResult.fail("文件不存在: " + path + "（新建文件请用 write_file）");
            }
            String reason = PathPolicy.pathDecision(path, PathPolicy.OP_WRITE);
            if (reason != null) {
                return ToolResult.fail(reason);
            }
            if (ToolUtils.isBinaryFile(path)) {
                return ToolResult.fail(path + " 是二进制文件，不能按文本修改");
            }
            // 读原文 → 匹配 → 备份 → 写回，全部在路径锁里完成，
            // 否则两条车道同时「读旧内容再整份写回」就会丢掉对方那一处修改
            try (PathLock.LockHandle ignored = PathLock.lock(path)) {
                String stale = FileGuard.checkWrite(ToolSession.currentSessionId(), path,
                        runtime().writeStaleGuardEnabled());
                if (stale != null) {
                    return ToolResult.fail(stale);
                }
                if (oldText.isEmpty()) {
                    return ToolResult.fail("old_text 为空；在文件末尾追加内容时，请把文件最后一段作为 old_text");
                }
                Charset encoding = ToolUtils.detectTextEncoding(path);
                if (encoding == null) {
                    return ToolResult.fail("无法识别 " + path + " 的编码，为避免写坏文件，不做修改");
                }
                boolean keepBom = ToolUtils.hasUtf8Bom(path);
                String text = new String(Files.readAllBytes(path), encoding);
                // BOM 字符不属于正文：匹配前剥掉，写回时再补上
                if (keepBom && !text.isEmpty() && text.charAt(0) == BOM_CHAR) {
                    text = text.substring(1);
                }

                // 模型生成的文本一般只用 \n；文件若是 Windows 的 \r\n，先统一成 \n 再匹配，写回时还原
                boolean crlf = text.contains("\r\n");
                String work = crlf ? text.replace("\r\n", "\n") : text;
                String old = oldText.replace("\r\n", "\n");
                String replacement = newText.replace("\r\n", "\n");

                int count = countOccurrences(work, old);
                if (count == 0) {
                    return ToolResult.fail("文件中没有找到 old_text；请先用 read_file 读取最新内容，逐字复制要改的片段");
                }
                if (count > 1 && !replaceAll) {
                    return ToolResult.fail("old_text 在文件中出现了 " + count
                            + " 次，无法确定改哪一处；请在 old_text 里多带几行上下文让它唯一，"
                            + "或确认要全部替换后传 replace_all=true");
                }

                int replaced = replaceAll ? count : 1;
                String result = replaceAll
                        ? work.replace(old, replacement)
                        : replaceOne(work, old, replacement);
                if (crlf) {
                    result = result.replace("\n", "\r\n");
                }

                Path bak = backup(path);
                byte[] body = result.getBytes(encoding);
                if (keepBom) {
                    byte[] withBom = new byte[body.length + 3];
                    withBom[0] = (byte) 0xEF;
                    withBom[1] = (byte) 0xBB;
                    withBom[2] = (byte) 0xBF;
                    System.arraycopy(body, 0, withBom, 3, body.length);
                    body = withBom;
                }
                Files.write(path, body);
                FileGuard.recordWrite(ToolSession.currentSessionId(), path);
                return ToolResult.ok("已修改 " + path + "：替换 " + replaced
                        + " 处（编码 " + encoding.name() + "），原文件已备份到 " + bak);
            }
        } catch (RuntimeException | IOException e) {
            return ToolResult.fail("修改失败: " + e.getMessage());
        }
    }

    /**
     * 统计子串出现次数（不重叠）。
     *
     * @param text 原文
     * @param part 子串（调用方保证非空）
     * @return 出现次数
     */
    private static int countOccurrences(String text, String part) {
        int count = 0;
        int index = 0;
        while ((index = text.indexOf(part, index)) >= 0) {
            count++;
            index += part.length();
        }
        return count;
    }

    /**
     * 只替换第一处。
     *
     * @param text        原文
     * @param oldPart     旧片段
     * @param newPart     新片段
     * @return 替换后的文本
     */
    private static String replaceOne(String text, String oldPart, String newPart) {
        int index = text.indexOf(oldPart);
        if (index < 0) {
            return text;
        }
        return text.substring(0, index) + newPart + text.substring(index + oldPart.length());
    }

    /**
     * 复制备份文件。
     *
     * @param path 已存在的文件
     * @return 备份路径
     * @throws IOException 复制失败
     */
    private static Path backup(Path path) throws IOException {
        String stamp = LocalDateTime.now().format(BACKUP_STAMP);
        Path bak = path.resolveSibling(path.getFileName() + "." + stamp + ".bak");
        Files.copy(path, bak, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.COPY_ATTRIBUTES);
        return bak;
    }

    /**
     * 截断长文本，用于确认弹窗展示。
     *
     * @param text 原文
     * @return 最多 300 字符的预览
     */
    private static String preview(String text) {
        return text.length() <= 300
                ? text
                : text.substring(0, 300) + "…（共 " + text.length() + " 字符）";
    }
}
