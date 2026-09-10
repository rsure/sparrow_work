// 模块说明：Agent 工具的公共底座（对应 Python app/tools/tool_utils.py）。
//
// 集中提供四类能力，所有原子工具都必须复用，避免各写一份导致安全策略漏改：
//   1. 绝对路径解析：只接受绝对路径；系统文件/系统目录一律拒绝；
//   2. 目录递归：跳过 node_modules/.git 等巨型目录与系统项，并设文件数上限；
//   3. 文件元信息：大小格式化、修改时间、后缀；
//   4. 任意文件读成文本：二进制嗅探、UTF-8/GB18030 编码识别、超大文件只给元信息。
package com.example.backendjava.tools;

// 标准库：IOException 表示文件系统读写失败（调用方通常转成 FAIL 文案）
import java.io.IOException;
// 标准库：DirectoryStream 逐层列目录，便于自己控制排序与跳过规则
import java.nio.file.DirectoryStream;
// 标准库：Files 提供读字节、读属性、判断存在性等文件操作
import java.nio.file.Files;
// 标准库：LinkOption.NOFOLLOW_LINKS 读文件属性时不跟随符号链接
import java.nio.file.LinkOption;
// 标准库：Path 表示文件/目录路径
import java.nio.file.Path;
// 标准库：Paths 把字符串转成 Path
import java.nio.file.Paths;
// 标准库：DosFileAttributes 用于读取 Windows 的「系统」属性
import java.nio.file.attribute.DosFileAttributes;
// 标准库：Charset 表示编码（UTF-8、GB18030 等）
import java.nio.charset.Charset;
// 标准库：CharsetDecoder 做严格解码，失败时抛异常而不是静默替换
import java.nio.charset.CharsetDecoder;
// 标准库：CodingErrorAction.REPORT 让解码遇到非法字节时立即报错
import java.nio.charset.CodingErrorAction;
// 标准库：StandardCharsets 提供 UTF-8 常量
import java.nio.charset.StandardCharsets;
// 标准库：CharacterCodingException 表示整份数据不是该编码
import java.nio.charset.CharacterCodingException;
// 标准库：ByteBuffer 把字节数组包装成解码器入参
import java.nio.ByteBuffer;
// 标准库：LocalDateTime/ZoneId/DateTimeFormatter 把修改时间格式化成人能读的文本
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
// 标准库：ArrayList 收集遍历结果
import java.util.ArrayList;
// 标准库：Comparator 定义「目录在前、文件名升序」的排序
import java.util.Comparator;
// 标准库：LinkedHashMap 保持不支持后缀的展示顺序
import java.util.LinkedHashMap;
// 标准库：List 返回文件清单
import java.util.List;
// 标准库：Locale 让大小写转换不受本机语言环境影响
import java.util.Locale;
// 标准库：Map 描述「后缀 -> 另存为建议」
import java.util.Map;
// 标准库：Set 描述跳过的目录名与富文本后缀
import java.util.Set;

/**
 * 工具公共底座。
 *
 * <p>本类全部是静态方法：它不持有状态，也不依赖 Spring，任何工具都能直接调用。</p>
 */
public final class ToolUtils {

    /**
     * 需要专用解析器的富文本后缀（对应 Python document_parser.structured_suffixes）。
     *
     * <p>Java 侧暂未接入 PDF/Office 解析器，读取时只返回说明；写文件时一律拒绝，
     * 避免把二进制格式当文本写坏。</p>
     */
    public static final Set<String> RICH_DOC_SUFFIXES = Set.of(
            ".pdf",
            ".docx", ".doc", ".dot", ".wps", ".wpt", ".docm",
            ".xlsx", ".xls", ".xlt", ".xlsm",
            ".pptx", ".ppt", ".pps", ".pot"
    );

    /** 递归遍历时默认跳过的目录名：依赖、缓存、版本库，体积大且对回答几乎没有价值。 */
    public static final Set<String> IGNORED_DIR_NAMES = Set.of(
            "node_modules", ".git", ".svn", ".hg", ".venv", "venv",
            "__pycache__", ".idea", ".vscode", "dist", "build", ".pytest_cache"
    );

