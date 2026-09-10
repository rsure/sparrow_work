// 模块说明：知识库文档匹配（对应 Python file_read_tool.py 的 all_indexed_docs / match_indexed_docs /
// resolve_scope / resolve_import_path）。
//
// delete_index（删除要 id）、rag_search（检索只要 source）、`\doc` 指令解析，三处都要
// 「把用户说的名字换成人库记录」。共用同一份规则，才不会出现「检索说找得到、删除却说找不到」。
package com.example.backendjava.tools.rag;

import com.example.backendjava.tools.ToolUtils; // 项目内：路径、遍历、文件元信息与文本读取公共方法

// 标准库：ArrayList 收集匹配结果
import java.util.ArrayList;
// 标准库：List 结果列表
import java.util.List;
// 标准库：Locale 大小写转换
import java.util.Locale;
// 标准库：Map 保存 source -> 文档（去重）
import java.util.LinkedHashMap;
// 标准库：Path 处理用户给的路径
import java.nio.file.Path;
// 标准库：Paths 字符串转 Path
import java.nio.file.Paths;
// 标准库：InvalidPathException 表示路径字符串非法
import java.nio.file.InvalidPathException;
// 项目内：RAG 服务接口（可能尚未有实现，调用方负责判空）
import com.example.backendjava.service.RagService;
// 项目内：RAG 文档 DTO
import com.example.backendjava.dto.RagDtos;

/**
 * 知识库文档匹配工具。
 */
public final class IndexedDocSupport {

    /** 一次性取全部文档时使用的条数上限（与 Python 侧 _ALL_DOCS_LIMIT 一致）。 */
    public static final int ALL_DOCS_LIMIT = 100_000;

    /** 工具类禁止实例化。 */
    private IndexedDocSupport() {
    }

    /**
     * 取出知识库里所有文档的元信息。
     *
     * @param service RAG 服务
     * @return 文档列表；服务返回 null 时为空列表
     */
    public static List<RagDtos.RagDocument> allDocs(RagService service) {
        List<RagDtos.RagDocument> docs = service.listDocuments(ALL_DOCS_LIMIT, 0);
        return docs == null ? List.of() : docs;
    }

    /**
     * 在「已导入文档」里按绝对路径 / 文件夹 / 裸文件名匹配。
     *
     * <p>三种写法：</p>
     * <ul>
     *   <li>绝对路径且是文件：只匹配这一篇；</li>
     *   <li>绝对路径且是文件夹：匹配它自己以及它下面所有已导入的文档；</li>
     *   <li>只有文件名（如 note.md）：按文件名精确匹配（不区分大小写）。</li>
     * </ul>
     *
     * @param service RAG 服务
     * @param scope   用户或模型给的路径 / 文件名列表
     * @return 匹配结果
     */
    public static MatchResult match(RagService service, List<String> scope) {
        // 服务尚未实现时按「一篇都没有」处理：调用方会得到「没匹配上」的可读结果，
        // 而不是一个 NullPointerException
        List<RagDtos.RagDocument> docs = service == null ? List.of() : allDocs(service);
        // source -> 文档记录，用它去重（同一文件夹写法可能命中同一篇）
        LinkedHashMap<String, RagDtos.RagDocument> matched = new LinkedHashMap<>();
        List<String> missing = new ArrayList<>();
        for (String item : scope == null ? List.<String>of() : scope) {
            String text = stripQuotes(item);
            if (text.isEmpty()) {
                continue;
            }
            Path path = parsePath(text);
            List<RagDtos.RagDocument> hits;
            if (path != null && path.isAbsolute()) {
                Path base = path.toAbsolutePath().normalize();
                hits = docs.stream()
                        .filter(doc -> {
                            Path source = parsePath(doc.source());
                            return source != null && ToolUtils.sameOrUnder(source, base);
                        })
                        .toList();
            } else {
                String lower = text.toLowerCase(Locale.ROOT);
                hits = docs.stream()
                        .filter(doc -> displayName(doc).toLowerCase(Locale.ROOT).equals(lower))
                        .toList();
            }
            if (hits.isEmpty()) {
                missing.add(item);
            } else {
                for (RagDtos.RagDocument doc : hits) {
                    matched.put(doc.source(), doc);
                }
            }
        }
        List<RagDtos.RagDocument> ordered = new ArrayList<>(matched.values());
        ordered.sort((left, right) -> nullSafe(left.source()).compareToIgnoreCase(nullSafe(right.source())));
        return new MatchResult(ordered, missing);
    }

