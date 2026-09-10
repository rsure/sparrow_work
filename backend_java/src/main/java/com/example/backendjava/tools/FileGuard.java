// 模块说明：写前校验（对应 Python app/tools/file_guard.py）。
//
// 解决的问题：子任务 A 读了 x.py，子任务 B 改了 x.py，A 再按记忆里的旧内容整份写回，
// B 的改动就被静默覆盖。做法是乐观锁：
//   read_file 成功后登记 (会话, 路径) -> 内容哈希；
//   write_file / edit_file 写入前比对磁盘当前哈希，不一致就拒绝并提示重新读取。
package com.example.backendjava.tools;

// 标准库：MessageDigest 计算 SHA-256 内容指纹
import java.security.MessageDigest;
// 标准库：NoSuchAlgorithmException 表示 JVM 缺少 SHA-256（正常不会发生）
import java.security.NoSuchAlgorithmException;
// 标准库：IOException 表示读取文件失败
import java.io.IOException;
// 标准库：Files 读取文件字节
import java.nio.file.Files;
// 标准库：Path 文件路径
import java.nio.file.Path;
// 标准库：LinkedHashMap 保持插入顺序，便于淘汰最旧条目
import java.util.LinkedHashMap;
// 标准库：Map 保存登记表
import java.util.Map;

/**
 * 读后写校验（乐观锁）。
 *
 * <p>登记表放在进程内：单机桌面应用够用，不需要落库。</p>
 */
public final class FileGuard {

    /** 登记表最多保留多少条；超出后淘汰最早插入的一项。 */
    private static final int MAX_ENTRIES = 500;

    /** 登记表：(会话 id + "|" + 绝对路径) -> 内容 SHA-256。 */
    private static final Map<String, String> SNAPSHOTS =
            new LinkedHashMap<>(16, 0.75f, false);

    /** 工具类禁止实例化。 */
    private FileGuard() {
    }

    /**
     * 登记「这个会话读过这个文件（当时的内容指纹）」。
     *
     * <p>失败静默：登记不上最多是少一层保护，不能让读文件失败。</p>
     *
     * @param sessionId 会话 id；空串表示不在对话里，直接忽略
     * @param path      文件路径
     */
    public static void recordRead(String sessionId, Path path) {
        if (sessionId == null || sessionId.isEmpty()) {
            return;
        }
        String hash = contentHash(path);
        if (hash == null) {
            return;
        }
        remember(key(sessionId, path), hash);
    }

    /**
     * 写入前校验：磁盘内容是否在本会话读取之后被改过。
     *
     * @param sessionId 会话 id
     * @param path      目标文件
     * @param enabled   是否开启写前校验（来自设置 task.write_stale_guard）
     * @return null 表示可以写；字符串表示拒绝原因（直接作为 FAIL 文案）
     */
    public static String checkWrite(String sessionId, Path path, boolean enabled) {
        if (sessionId == null || sessionId.isEmpty() || !enabled) {
            return null;
        }
        if (!Files.exists(path)) {
            // 新建文件不存在「覆盖别人改动」的问题
            return null;
        }
        String key = key(sessionId, path);
        String known;
        synchronized (SNAPSHOTS) {
            known = SNAPSHOTS.get(key);
        }
        if (known == null) {
            // 没读过：不做「未读先写」的强制（见模块说明），放行
            return null;
        }
        String current = contentHash(path);
        if (current == null || current.equals(known)) {
            return null;
        }
        return "文件在读取之后已被修改：" + path + "。为避免覆盖别人的改动，本次写入已拒绝。"
                + "请先用 read_file 重新读取最新内容，再决定怎么写。";
    }

    /**
     * 写入成功后更新登记（这样紧接着的第二次写入不会被自己误判为「被改过」）。
     *
     * @param sessionId 会话 id
     * @param path      目标文件
     */
    public static void recordWrite(String sessionId, Path path) {
        if (sessionId == null || sessionId.isEmpty()) {
            return;
        }
        String hash = contentHash(path);
        if (hash != null) {
            remember(key(sessionId, path), hash);
        }
    }

    /**
     * 计算文件的 SHA-256；读不到（不存在/无权限）时返回 null。
     *
     * @param path 文件路径
     * @return 十六进制摘要或 null
     */
    public static String contentHash(Path path) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            // 分块读：大文件也不至于把内存打满
            try (var in = Files.newInputStream(path)) {
                byte[] buffer = new byte[1 << 20];
                int read;
                while ((read = in.read(buffer)) >= 0) {
                    if (read > 0) {
                        digest.update(buffer, 0, read);
                    }
                }
            }
            byte[] bytes = digest.digest();
            StringBuilder hex = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (IOException | NoSuchAlgorithmException e) {
            return null;
        }
    }

    /**
     * 清空登记表（仅测试用：用例之间不能互相继承状态）。
     */
    public static void resetForTest() {
        synchronized (SNAPSHOTS) {
            SNAPSHOTS.clear();
        }
    }

    /**
     * 生成登记表的键：路径统一成绝对路径字符串。
     *
     * @param sessionId 会话 id
     * @param path      文件路径
     * @return 登记键
     */
    private static String key(String sessionId, Path path) {
        Path resolved;
        try {
            resolved = path.toRealPath();
        } catch (IOException e) {
            resolved = path.toAbsolutePath().normalize();
        }
        return sessionId + "|" + resolved;
    }

    /**
     * 写入登记表并维护淘汰顺序。
     *
     * @param key  登记键
     * @param hash 内容哈希
     */
    private static void remember(String key, String hash) {
        synchronized (SNAPSHOTS) {
            // 重新插入到末尾：表示「最近使用」，避免长期活跃的文件被先淘汰
            SNAPSHOTS.remove(key);
            SNAPSHOTS.put(key, hash);
            while (SNAPSHOTS.size() > MAX_ENTRIES) {
                String oldest = SNAPSHOTS.keySet().iterator().next();
                SNAPSHOTS.remove(oldest);
            }
        }
    }
}