    /** 判断二进制时只看文件开头这么多字节（单位：字节），足够覆盖文件头又不必读整份文件。 */
    public static final int BINARY_SNIFF_BYTES = 8192;

    /** 纯文本解码依次尝试的编码；GB18030 是 GBK 的超集，能覆盖 Windows 中文文件。 */
    private static final List<String> TEXT_ENCODINGS = List.of("UTF-8", "GB18030");

    /** readTextAny 允许读取的最大文件体积（单位：字节，20MB），再大只返回元信息。 */
    public static final long MAX_READ_BYTES = 20L * 1024 * 1024;

    /** 引擎明确不支持的 Office 容器格式：按文本硬读是乱码，直接提示另存为更有用。 */
    private static final Map<String, String> UNSUPPORTED_OFFICE_SUFFIXES = Map.of(
            ".rtf", ".docx",
            ".odt", ".docx",
            ".et", ".xlsx",
            ".dps", ".pptx"
    );

    /** 当前运行环境是否 Windows；路径规则与文件属性判断都依赖它。 */
    public static final boolean IS_WINDOWS =
            System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");

    /** 系统目录：任何工具（读、搜、导入、写）都不允许进入。 */
    private static final List<Path> SYSTEM_DIRS = buildSystemDirs();

    /** 各盘根目录下的系统项（名字小写）：回收站、还原点、启动文件、虚拟内存等。 */
    private static final Set<String> ROOT_SYSTEM_NAMES = Set.of(
            "$recycle.bin", "system volume information", "recovery", "boot", "bootmgr",
            "$windows.~bt", "$windows.~ws", "$winreagent", "config.msi",
            "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp"
    );

    /** 修改时间展示格式：年-月-日 时:分，与 Python 侧保持一致。 */
    private static final DateTimeFormatter MTIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    /** 工具类禁止实例化。 */
    private ToolUtils() {
    }

    // ------------------------------------------------------------------ //
    // 路径
    // ------------------------------------------------------------------ //

    /**
     * 把模型传进来的路径字符串规范成绝对路径；不是绝对路径时直接报错。
     *
     * <p>为什么拒绝相对路径：后端进程的工作目录不是用户心里的目录，用户说的 "docs"
     * 在后端看来可能是 backend_java/docs，很容易读错甚至写错地方。</p>
     *
     * @param raw 原始路径字符串，允许首尾空格、引号与 ~（用户主目录）
     * @return 已规范的绝对路径（不保证存在，调用方自行判断）
     * @throws IllegalArgumentException 路径为空或不是绝对路径
     * @throws SecurityException        路径属于系统文件/系统目录
     */
    public static Path resolveAbsPath(String raw) {
        String text = raw == null ? "" : raw.strip();
        // 用户从资源管理器复制路径时经常带引号，先剥掉再解析
        text = stripQuotes(text);
        if (text.isEmpty()) {
            throw new IllegalArgumentException("路径为空");
        }
        // Java 没有 Path.expanduser()，这里手动把 ~ 换成本机用户主目录
        if (text.equals("~") || text.startsWith("~/") || text.startsWith("~\\")) {
            text = System.getProperty("user.home", "") + text.substring(1);
        }
        Path path = Paths.get(text);
        if (!path.isAbsolute()) {
            throw new IllegalArgumentException(
                    "需要绝对路径（如 D:\\docs），收到的是相对路径: " + raw + "；请向用户确认完整路径");
        }
        path = path.toAbsolutePath().normalize();
        // 存在时解析符号链接，避免「软链接指向系统目录」绕过检查；不存在则保留规范路径
        if (Files.exists(path)) {
            try {
                path = path.toRealPath();
            } catch (IOException ignored) {
                // 权限不足等情况下保留原路径，后续的存在性/权限检查会给出更具体的错误
            }
        }
        String reason = systemPathReason(path);
        if (reason != null) {
            throw new SecurityException(reason + "，系统文件不允许读取、搜索、导入或修改");
        }
        return path;
    }

