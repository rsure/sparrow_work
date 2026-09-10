// 模块说明：技能管理业务实现（对应 Python 侧 app/skills/registry.py + app/skills/loader.py）。
//
// 技能本质是磁盘上的 SKILL.md：frontmatter 提供元信息，正文是给模型的操作说明。
// 本类负责「扫描目录 → 解析 → 缓存 → 合并启停开关 → 输出快照」，
// 刷新时机与 Python 侧一致：首次读取、手动 reload、设置变化后的惰性刷新。
package com.example.backendjava.service.impl;

// 第三方（Spring）：声明为本服务的 Bean 实现
import org.springframework.stereotype.Service;
// 第三方（SnakeYAML）：frontmatter 的 YAML 解析
import org.yaml.snakeyaml.Yaml;
// 第三方（SnakeYAML）：YAML 解析选项（本工程不需要任何特殊选项）
import org.yaml.snakeyaml.LoaderOptions;
// 第三方（SnakeYAML）：安全构造器，只允许标准类型，避免加载任意 Java 类
import org.yaml.snakeyaml.constructor.SafeConstructor;

// 标准库：IOException 表示文件读取/目录创建失败
import java.io.IOException;
// 标准库：StandardCharsets 明确按 UTF-8 读取 SKILL.md
import java.nio.charset.StandardCharsets;
// 标准库：Files 读写文件与遍历目录
import java.nio.file.Files;
// 标准库：InvalidPathException 表示设置里的额外目录不是合法路径
import java.nio.file.InvalidPathException;
// 标准库：Path 路径对象
import java.nio.file.Path;
// 标准库：Paths 字符串转 Path
import java.nio.file.Paths;
// 标准库：ArrayList 收集技能与错误
import java.util.ArrayList;
// 标准库：Comparator 按名字排序
import java.util.Comparator;
// 标准库：HashSet 检测同名技能
import java.util.HashSet;
// 标准库：LinkedHashMap 保持快照字段顺序
import java.util.LinkedHashMap;
// 标准库：LinkedHashSet 目录去重并保持顺序
import java.util.LinkedHashSet;
// 标准库：List 技能列表
import java.util.List;
// 标准库：Locale 小写转换
import java.util.Locale;
// 标准库：Map 动态快照
import java.util.Map;
// 标准库：Set 禁用名单
import java.util.Set;
// 标准库：TreeSet 让禁用名单稳定排序
import java.util.TreeSet;
// 标准库：Pattern 解析 frontmatter 与校验技能名
import java.util.regex.Matcher;
import java.util.regex.Pattern;

// 项目内：设置注册表（读取 skill.* 设置项）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：技能业务接口（本类实现它）
import com.example.backendjava.service.SkillService;

/**
 * 技能注册表实现。
 */
@Service
public class SkillServiceImpl implements SkillService {

    /** 技能清单文件名：与社区约定一致，大小写敏感。 */
    private static final String SKILL_FILENAME = "SKILL.md";

    /** 技能名允许的字符：小写字母数字 + 连字符/下划线，最长 64。 */
    private static final Pattern NAME_PATTERN =
            Pattern.compile("^[a-z0-9][a-z0-9_-]{0,63}$");

    /** frontmatter 匹配：文件开头必须是单独一行 ---，中间是 YAML，再以 --- 结束。 */
    private static final Pattern FRONTMATTER_PATTERN =
            Pattern.compile("^---\\s*\\n(.*?)\\n---\\s*(?:\\n|$)", Pattern.DOTALL);

    /** 技能正文最多注入多少字符：防止巨型 SKILL.md 把上下文吃光。 */
    private static final int MAX_BODY_CHARS = 20_000;

    /** 设置注册表：技能目录、总开关与禁用名单的唯一数据来源。 */
    private final SettingsRegistry settingsRegistry;

    /** 保护注册表状态（工具层可能在其它线程里读取）。 */
    private final Object lock = new Object();

    /** 已解析成功的技能：技能名 → 技能对象。 */
    private Map<String, SkillSpec> specs = new LinkedHashMap<>();

