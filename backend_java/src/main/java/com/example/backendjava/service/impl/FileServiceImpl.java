// 模块说明：文件预览业务实现（对应 Python 侧 app/services/file_browse_service.py）。
//
// 安全边界与工具层完全一致：路径先过 ToolUtils.resolveAbsPath（拒绝相对路径与系统目录），
// 再过 PathPolicy.pathDecision(OP_READ)，因此「Agent 能读什么，用户点击就能看什么」。
package com.example.backendjava.service.impl;

// 第三方（Spring）：声明为本服务的 Bean 实现
import org.springframework.stereotype.Service;

// 标准库：IOException 表示文件读取失败
import java.io.IOException;
// 标准库：URLConnection 按文件名猜 MIME（Windows 上比 probeContentType 更稳定）
import java.net.URLConnection;
// 标准库：Files 判断文件、读取大小与字节
import java.nio.file.Files;
// 标准库：Path 路径对象
import java.nio.file.Path;
// 标准库：Paths 字符串转 Path
import java.nio.file.Paths;
// 标准库：ArrayList 收集清单与候选
import java.util.ArrayList;
// 标准库：Comparator 候选排序
import java.util.Comparator;
// 标准库：HashSet 候选去重
import java.util.HashSet;
// 标准库：LinkedHashMap 保持结果字段顺序
import java.util.LinkedHashMap;
// 标准库：LinkedHashSet 按输入顺序去重路径
import java.util.LinkedHashSet;
// 标准库：List 批量路径与搜索结果
import java.util.List;
// 标准库：Locale 小写转换
import java.util.Locale;
// 标准库：Map 动态预览结果
import java.util.Map;
// 标准库：Set 候选去重
import java.util.Set;

// 项目内：业务异常（403/404 等业务码）
import com.example.backendjava.common.ApiException;
// 项目内：文件域 DTO（RawFile）
import com.example.backendjava.dto.FileDtos;
// 项目内：设置接口（读取当前生效工作区根目录）
import com.example.backendjava.dto.SettingDtos;
// 项目内：设置服务（工作区根目录的数据来源）
import com.example.backendjava.service.SettingsService;
// 项目内：文件预览业务接口（本类实现它）
import com.example.backendjava.service.FileService;
// 项目内：文件读取结果
import com.example.backendjava.tools.TextReadResult;
// 项目内：路径、文件元信息、文本读取与遍历工具
import com.example.backendjava.tools.ToolUtils;
// 项目内：遍历统计（截断标记）
import com.example.backendjava.tools.WalkStats;
// 项目内：路径操作策略（与 Agent 工具共用同一条放行规则）
import com.example.backendjava.tools.PathPolicy;

/**
 * 文件预览服务实现。
 */
@Service
public class FileServiceImpl implements FileService {

    /** 可以在 &lt;img&gt; 里直接显示的图片后缀（小写，含点）。 */
    private static final Set<String> IMAGE_SUFFIXES = Set.of(
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"
    );

    /** 预览接口单次最多返回多少字符（前端只做「看一眼」，不做全文编辑器）。 */
    private static final int PREVIEW_MAX_CHARS = 200_000;

    /** `@` 文件候选一次最多给多少条：输入框是下拉，太多翻不完。 */
    private static final int MENTION_MAX_RESULTS = 20;

    /** 搜索时单次最多扫多少个文件（防止在超大目录里把接口拖死）。 */
    private static final int MENTION_MAX_SCAN = 20_000;

    /** 设置服务：按当前生效工作区取根目录，保证搜索范围与 Agent 工具一致。 */
    private final SettingsService settingsService;

    /**
     * 构造器注入设置服务。
     *
     * @param settingsService 设置服务
     */
    public FileServiceImpl(SettingsService settingsService) {
        this.settingsService = settingsService;
    }