    /**
     * 判断 path 是否就是 base，或位于 base 目录之下（Windows 下大小写不敏感）。
     *
     * @param path 被检查的路径
     * @param base 基准文件或目录
     * @return path == base 或 path 在 base 子树内时为 true
     */
    public static boolean sameOrUnder(Path path, Path base) {
        String p = normalizeForCompare(path);
        String b = normalizeForCompare(base);
        return p.equals(b) || p.startsWith(b.endsWith(java.io.File.separator)
                ? b
                : b + java.io.File.separator);
    }

    /**
     * 判断路径是不是系统文件/系统目录，是的话说明原因。三条规则任一命中即算：
     *
     * <ol>
     *   <li>位于 SYSTEM_DIRS 之下（Windows 目录、Program Files、ProgramData 等）；</li>
     *   <li>是某个盘根目录下的系统项，或位于其中（回收站、pagefile.sys 等）；</li>
     *   <li>文件本身带 Windows「系统」属性（目录上的系统属性不算）。</li>
     * </ol>
     *
     * @param path 绝对路径（不要求存在；不存在时跳过第 3 条）
     * @return 命中时返回原因；不是系统路径返回 null
     */
    public static String systemPathReason(Path path) {
        Path absolute = path.toAbsolutePath().normalize();
        for (Path dir : SYSTEM_DIRS) {
            if (sameOrUnder(absolute, dir)) {
                return absolute + " 位于系统目录 " + dir;
            }
        }
        // Windows 上 getName(0) 是盘符后的第一层名字（如 C:\Windows 的 "Windows"）
        if (absolute.getNameCount() >= 1) {
            String first = absolute.getName(0).toString().toLowerCase(Locale.ROOT);
            if (ROOT_SYSTEM_NAMES.contains(first)) {
                return absolute + " 属于磁盘根目录下的系统项 " + first;
            }
        }
        try {
            DosFileAttributes attrs = Files.readAttributes(
                    absolute, DosFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (attrs.isSystem() && !attrs.isDirectory()) {
                return absolute + " 带有系统文件属性";
            }
        } catch (IOException | UnsupportedOperationException ignored) {
            // 文件不存在、无权限，或当前系统没有 DOS 属性视图：交给调用方后续检查
        }
        return null;
    }

    // ------------------------------------------------------------------ //
    // 遍历
    // ------------------------------------------------------------------ //

    /**
     * 递归收集 root 下的文件，跳过依赖/缓存目录与系统项，最多收集 maxFiles 个。
     *
     * <p>用自己写的递归而不是 Files.walk：需要「原地裁剪子目录 + 稳定排序 + 统计跳过数量」，
     * Files.walk 既要先全部产出再过滤，也无法在遍历中告诉调用方跳过了多少。</p>
     *
     * @param root     起始目录（调用方保证是存在的目录）
     * @param maxFiles 文件数上限，防止扫描整个磁盘时卡死
     * @param stats    统计对象，遍历中会写入跳过数量与截断标记
     * @return 文件路径列表（目录内按名字升序，保证结果稳定）
     */
    public static List<Path> walkFiles(Path root, int maxFiles, WalkStats stats) {
        List<Path> files = new ArrayList<>();
        walkRecursive(root, maxFiles, stats, files);
        return files;
    }

    /**
     * walkFiles 的递归实现：每层先列出、排序、过滤，再决定是否继续深入。
     *
     * @param dir      当前目录
     * @param maxFiles 文件数上限
     * @param stats    统计对象
     * @param out      收集结果的可变列表
     */
    private static void walkRecursive(Path dir, int maxFiles, WalkStats stats, List<Path> out) {
        if (out.size() >= maxFiles) {
            stats.markTruncated();
            return;
        }
        List<Path> children = new ArrayList<>();
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(dir)) {
            for (Path child : stream) {
                children.add(child);
            }
        } catch (IOException | SecurityException ignored) {
            // 无权限读取的目录直接跳过：遍历整个磁盘时这是常态，不该让整个工具失败
            return;
        }
        children.sort(Comparator.comparing(
                (Path p) -> p.getFileName().toString().toLowerCase(Locale.ROOT))
                .thenComparing(p -> p.getFileName().toString()));
        for (Path child : children) {
            if (out.size() >= maxFiles) {
                stats.markTruncated();
                return;
            }
            String name = child.getFileName().toString();
            if (Files.isDirectory(child)) {
                if (IGNORED_DIR_NAMES.contains(name)) {
                    stats.addSkippedDir();
                    continue;
                }
                if (systemPathReason(child) != null) {
                    stats.addSkippedSystem();
                    continue;
                }
                walkRecursive(child, maxFiles, stats, out);
            } else {
                if (systemPathReason(child) != null) {
                    stats.addSkippedSystem();
                    continue;
                }
                out.add(child);
            }
        }
    }

