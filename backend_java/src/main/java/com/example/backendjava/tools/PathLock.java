// 模块说明：按文件路径加互斥锁（对应 Python app/tools/path_lock.py）。
//
// 并行车道在计划期已经保证「两条道不写同一个文件」，但计划是模型给的，可能漏。
// 再加一把按路径的锁：即使真撞上，也只会串行发生，不会两个线程同时「读原文件 →
// 拼接 → 整份写回」而互相覆盖。
//
// 为什么用 ReentrantLock：同一个工具函数内部可能对同一路径两次取锁（例如先备份再写入），
// 可重入锁才不会自己把自己锁死。引用计数保证锁表不会只增不减。
package com.example.backendjava.tools;

// 标准库：IOException 用于把超时异常包装成 AutoCloseable 可抛出的形式
import java.io.IOException;
// 标准库：Path 表示被锁路径
import java.nio.file.Path;
// 标准库：ConcurrentHashMap 保存路径 -> 锁条目
import java.util.concurrent.ConcurrentHashMap;
// 标准库：TimeUnit 表示等待锁的时间单位
import java.util.concurrent.TimeUnit;
// 标准库：ReentrantLock 可重入的线程锁
import java.util.concurrent.locks.ReentrantLock;

/**
 * 按路径的互斥锁。
 *
 * <p>用法：</p>
 * <pre>{@code
 * try (PathLock.LockHandle ignored = PathLock.lock(path)) {
 *     // 读改写...
 * }
 * }</pre>
 */
public final class PathLock {

    /** 等锁的最长秒数：真死锁时宁愿报错让用户看到，也不要把对话卡死在这里。 */
    public static final long LOCK_TIMEOUT_SECONDS = 30L;

    /** 锁表：规范化路径 -> 锁条目。 */
    private static final ConcurrentHashMap<String, LockEntry> LOCKS = new ConcurrentHashMap<>();

    /** 工具类禁止实例化。 */
    private PathLock() {
    }

    /**
     * 一个路径的锁及其引用计数。
     */
    private static final class LockEntry {
        /** 可重入锁。 */
        private final ReentrantLock lock = new ReentrantLock();
        /** 当前持有/等待这个条目的调用数。 */
        private int refs;
    }

    /**
     * 锁句柄：关闭时自动释放锁；必须在 try-with-resources 中使用。
     */
    public static final class LockHandle implements AutoCloseable {

        /** 锁表里的规范化键。 */
        private final String key;

        /** 本次获取的锁条目。 */
        private final LockEntry entry;

        /**
         * 构造句柄。
         *
         * @param key   锁表键
         * @param entry 锁条目
         */
        private LockHandle(String key, LockEntry entry) {
            this.key = key;
            this.entry = entry;
        }

        /**
         * 释放锁并归还引用计数；重复调用是安全的。
         *
         * @throws IOException 不会真正抛出，签名只是为了配合 try-with-resources 的通用写法
         */
        @Override
        public void close() throws IOException {
            entry.lock.unlock();
            releaseEntry(key, entry);
        }
    }

    /**
     * 独占某个文件路径；关闭返回的句柄时自动释放。
     *
     * @param path 要独占的路径（文件或目录都可以，锁粒度只到「这个路径字符串」）
     * @return 锁句柄（AutoCloseable）
     * @throws IllegalStateException 等锁超过 {@link #LOCK_TIMEOUT_SECONDS} 秒
     */
    public static LockHandle lock(Path path) {
        String key = lockKey(path);
        LockEntry entry = acquireEntry(key);
        try {
            boolean acquired = entry.lock.tryLock(LOCK_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!acquired) {
                throw new IllegalStateException(
                        "等待文件锁超时（" + LOCK_TIMEOUT_SECONDS + "s）：" + path);
            }
        } catch (InterruptedException e) {
            // 恢复中断标记：上层（工具循环）可能据此取消本次任务
            Thread.currentThread().interrupt();
            releaseEntry(key, entry);
            throw new IllegalStateException("等待文件锁时线程被中断：" + path, e);
        } catch (RuntimeException e) {
            releaseEntry(key, entry);
            throw e;
        }
        return new LockHandle(key, entry);
    }

    /**
     * 把路径规范成锁表里的键（统一分隔符与大小写）。
     *
     * @param path 原始路径
     * @return 规范化后的键
     */
    public static String lockKey(Path path) {
        String text = path.toAbsolutePath().normalize().toString();
        return ToolUtils.IS_WINDOWS ? text.toLowerCase(java.util.Locale.ROOT) : text;
    }

    /**
     * 取出（必要时创建）某个路径的锁条目，并给它 +1 引用。
     *
     * @param key 锁表键
     * @return 锁条目
     */
    private static LockEntry acquireEntry(String key) {
        // 用 compute 把「取/建条目」与「引用计数 +1」合成一个原子操作：
        // 如果分成 get + synchronized，另一个线程刚好在中间把计数减到 0 并删表，
        // 就会出现「两个人各拿一把锁锁同一个文件」的竞态。
        return LOCKS.compute(key, (ignored, existing) -> {
            LockEntry entry = existing == null ? new LockEntry() : existing;
            entry.refs++;
            return entry;
        });
    }

    /**
     * 释放一次引用，引用归零时把该路径的锁从表里删掉。
     *
     * @param key   锁表键
     * @param entry 之前获取的条目
     */
    private static void releaseEntry(String key, LockEntry entry) {
        // 同样用 computeIfPresent：只有当表里还是「自己这一条」时才减计数，
        // 计数归零返回 null，ConcurrentHashMap 会自动删除这个键。
        LOCKS.computeIfPresent(key, (ignored, existing) -> {
            if (existing != entry) {
                return existing;
            }
            existing.refs--;
            return existing.refs <= 0 ? null : existing;
        });
    }

    /**
     * 当前锁表里有多少个路径（仅用于测试与诊断）。
     *
     * @return 锁条目数量
     */
    public static int lockedCount() {
        return LOCKS.size();
    }

    /**
     * 清空锁表（只给测试用：用例之间不能互相继承锁状态）。
     */
    public static void resetForTest() {
        LOCKS.clear();
    }
}
