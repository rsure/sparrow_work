// 模块说明：HTML → 纯文本的轻量实现（对应 Python web_tool.py 的 html_to_text）。
//
// Java 侧没有引入 jsoup/BeautifulSoup；这里用正则做近似处理，够网页正文提取使用。
// 已知限制：不解析嵌套标签的精确结构，style/script 之外的内联样式仍会残留少量文字。
package com.example.backendjava.tools.net;

// 标准库：Pattern / Matcher 做标签、脚本块与实体的替换
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * HTML 文本处理工具。
 */
public final class HtmlUtils {

    /** 对回答没有价值、且可能藏注入文本的整块标签（script 是注入高发区）。 */
    private static final Pattern BLOCK_TAGS = Pattern.compile(
            "(?is)<(script|style|noscript|nav|footer|header|svg)\\b.*?</\\1>");

    /** 块级标签：替换成换行，避免整页文字粘成一行。 */
    private static final Pattern BLOCK_BREAKS = Pattern.compile(
            "(?is)</?(p|div|li|tr|br|h[1-6]|section|article|table)\\b[^>]*>");

    /** 任意 HTML 标签。 */
    private static final Pattern ANY_TAG = Pattern.compile("(?s)<[^>]+>");

    /** 连续空白（用于摘要压缩成一行）。 */
    private static final Pattern WHITESPACE = Pattern.compile("\\s+");

    /** 三行以上空行折叠成两行，避免正文被排版空白冲淡。 */
    private static final Pattern MANY_NEWLINES = Pattern.compile("\\n{3,}");

    /** 数值实体（十进制与十六进制）。 */
    private static final Pattern NUMERIC_ENTITY = Pattern.compile("&#(x?)([0-9a-fA-F]+);");

    /** 工具类禁止实例化。 */
    private HtmlUtils() {
    }

    /**
     * 把整页 HTML 转成可读正文。
     *
     * @param html 原始 HTML
     * @return 纯文本；输入为 null 时返回空串
     */
    public static String toPlainText(String html) {
        if (html == null || html.isEmpty()) {
            return "";
        }
        String text = BLOCK_TAGS.matcher(html).replaceAll(" ");
        text = BLOCK_BREAKS.matcher(text).replaceAll("\n");
        text = ANY_TAG.matcher(text).replaceAll("");
        text = decodeEntities(text);
        text = text.replace("\r\n", "\n").replace('\r', '\n');
        text = text.replaceAll("[ \\t\\x0B\\f]+", " ");
        text = MANY_NEWLINES.matcher(text).replaceAll("\n\n");
        return text.strip();
    }

    /**
     * 去掉标签并压缩空白，用于搜索结果标题/摘要这种单行文本。
     *
     * @param html 原始片段
     * @return 单行纯文本
     */
    public static String toInlineText(String html) {
        if (html == null || html.isEmpty()) {
            return "";
        }
        String text = ANY_TAG.matcher(html).replaceAll("");
        text = decodeEntities(text);
        return WHITESPACE.matcher(text).replaceAll(" ").strip();
    }

    /**
     * 解码常见 HTML 实体与数值实体。
     *
     * @param text 原始文本
     * @return 解码后的文本
     */
    public static String decodeEntities(String text) {
        String result = text
                .replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"")
                .replace("&#39;", "'")
                .replace("&apos;", "'");
        Matcher matcher = NUMERIC_ENTITY.matcher(result);
        StringBuilder out = new StringBuilder();
        while (matcher.find()) {
            String replacement;
            try {
                int code = matcher.group(1).isEmpty()
                        ? Integer.parseInt(matcher.group(2))
                        : Integer.parseInt(matcher.group(2), 16);
                replacement = new String(Character.toChars(code));
            } catch (RuntimeException e) {
                // 非法实体原样保留，避免因为一条脏数据丢掉整段正文
                replacement = matcher.group();
            }
            matcher.appendReplacement(out, Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(out);
        return out.toString();
    }
}