    // ------------------------------------------------------------------ //
    // 文件元信息
    // ------------------------------------------------------------------ //

    /**
     * 把字节数格式化成 B / KB / MB / GB，方便模型直接转述给用户。
     *
     * @param bytes 字节数
     * @return 例如 "1.5 MB"
     */
    public static String humanSize(long bytes) {
        double size = bytes;
        String[] units = {"B", "KB", "MB", "GB"};
        for (int i = 0; i < units.length; i++) {
            if (size < 1024 || i == units.length - 1) {
                return "B".equals(units[i])
                        ? String.format(Locale.ROOT, "%.0f %s", size, units[i])
                        : String.format(Locale.ROOT, "%.1f %s", size, units[i]);
            }
            size /= 1024;
        }
        return bytes + " B";
    }

    /**
     * 生成一个文件的元信息描述（大小 + 修改时间 + 后缀），无法读内容时作为兜底返回。
     *
     * @param path 已存在的文件
     * @return 例如 "大小 1.2 MB，修改于 2026-10-14 10:30，类型 .png"
     */
    public static String describeFile(Path path) {
        try {
            long size = Files.size(path);
            LocalDateTime mtime = LocalDateTime.ofInstant(
                    Files.getLastModifiedTime(path).toInstant(), ZoneId.systemDefault());
            String suffix = suffixOf(path);
            return "大小 " + humanSize(size)
                    + "，修改于 " + mtime.format(MTIME_FORMAT)
                    + "，类型 " + (suffix.isEmpty() ? "(无后缀)" : suffix);
        } catch (IOException e) {
            return "无法读取文件元信息: " + e.getMessage();
        }
    }

    /**
     * 取文件的小写后缀（含点）；没有后缀时返回空串。
     *
     * @param path 文件路径
     * @return 例如 ".md"；无后缀时 ""
     */
    public static String suffixOf(Path path) {
        String name = path.getFileName() == null ? "" : path.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
    }

    // ------------------------------------------------------------------ //
    // 文本读取
    // ------------------------------------------------------------------ //

    /**
     * 判断文件是否以 UTF-8 BOM（EF BB BF）开头。
     *
     * <p>写文件时要保留原来的 BOM，否则某些 Windows 程序会把带 BOM 的 UTF-8 文件
     * 再次按 GBK 识别，导致中文乱码。</p>
     *
     * @param path 文件路径
     * @return true 表示带 BOM；文件读不到时按 false 处理
     */
    public static boolean hasUtf8Bom(Path path) {
        try (var in = Files.newInputStream(path)) {
            byte[] head = in.readNBytes(3);
            return hasUtf8Bom(head);
        } catch (IOException e) {
            return false;
        }
    }