    /**
     * 把一批路径转成文件清单。
     *
     * <p>单个路径解析失败（相对路径、系统目录）不会让整个清单失败：跳过即可，
     * 这样 AI 回答里混入一条乱写的路径不会导致整个响应出错。</p>
     *
     * @param paths 文件绝对路径列表
     * @return 文件清单条目列表（顺序与输入一致，已去重）
     */
    @Override
    public List<Map<String, Object>> catalog(List<String> paths) {
        List<Map<String, Object>> result = new ArrayList<>();
        if (paths == null) {
            return result;
        }
        // 去重但保持输入顺序
        for (String raw : new LinkedHashSet<>(paths)) {
            try {
                Path path = ToolUtils.resolveAbsPath(raw);
                if (PathPolicy.pathDecision(path, PathPolicy.OP_READ) != null) {
                    // 策略不允许读：不出现在清单里，前端也就不会去点它
                    continue;
                }
                result.add(describe(path));
            } catch (RuntimeException ignored) {
                // 非法路径（相对路径 / 系统目录）直接跳过
            }
        }
        return result;
    }

    /**
     * 读取文本预览内容；不能预览时返回原因而不是抛异常。
     *
     * @param path     文件绝对路径
     * @param maxChars 最多返回多少字符
     * @return 含 ok/kind/content/reason/truncated 等字段的结果
     */
    @Override
    public Map<String, Object> preview(String path, int maxChars) {
        int limit = Math.max(1, Math.min(maxChars, 500_000));
        Map<String, Object> response = new LinkedHashMap<>();

        Path resolved;
        try {
            resolved = ToolUtils.resolveAbsPath(path);
        } catch (RuntimeException e) {
            response.put("ok", false);
            response.put("kind", "missing");
            response.put("reason", "路径不可访问: " + e.getMessage());
            response.put("content", "");
            return response;
        }

        String denied = PathPolicy.pathDecision(resolved, PathPolicy.OP_READ);
        if (denied != null) {
            response.put("ok", false);
            response.put("kind", "denied");
            response.put("reason", denied);
            response.put("content", "");
            return response;
        }
        if (!Files.isRegularFile(resolved)) {
            response.put("ok", false);
            response.put("kind", "missing");
            response.put("reason", "文件不存在或不是普通文件");
            response.put("content", "");
            return response;
        }

        String kind = kindOf(resolved);
        if ("image".equals(kind)) {
            // 图片不走本接口返回内容（前端直接用 /file/raw 当 <img> 的 src），
            // 这里只回元信息，避免把二进制塞进 JSON
            response.put("ok", true);
            response.put("kind", "image");
            response.put("content", "");
            response.put("reason", "");
            response.put("raw_url", "/file/raw?path=" + resolved);
            response.put("truncated", false);
            return response;
        }
        if ("rich".equals(kind) || "binary".equals(kind)) {
            response.put("ok", true);
            response.put("kind", kind);
            response.put("content", "");
            response.put("reason", "该格式不支持在页面内预览，可用系统程序打开");
            response.put("truncated", false);
            return response;
        }

        TextReadResult textResult = ToolUtils.readTextAny(resolved);
        if (textResult.text() == null) {
            response.put("ok", false);
            response.put("kind", "text");
            response.put("reason", textResult.note());
            response.put("content", "");
            response.put("truncated", false);
            return response;
        }

        String text = textResult.text();
        boolean truncated = text.length() > limit;
        java.nio.charset.Charset charset = ToolUtils.detectTextEncoding(resolved);
        response.put("ok", true);
        response.put("kind", "text");
        response.put("content", truncated ? text.substring(0, limit) : text);
        response.put("reason", "");
        response.put("encoding", charset == null ? "utf-8" : charset.name().toLowerCase(Locale.ROOT));
        response.put("truncated", truncated);
        return response;
    }