    /** 解析失败的 SKILL.md（路径 + 原因），随列表一起下发给前端。 */
    private List<SkillLoadError> errors = new ArrayList<>();

    /** 本次实际扫描的目录（用户经常「放错地方」，把目录回显出来最省事）。 */
    private List<Path> scannedDirs = new ArrayList<>();

    /** 上次刷新时的设置指纹：用于惰性判断「目录/禁用名单是否变了」。 */
    private String signature = "";

    /** 是否已经扫描过（避免「零个技能」时每次都重扫）。 */
    private boolean loaded = false;

    /**
     * 构造器注入设置注册表。
     *
     * @param settingsRegistry 设置注册表
     */
    public SkillServiceImpl(SettingsRegistry settingsRegistry) {
        this.settingsRegistry = settingsRegistry;
    }

    /**
     * 返回技能清单与扫描状态。
     *
     * @return 形如 {"enabled","disabled","dirs","skills","errors"} 的快照
     */
    @Override
    public synchronized Map<String, Object> snapshot() {
        ensureLoaded();
        return snapshotInternal();
    }

    /**
     * 重新扫描技能目录并返回最新快照。
     *
     * @return 重载后的快照
     */
    @Override
    public synchronized Map<String, Object> reload() {
        List<Path> dirs = resolveDirs();
        Set<String> disabled = disabledNames();
        String newSignature = signatureOf(dirs, disabled);

        // 用户级目录不存在时自动创建：让「把技能放进去」这件事有明确落点
        try {
            Files.createDirectories(defaultSkillsDir());
        } catch (IOException ignored) {
            // 没有写权限也不该让功能崩掉：只是这个目录扫不到而已
        }

        List<SkillSpec> found = new ArrayList<>();
        List<SkillLoadError> loadErrors = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Path root : dirs) {
            if (!Files.isDirectory(root)) {
                continue;
            }
            // 只扫一层：root/*/SKILL.md
            for (Path child : listChildrenSorted(root)) {
                if (!Files.isDirectory(child)) {
                    continue;
                }
                Path skillFile = child.resolve(SKILL_FILENAME);
                if (!Files.isRegularFile(skillFile)) {
                    continue;
                }
                SkillSpec spec;
                try {
                    spec = parseSkillFile(skillFile);
                } catch (SkillFormatException e) {
                    loadErrors.add(new SkillLoadError(skillFile, e.getMessage()));
                    continue;
                }
                if (!seen.add(spec.name())) {
                    loadErrors.add(new SkillLoadError(
                            skillFile,
                            "技能名 '" + spec.name() + "' 与前面的目录重复，本条已忽略"
                    ));
                    continue;
                }
                found.add(spec);
            }
        }
        found.sort(Comparator.comparing(SkillSpec::name));