    /**
     * 嗅探文件开头是否含 NUL 字节，含则认为是二进制（图片、压缩包、exe 等）。
     *
     * <p>这是 git / grep 等工具通用的近似判断：文本文件几乎不会出现 \x00。
     * 已知限制：UTF-16 编码的文本也含 \x00，会被误判为二进制。</p>
     *
     * @param path 已存在的文件
     * @return true 表示二进制，不应按文本解码
     */
    public static boolean isBinaryFile(Path path) {
        try (var in = Files.newInputStream(path)) {
            byte[] head = in.readNBytes(BINARY_SNIFF_BYTES);
            for (byte b : head) {
                if (b == 0) {
                    return true;
                }
            }
            return false;
        } catch (IOException e) {
            // 读不了就按二进制处理：宁可只给元信息，也不要吐一堆乱码
            return true;
        }
    }

    /**
     * 按 TEXT_ENCODINGS 依次严格解码整份文件，返回第一个成功的编码。
     *
     * <p>写文件时需要沿用原编码，避免 UTF-8 文件被别的程序按 GBK 读成乱码。
     * 带 UTF-8 BOM 的文件返回 UTF-8（读取时会剥掉 BOM）。</p>
     *
     * @param path 已存在的纯文本文件
     * @return 编码；全部失败时返回 null（调用方可退化为 UTF-8 + 替换非法字节）
     */
    public static Charset detectTextEncoding(Path path) {
        final byte[] data;
        try {
            data = Files.readAllBytes(path);
        } catch (IOException e) {
            return null;
        }
        if (hasUtf8Bom(data)) {
            return StandardCharsets.UTF_8;
        }
        for (String name : TEXT_ENCODINGS) {
            Charset charset = Charset.forName(name);
            if (canDecode(data, charset)) {
                return charset;
            }
        }
        return null;
    }

    /**
     * 尽量把任意文件读成文本，读不了就说明原因。分层兜底：
     *
     * <ol>
     *   <li>超过 MAX_READ_BYTES：不读内容，只给元信息；</li>
     *   <li>pdf/docx：需要专用解析器，提示走 RAG 导入；</li>
     *   <li>引擎明确不支持的 Office 容器格式：提示另存为；</li>
     *   <li>二进制：不读；</li>
     *   <li>其它：按 UTF-8 / GB18030 解码，全失败则 UTF-8 容错解码。</li>
     * </ol>
     *
     * @param path 已存在的文件
     * @return 读取结果；text 为 null 表示无法读取正文
     */
    public static TextReadResult readTextAny(Path path) {
        long size;
        try {
            size = Files.size(path);
        } catch (IOException e) {
            return new TextReadResult(null, "读取文件大小失败: " + e.getMessage());
        }
        if (size > MAX_READ_BYTES) {
            return new TextReadResult(null,
                    "文件过大（" + humanSize(size) + "，上限 " + humanSize(MAX_READ_BYTES) + "），只能提供元信息");
        }
        String suffix = suffixOf(path);
        if (RICH_DOC_SUFFIXES.contains(suffix)) {
            // Java 侧尚未接入 PDF/Word 解析器；明确告知模型，避免它以为文件是空的
            return new TextReadResult(null, suffix + " 需要专用文档解析器，当前 Java 工具层暂未接入，可先导入 RAG 知识库");
        }
        String hint = UNSUPPORTED_OFFICE_SUFFIXES.get(suffix);
        if (hint != null) {
            return new TextReadResult(null, "暂不支持直接读取 " + suffix + " 文件，请另存为 " + hint + " 后再试");
        }
        if (isBinaryFile(path)) {
            return new TextReadResult(null, "二进制文件（图片/压缩包/可执行文件/xlsx 等），无法按文本读取");
        }
        final byte[] data;
        try {
            data = Files.readAllBytes(path);
        } catch (IOException e) {
            return new TextReadResult(null, "读取文件失败: " + e.getMessage());
        }
        Charset charset = detectTextEncoding(path);
        if (charset == null) {
            return new TextReadResult(new String(data, StandardCharsets.UTF_8),
                    "编码无法识别，已容错解码（可能有乱码）");
        }
        String text = decode(data, charset);
        return new TextReadResult(text, "文本，编码 " + charset.name());
    }