    /**
     * 在当前工作区里按文件名/相对路径模糊搜索（输入框 `@` 的候选）。
     *
     * @param query 搜索关键词；空表示随便列一些
     * @param limit 最多返回多少条
     * @return 含 query/items/roots/truncated 的结果
     */
    @Override
    public Map<String, Object> search(String query, int limit) {
        String rawQuery = query == null ? "" : query;
        String q = rawQuery.strip().toLowerCase(Locale.ROOT);
        int maxResults = Math.max(1, Math.min(limit, 50));
        List<Path> roots = activeRoots();

        List<Candidate> matched = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        WalkStats stats = new WalkStats();
        for (Path root : roots) {
            for (Path path : ToolUtils.walkFiles(root, MENTION_MAX_SCAN, stats)) {
                String relative;
                try {
                    relative = root.relativize(path).toString().replace('\\', '/');
                } catch (IllegalArgumentException e) {
                    // 理论上 walkFiles 只产出 root 之下的路径；真越界就当它不在这个根里
                    continue;
                }
                String key = path.toString().toLowerCase(Locale.ROOT);
                if (!seen.add(key)) {
                    continue;
                }
                String name = path.getFileName() == null
                        ? ""
                        : path.getFileName().toString().toLowerCase(Locale.ROOT);
                if (!q.isEmpty() && !name.contains(q) && !relative.toLowerCase(Locale.ROOT).contains(q)) {
                    continue;
                }
                matched.add(new Candidate(
                        q.isEmpty() ? 2 : mentionScore(name, q),
                        relative.length(),
                        path,
                        root
                ));
                if (matched.size() >= MENTION_MAX_SCAN) {
                    stats.markTruncated();
                    break;
                }
            }
        }

        // 先按「命中质量」，再按路径深浅（浅的更容易认出来），最后按路径字典序保证稳定
        matched.sort(Comparator
                .comparingInt(Candidate::score)
                .thenComparingInt(Candidate::relativeLength)
                .thenComparing(candidate -> candidate.path().toString().toLowerCase(Locale.ROOT)));

        List<Map<String, Object>> items = new ArrayList<>();
        for (Candidate candidate : matched) {
            if (items.size() >= maxResults) {
                break;
            }
            Path path = candidate.path();
            try {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("path", path.toString());
                item.put("name", path.getFileName() == null ? "" : path.getFileName().toString());
                item.put("rel", candidate.root().relativize(path).toString().replace('\\', '/'));
                item.put("kind", kindOf(path));
                item.put("size_text", ToolUtils.humanSize(Files.size(path)));
                items.add(item);
            } catch (IOException | RuntimeException ignored) {
                // 扫到之后文件又被删了：跳过，不要让整个候选列表失败
            }
        }

        List<String> rootTexts = new ArrayList<>(roots.size());
        for (Path root : roots) {
            rootTexts.add(root.toString());
        }
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("query", rawQuery);
        response.put("items", items);
        response.put("roots", rootTexts);
        response.put("truncated", stats.isTruncated());
        return response;
    }

    /**
     * 原样读取文件内容（用于图片等）。
     *
     * @param path 文件绝对路径
     * @return 文件字节与 MIME 类型
     */
    @Override
    public FileDtos.RawFile raw(String path) {
        Path resolved;
        try {
            resolved = ToolUtils.resolveAbsPath(path);
        } catch (RuntimeException e) {
            throw new ApiException(403, "路径不可访问: " + e.getMessage(), e);
        }
        String reason = PathPolicy.pathDecision(resolved, PathPolicy.OP_READ);
        if (reason != null || !Files.isRegularFile(resolved)) {
            // 403 而不是 404：让前端能区分「不存在」和「不允许」
            throw new ApiException(403, reason == null ? "不是普通文件" : reason);
        }
        try {
            return new FileDtos.RawFile(Files.readAllBytes(resolved), guessMime(resolved));
        } catch (IOException e) {
            throw new ApiException(404, "读取文件失败: " + e.getMessage(), e);
        }
    }

    /**
     * 判断文件属于哪一类（决定前端用哪种预览方式）。
     *
     * @param path 已 resolve 的绝对路径
     * @return text / image / rich / binary 之一
     */
    private String kindOf(Path path) {
        String suffix = ToolUtils.suffixOf(path);
        if (IMAGE_SUFFIXES.contains(suffix)) {
            return "image";
        }
        if (ToolUtils.RICH_DOC_SUFFIXES.contains(suffix)) {
            return "rich";
        }
        // 先按后缀排除明显是二进制的，再用内容嗅探兜底（防止 .md 里其实塞了二进制）
        return ToolUtils.isBinaryFile(path) ? "binary" : "text";
    }