    /**
     * 把检索范围换算成知识库里的 source 列表。
     *
     * @param service RAG 服务
     * @param scope   路径或文件名列表
     * @return source 列表 + 没匹配上的条目
     */
    public static ScopeResult resolveScope(RagService service, List<String> scope) {
        MatchResult matched = match(service, scope);
        List<String> sources = matched.docs().stream()
                .map(RagDtos.RagDocument::source)
                .toList();
        return new ScopeResult(sources, matched.missing());
    }

    /**
     * 把 index_path 收到的参数解析成磁盘上的绝对路径。
     *
     * <p>支持绝对路径，也支持「已导入文档的文件名」（换算成当初导入时用的绝对路径）。</p>
     *
     * @param service RAG 服务
     * @param raw     用户或模型给的路径 / 文件名
     * @return 磁盘上的绝对路径（不保证存在）
     * @throws IllegalArgumentException 既不是绝对路径，也不匹配任何已导入文档
     */
    public static Path resolveImportPath(RagService service, String raw) {
        String text = stripQuotes(raw);
        Path direct = parsePath(text);
        if (direct != null && direct.isAbsolute()) {
            return ToolUtils.resolveAbsPath(text);
        }
        MatchResult matched = match(service, List.of(text));
        if (matched.docs().isEmpty()) {
            throw new IllegalArgumentException("「" + text + "」既不是绝对路径，也不是已导入文档的文件名。"
                    + "导入新文件请给完整路径（如 D:\\docs\\a.md）；"
                    + "不确定文档名可以先用 list_indexed_docs 查一下");
        }
        // 命中多篇同名文档（不同目录下的同名文件）时取第一篇：够用，且不会静默什么都不做
        Path source = parsePath(matched.docs().get(0).source());
        if (source == null) {
            throw new IllegalArgumentException("知识库记录的来源路径不合法：" + matched.docs().get(0).source());
        }
        return source.toAbsolutePath().normalize();
    }

    /**
     * 取文档的展示文件名：优先用 name，缺失时从 source 推断。
     *
     * @param doc 文档记录
     * @return 文件名；都取不到时返回空串
     */
    public static String displayName(RagDtos.RagDocument doc) {
        if (doc == null) {
            return "";
        }
        if (doc.name() != null && !doc.name().isBlank()) {
            return doc.name();
        }
        Path source = parsePath(doc.source());
        return source == null || source.getFileName() == null
                ? nullSafe(doc.source())
                : source.getFileName().toString();
    }

    /**
     * 把字符串转成 Path；非法路径返回 null（不抛异常）。
     *
     * @param text 路径字符串
     * @return Path 或 null
     */
    public static Path parsePath(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return Paths.get(expandUser(text.strip()));
        } catch (InvalidPathException e) {
            return null;
        }
    }

    /**
     * 剥掉路径首尾的空格与引号。
     *
     * @param text 原始文本
     * @return 清理后的文本
     */
    public static String stripQuotes(String text) {
        String result = text == null ? "" : text.strip();
        while (result.length() >= 2
                && ((result.startsWith("\"") && result.endsWith("\""))
                || (result.startsWith("'") && result.endsWith("'")))) {
            result = result.substring(1, result.length() - 1).strip();
        }
        return result;
    }

    /**
     * 展开开头的 ~ 为用户主目录（Java 没有 Path.expanduser）。
     *
     * @param text 原始路径
     * @return 展开后的路径
     */
    private static String expandUser(String text) {
        if (text.equals("~") || text.startsWith("~/") || text.startsWith("~\\")) {
            return System.getProperty("user.home", "") + text.substring(1);
        }
        return text;
    }

    /**
     * null 安全的字符串取值。
     *
     * @param value 原值
     * @return 原值或空串
     */
    private static String nullSafe(String value) {
        return value == null ? "" : value;
    }

    /**
     * 匹配结果。
     *
     * @param docs    命中的文档（按 source 排序去重）
     * @param missing 没匹配上的原始条目
     */
    public record MatchResult(
            // 命中的文档
            List<RagDtos.RagDocument> docs,
            // 没匹配上的条目
            List<String> missing
    ) {
    }

    /**
     * 检索范围换算结果。
     *
     * @param sources 匹配到的 source 列表
     * @param missing 没匹配上的条目
     */
    public record ScopeResult(
            // source 列表
            List<String> sources,
            // 没匹配上的条目
            List<String> missing
    ) {
    }
}