    // ------------------------------------------------------------------ //
    // 私有小工具
    // ------------------------------------------------------------------ //

    /**
     * 构造系统目录列表：Windows 用环境变量取真实位置（系统盘不一定是 C:）。
     *
     * @return 系统目录列表
     */
    private static List<Path> buildSystemDirs() {
        List<Path> dirs = new ArrayList<>();
        if (IS_WINDOWS) {
            for (String name : List.of("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")) {
                String value = System.getenv(name);
                if (value != null && !value.isBlank()) {
                    dirs.add(Paths.get(value).toAbsolutePath().normalize());
                }
            }
            if (dirs.isEmpty()) {
                dirs.add(Paths.get("C:\\Windows"));
            }
        } else {
            for (String value : List.of("/bin", "/sbin", "/boot", "/dev", "/etc", "/proc",
                    "/sys", "/usr", "/System", "/Library")) {
                dirs.add(Paths.get(value));
            }
        }
        return List.copyOf(dirs);
    }

    /**
     * 剥掉路径首尾的空格、单引号与双引号。
     *
     * @param text 原始文本
     * @return 清理后的文本
     */
    private static String stripQuotes(String text) {
        String result = text.strip();
        while (result.length() >= 2
                && ((result.startsWith("\"") && result.endsWith("\""))
                || (result.startsWith("'") && result.endsWith("'")))) {
            result = result.substring(1, result.length() - 1).strip();
        }
        return result;
    }

    /**
     * 把路径转成用于前缀比较的字符串：绝对、规范、Windows 下转小写。
     *
     * @param path 任意路径
     * @return 归一化后的字符串
     */
    private static String normalizeForCompare(Path path) {
        String text = path.toAbsolutePath().normalize().toString();
        return IS_WINDOWS ? text.toLowerCase(Locale.ROOT) : text;
    }

    /**
     * 判断字节数组是否以 UTF-8 BOM（EF BB BF）开头。
     *
     * @param data 文件字节
     * @return true 表示带 BOM
     */
    private static boolean hasUtf8Bom(byte[] data) {
        return data.length >= 3
                && (data[0] & 0xFF) == 0xEF
                && (data[1] & 0xFF) == 0xBB
                && (data[2] & 0xFF) == 0xBF;
    }

    /**
     * 用指定编码严格解码；遇到非法字节返回 false 而不是抛异常。
     *
     * @param data    原始字节
     * @param charset 候选编码
     * @return true 表示整份数据都能按该编码解码
     */
    private static boolean canDecode(byte[] data, Charset charset) {
        CharsetDecoder decoder = charset.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT);
        try {
            decoder.decode(ByteBuffer.wrap(data));
            return true;
        } catch (CharacterCodingException e) {
            return false;
        }
    }

    /**
     * 按指定编码解码，并剥掉开头的 UTF-8 BOM 字符。
     *
     * @param data    原始字节
     * @param charset 编码
     * @return 解码后的文本
     */
    private static String decode(byte[] data, Charset charset) {
        String text = new String(data, charset);
        if (!text.isEmpty() && text.charAt(0) == '\uFEFF') {
            return text.substring(1);
        }
        return text;
    }

    /**
     * 把「后缀 -> 后缀计数」按数量倒序转成一行中文说明。
     *
     * @param counts 后缀计数（保持插入顺序）
     * @param limit  最多展示几项
     * @return 例如 ".md 8，.txt 3"；空时为 "无"
     */
    public static String topSuffixSummary(Map<String, Integer> counts, int limit) {
        return counts.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .limit(limit)
                .map(entry -> entry.getKey() + " " + entry.getValue())
                .reduce((left, right) -> left + "，" + right)
                .orElse("无");
    }

    /**
     * 创建一个「保持插入顺序」的后缀计数表。
     *
     * @return 可变的有序 Map
     */
    public static Map<String, Integer> newSuffixCounter() {
        return new LinkedHashMap<>();
    }
}