    /**
     * 生成一个文件清单条目（不含内容）。
     *
     * @param path 已 resolve 的绝对路径
     * @return 含 path/name/kind/previewable/size/size_text/reason/mime 的字典
     */
    private Map<String, Object> describe(Path path) {
        boolean exists = Files.isRegularFile(path);
        String kind = exists ? kindOf(path) : "missing";
        boolean previewable = "text".equals(kind) || "image".equals(kind) || "rich".equals(kind);

        String reason = "";
        if (!exists) {
            reason = "文件不存在或不是普通文件";
        } else if ("binary".equals(kind)) {
            reason = "二进制文件，不支持在页面内预览";
        }

        long size = 0L;
        String sizeText = "";
        if (exists) {
            try {
                size = Files.size(path);
                sizeText = ToolUtils.humanSize(size);
            } catch (IOException ignored) {
                // 读不到大小就按 0 展示，不影响其余字段
            }
        }

        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("path", path.toString());
        entry.put("name", path.getFileName() == null ? "" : path.getFileName().toString());
        entry.put("kind", kind);
        // 能否在左侧面板里预览（false 时前端只提供「打开所在文件夹/用系统程序打开」）
        entry.put("previewable", previewable);
        entry.put("size", size);
        entry.put("size_text", sizeText);
        entry.put("reason", reason);
        entry.put("mime", guessMime(path));
        return entry;
    }

    /**
     * 猜文件的 MIME 类型；猜不出时返回空串（Controller 会回退成二进制流）。
     *
     * @param path 文件路径
     * @return 例如 image/png；未知时 ""
     */
    private String guessMime(Path path) {
        try {
            String probed = Files.probeContentType(path);
            if (probed != null && !probed.isBlank()) {
                return probed;
            }
        } catch (IOException ignored) {
            // probe 失败不影响后续按文件名猜
        }
        String fileName = path.getFileName() == null ? "" : path.getFileName().toString();
        String guessed = URLConnection.guessContentTypeFromName(fileName);
        return guessed == null ? "" : guessed;
    }

    /**
     * 返回当前生效工作区的根目录（只保留真实存在的目录）。
     *
     * @return 根目录列表；没有生效工作区或目录全失效时为空列表
     */
    private List<Path> activeRoots() {
        List<Path> roots = new ArrayList<>();
        try {
            SettingDtos.WorkspacesView view = settingsService.listWorkspaces();
            for (SettingDtos.WorkspaceProfile profile : view.workspaces()) {
                if (!profile.active()) {
                    continue;
                }
                for (String text : profile.roots()) {
                    try {
                        Path path = Paths.get(expandUser(text)).toAbsolutePath().normalize();
                        if (Files.isDirectory(path)) {
                            roots.add(path);
                        }
                    } catch (RuntimeException ignored) {
                        // 配置里残留的非法路径：跳过
                    }
                }
                // 只取当前生效的那一个工作区
                break;
            }
        } catch (RuntimeException ignored) {
            // 设置库尚未就绪时按「没有工作区」处理，不让搜索接口 500
        }
        return roots;
    }

    /**
     * 展开路径开头的 ~ 为用户主目录（Java 没有 Path.expanduser）。
     *
     * @param text 原始路径
     * @return 展开后的路径
     */
    private String expandUser(String text) {
        if (text == null) {
            return "";
        }
        String stripped = text.strip();
        if (stripped.equals("~") || stripped.startsWith("~/") || stripped.startsWith("~\\")) {
            return System.getProperty("user.home", "") + stripped.substring(1);
        }
        return stripped;
    }

    /**
     * 给一个命中文件打排序分（越小越靠前）。
     *
     * @param nameLower 已转小写的文件名（含后缀）
     * @param query     已转小写的查询串
     * @return 0=文件名以查询串开头，1=文件名包含，2=只在路径里包含
     */
    private int mentionScore(String nameLower, String query) {
        if (nameLower.startsWith(query)) {
            return 0;
        }
        return nameLower.contains(query) ? 1 : 2;
    }

    /**
     * 一个搜索候选：排序分、相对路径长度、绝对路径与所属根目录。
     *
     * @param score          命中质量分（越小越靠前）
     * @param relativeLength 相对路径长度（浅的优先）
     * @param path           文件绝对路径
     * @param root           所属工作区根目录
     */
    private record Candidate(
            // 命中质量分
            int score,
            // 相对路径长度
            int relativeLength,
            // 文件绝对路径
            Path path,
            // 所属根目录
            Path root
    ) {
    }
}