        Map<String, SkillSpec> newSpecs = new LinkedHashMap<>();
        for (SkillSpec spec : found) {
            newSpecs.put(spec.name(), spec);
        }
        specs = newSpecs;
        errors = loadErrors;
        scannedDirs = new ArrayList<>(dirs);
        signature = newSignature;
        loaded = true;
        return snapshotInternal();
    }

    /**
     * 读取某个技能的完整正文。
     *
     * @param name 技能名
     * @return 形如 {"name","description","tools","body","path","enabled"} 的详情；不存在时返回 null
     */
    @Override
    public Map<String, Object> getSkill(String name) {
        ensureLoaded();
        SkillSpec spec;
        synchronized (lock) {
            spec = specs.get(name);
        }
        if (spec == null) {
            return null;
        }
        Map<String, Object> payload = spec.toMap(!disabledNames().contains(spec.name()));
        // 详情接口才返回正文（列表接口刻意不带，避免几十个技能一次塞满响应）
        payload.put("body", spec.body());
        return payload;
    }

    /**
     * 确保注册表已填充；设置变化后自动重扫（惰性刷新）。
     */
    private synchronized void ensureLoaded() {
        if (!loaded) {
            reload();
            return;
        }
        // 锁外读取设置再比较签名：reload 内部会重新取锁
        String current = signatureOf(resolveDirs(), disabledNames());
        if (!current.equals(signature)) {
            reload();
        }
    }

    /**
     * 拼出当前快照（调用方已持有本对象锁）。
     *
     * @return 快照
     */
    private Map<String, Object> snapshotInternal() {
        Set<String> disabled = disabledNames();
        List<SkillSpec> ordered;
        List<SkillLoadError> errorCopy;
        List<Path> dirCopy;
        synchronized (lock) {
            ordered = new ArrayList<>(specs.values());
            ordered.sort(Comparator.comparing(SkillSpec::name));
            errorCopy = new ArrayList<>(errors);
            dirCopy = new ArrayList<>(scannedDirs);
        }

        List<Map<String, Object>> skillList = new ArrayList<>(ordered.size());
        for (SkillSpec spec : ordered) {
            skillList.add(spec.toMap(!disabled.contains(spec.name())));
        }
        List<Map<String, Object>> errorList = new ArrayList<>(errorCopy.size());
        for (SkillLoadError error : errorCopy) {
            errorList.add(error.toMap());
        }
        List<String> dirTexts = new ArrayList<>(dirCopy.size());
        for (Path dir : dirCopy) {
            dirTexts.add(dir.toString());
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("skills", skillList);
        result.put("errors", errorList);
        result.put("dirs", dirTexts);
        result.put("enabled", isGloballyEnabled());
        result.put("disabled", new ArrayList<>(disabled));
        return result;
    }

    /**
     * 解析一个 SKILL.md。
     *
     * @param skillFile SKILL.md 路径
     * @return 技能对象
     * @throws SkillFormatException 缺 frontmatter / name 非法 / 缺 description / 正文为空
     */
    private SkillSpec parseSkillFile(Path skillFile) {
        String raw;
        try {
            raw = Files.readString(skillFile, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new SkillFormatException("读取失败：" + e.getMessage());
        }

        Matcher matcher = FRONTMATTER_PATTERN.matcher(raw);
        if (!matcher.find()) {
            throw new SkillFormatException("缺少 frontmatter（文件开头需要 --- 包裹的元数据块）");
        }

        Map<?, ?> meta;
        try {
            // SafeConstructor 只认标准 YAML 类型，不会实例化任意类
            Yaml yaml = new Yaml(new SafeConstructor(new LoaderOptions()));
            Object loadedMeta = yaml.load(matcher.group(1));
            if (loadedMeta == null) {
                meta = Map.of();
            } else if (loadedMeta instanceof Map<?, ?> map) {
                meta = map;
            } else {
                throw new SkillFormatException("frontmatter 必须是键值对");
            }
        } catch (SkillFormatException e) {
            throw e;
        } catch (RuntimeException e) {
            throw new SkillFormatException("frontmatter 不是合法 YAML：" + e.getMessage());
        }

        String name = textOf(meta.get("name"));
        if (!NAME_PATTERN.matcher(name).matches()) {
            throw new SkillFormatException(
                    "name 非法（'" + name + "'）：只允许小写字母/数字/连字符/下划线，且不超过 64 字符"
            );
        }

        String description = textOf(meta.get("description"));
        if (description.isEmpty()) {
            throw new SkillFormatException("缺少 description（模型靠它判断什么时候用这个技能）");
        }

        List<String> tools = parseTools(meta.get("tools"));

        String body = raw.substring(matcher.end()).strip();
        if (body.isEmpty()) {
            throw new SkillFormatException("正文为空（没有操作说明，技能无法执行）");
        }
        if (body.length() > MAX_BODY_CHARS) {
            // 截断而不是报错：宁可少读一点，也不要让用户因为「写太长」而完全用不了
            body = body.substring(0, MAX_BODY_CHARS) + "\n\n…（技能正文过长，已截断）";
        }

        double mtime;
        try {
            mtime = Files.getLastModifiedTime(skillFile).toMillis() / 1000.0;
        } catch (IOException e) {
            mtime = 0.0;
        }
        return new SkillSpec(
                name,
                description,
                tools,
                body,
                skillFile.toAbsolutePath().normalize(),
                mtime
        );
    }

    /**
     * 解析 tools 声明：既允许 YAML 列表，也允许逗号分隔字符串。
     *
     * @param raw 原始值
     * @return 工具名列表
     * @throws SkillFormatException 类型不合法
     */
    private List<String> parseTools(Object raw) {
        List<String> tools = new ArrayList<>();
        if (raw == null) {
            return tools;
        }
        if (raw instanceof String text) {
            // 允许写成 "read_file, grep_files"，省去用户记 YAML 列表语法的负担
            for (String item : text.split(",")) {
                String trimmed = item.strip();
                if (!trimmed.isEmpty()) {
                    tools.add(trimmed);
                }
            }
            return tools;
        }
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                String text = textOf(item);
                if (!text.isEmpty()) {
                    tools.add(text);
                }
            }
            return tools;
        }
        throw new SkillFormatException("tools 必须是列表（或逗号分隔的字符串）");
    }

    /**
     * 算出本次要扫描的目录：用户级默认目录优先，再追加设置里的额外目录。
     *
     * @return 去重后的目录列表
     */
    private List<Path> resolveDirs() {
        List<Path> dirs = new ArrayList<>();
        dirs.add(defaultSkillsDir());
        Object extra = readSetting("skill.dirs", List.of());
        if (extra instanceof List<?> items) {
            for (Object item : items) {
                String text = item == null ? "" : String.valueOf(item).strip();
                if (text.isEmpty()) {
                    continue;
                }
                try {
                    dirs.add(Paths.get(expandUser(text)));
                } catch (InvalidPathException ignored) {
                    // 设置里写了非法路径：跳过，不让整次扫描失败
                }
            }
        }
        // 去重（保持顺序）：同一目录写两次不该扫两遍
        return new ArrayList<>(new LinkedHashSet<>(dirs));
    }

    /**
     * 返回用户级技能目录（Windows/macOS/Linux 各自的用户数据目录）。
     *
     * @return 技能根目录
     */
    private Path defaultSkillsDir() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        String home = System.getProperty("user.home", ".");
        Path base;
        if (os.contains("win")) {
            String appData = System.getenv("APPDATA");
            base = appData == null || appData.isBlank()
                    ? Paths.get(home, "AppData", "Roaming")
                    : Paths.get(appData);
        } else if (os.contains("mac")) {
            base = Paths.get(home, "Library", "Application Support");
        } else {
            String xdg = System.getenv("XDG_CONFIG_HOME");
            base = xdg == null || xdg.isBlank()
                    ? Paths.get(home, ".config")
                    : Paths.get(xdg);
        }
        return base.resolve("app-backend").resolve("skills");
    }

    /**
     * 读出被禁用的技能名集合（设置键 skill.disabled）。
     *
     * @return 排序后的禁用名单
     */
    private Set<String> disabledNames() {
        Object raw = readSetting("skill.disabled", List.of());
        Set<String> result = new TreeSet<>();
        if (raw instanceof List<?> items) {
            for (Object item : items) {
                String text = item == null ? "" : String.valueOf(item).strip();
                if (!text.isEmpty()) {
                    result.add(text);
                }
            }
        }
        return result;
    }

    /**
     * 技能系统总开关（设置键 skill.enabled），默认开启。
     *
     * @return true 表示开启
     */
    private boolean isGloballyEnabled() {
        Object raw = readSetting("skill.enabled", Boolean.TRUE);
        if (raw instanceof Boolean value) {
            return value;
        }
        return raw == null || Boolean.parseBoolean(String.valueOf(raw));
    }

    /**
     * 计算「影响技能集合」的设置指纹（目录 + 禁用名单）。
     *
     * @param dirs     扫描目录
     * @param disabled 禁用名单
     * @return 可比较的字符串
     */
    private String signatureOf(List<Path> dirs, Set<String> disabled) {
        StringBuilder builder = new StringBuilder();
        for (Path dir : dirs) {
            builder.append(dir).append('\n');
        }
        builder.append("--disabled--\n");
        for (String name : disabled) {
            builder.append(name).append('\n');
        }
        return builder.toString();
    }

    /**
     * 读取一个设置项；设置库未就绪或键未声明时返回默认值。
     *
     * @param key          设置键
     * @param defaultValue 默认值
     * @return 设置值或默认值
     */
    private Object readSetting(String key, Object defaultValue) {
        try {
            Object value = settingsRegistry.getSetting(key);
            return value == null ? defaultValue : value;
        } catch (RuntimeException e) {
            return defaultValue;
        }
    }

    /**
     * 列出目录下的子项并按键名升序排序（大小写不敏感）。
     *
     * @param root 目录
     * @return 子项列表；读取失败时为空列表
     */
    private List<Path> listChildrenSorted(Path root) {
        List<Path> children = new ArrayList<>();
        try (var stream = Files.newDirectoryStream(root)) {
            for (Path child : stream) {
                children.add(child);
            }
        } catch (IOException | SecurityException e) {
            return children;
        }
        children.sort(Comparator.comparing(
                path -> path.getFileName().toString().toLowerCase(Locale.ROOT)
        ));
        return children;
    }

    /**
     * 展开路径开头的 ~ 为用户主目录。
     *
     * @param text 原始路径
     * @return 展开后的路径
     */
    private String expandUser(String text) {
        if (text.equals("~") || text.startsWith("~/") || text.startsWith("~\\")) {
            return System.getProperty("user.home", "") + text.substring(1);
        }
        return text;
    }

    /**
     * 把任意值安全转成去空白的字符串。
     *
     * @param value 原始值
     * @return 字符串；null 转成空串
     */
    private String textOf(Object value) {
        return value == null ? "" : String.valueOf(value).strip();
    }

    /**
     * 一个已解析的技能。
     *
     * @param name        技能唯一 id（小写 kebab-case）
     * @param description 一句话说明：进系统提示词，模型据此判断何时调用
     * @param tools       该技能声明会用到的底层工具名（仅声明与展示）
     * @param body        技能正文（给模型的操作说明）
     * @param path        SKILL.md 的绝对路径
     * @param mtime       文件修改时间（单位：秒）
     */
    private record SkillSpec(
            // 技能名
            String name,
            // 一句话说明
            String description,
            // 声明的工具名
            List<String> tools,
            // 正文
            String body,
            // SKILL.md 路径
            Path path,
            // 修改时间（秒）
            double mtime
    ) {

        /**
         * 转成接口/前端使用的字典（不含正文）。
         *
         * @param enabled 该技能当前是否启用
         * @return 可 JSON 序列化的字典
         */
        Map<String, Object> toMap(boolean enabled) {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("name", name);
            map.put("description", description);
            map.put("tools", tools);
            map.put("path", path.toString());
            map.put("mtime", mtime);
            map.put("enabled", enabled);
            // 正文长度给前端一个「这份技能有多长」的直觉，正文本身走详情接口
            map.put("body_chars", body.length());
            return map;
        }
    }

    /**
     * 一条加载失败记录。
     *
     * @param path   出问题的 SKILL.md 路径
     * @param reason 人类可读的失败原因
     */
    private record SkillLoadError(
            // SKILL.md 路径
            Path path,
            // 失败原因
            String reason
    ) {

        /**
         * 转成可 JSON 序列化的字典。
         *
         * @return 含 path / reason 的字典
         */
        Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("path", path.toString());
            map.put("reason", reason);
            return map;
        }
    }

    /**
     * SKILL.md 格式不合法（缺 frontmatter、name 非法、缺 description 等）。
     */
    private static final class SkillFormatException extends RuntimeException {

        /**
         * 创建格式异常。
         *
         * @param message 人类可读的原因
         */
        private SkillFormatException(String message) {
            super(message);
        }
    }
}
