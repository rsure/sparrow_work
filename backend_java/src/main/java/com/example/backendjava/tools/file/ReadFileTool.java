// 模块说明：read_file 工具（对应 Python file_read_tool.py 的 read_file）。
package com.example.backendjava.tools.file;

import com.example.backendjava.tools.TextReadResult; // 项目内：文本读取结果（正文 + 读取说明）

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.FileGuard; // 项目内：读后写校验（防止覆盖别人刚做的修改）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）
import com.example.backendjava.tools.ToolSession; // 项目内：线程本地的会话上下文
import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：Files 判断文件类型
import java.nio.file.Files;
// 标准库：Path 文件路径
import java.nio.file.Path;
// 标准库：List 构造待校验路径
import java.util.List;
// 标准库：Map 构造弹窗预览与工具入参
import java.util.Map;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;

/**
 * 读取一个文件的文本内容（支持任意纯文本；二进制只返回元信息）。
 */
@Component
public class ReadFileTool extends AbstractGuardedTool {

    /** 单次最多返回的字符数，太大会挤占模型上下文。 */
    private static final int READ_MAX_CHARS = 20_000;

    /** 默认返回字符数，与 Python 侧一致。 */
    private static final int DEFAULT_CHARS = 8_000;

    /**
     * 构造器。
     *
     * @param runtime 工具执行关卡
     */
    public ReadFileTool(ToolRuntime runtime) {
        super(runtime);
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "read_file";
    }

    /** 返回工具说明，模型据此决定何时调用。 */
    @Override
    public String description() {
        return "读取一个文件的文本内容（支持 txt/md/代码/json/csv/日志等任何纯文本）。"
                + "适用：用户要求阅读、总结、基于某份文档回答问题。文档不大时优先直接读全文，"
                + "比知识库检索更准确。内容较长时会分段返回，按提示用 offset 继续读后面的部分。"
                + "图片、压缩包、xlsx 等二进制文件无法读取，只会返回大小/修改时间等元信息。";
    }

    /**
     * 把参数翻译成一次待裁决的只读操作。
     *
     * @param args 工具入参：path / offset / max_chars
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        Path path = ToolUtils.resolveAbsPath(ToolArgs.requiredString(args, "path"));
        return new ToolAction(
                name(),
                ToolKind.READ,
                path.toString(),
                List.of(path),
                Map.of("path", path.toString()),
                "读取文件 " + path
        );
    }

    /**
     * 执行读取：先做二进制/编码判断，再按 offset/max_chars 切一段返回。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 文件头信息 + 正文片段
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        try {
            Path path = action.paths().get(0);
            if (!Files.isRegularFile(path)) {
                return ToolResult.fail("文件不存在或不是文件: " + path);
            }
            TextReadResult read = ToolUtils.readTextAny(path);
            if (read.text() == null) {
                return ToolResult.fail("无法读取内容：" + read.note()
                        + "。文件元信息：" + ToolUtils.describeFile(path));
            }
            // 写前校验：登记「这个会话读过这份内容」，之后被别人改过再写会被拒绝
            FileGuard.recordRead(ToolSession.currentSessionId(), path);

            int maxChars = Math.max(1, Math.min(
                    ToolArgs.optionalInt(args, "max_chars", DEFAULT_CHARS), READ_MAX_CHARS));
            int start = Math.max(0, ToolArgs.optionalInt(args, "offset", 0));
            String text = read.text();
            // Java 的字符串按 UTF-16 码元计；这是模型上下文的字符预算，够用
            start = Math.min(start, text.length());
            int end = Math.min(text.length(), start + maxChars);
            String header = path + "（" + read.note() + "，共 " + text.length()
                    + " 字符，本次返回第 " + start + "~" + end + " 字符）";
            String tail = end < text.length()
                    ? "\n…[还剩 " + (text.length() - end) + " 字符未读，如需继续请用 offset=" + end + " 再次调用]"
                    : "";
            return ToolResult.ok(header + "\n" + text.substring(start, end) + tail);
        } catch (RuntimeException e) {
            return ToolResult.fail("读取失败: " + e.getMessage());
        }
    }
}
