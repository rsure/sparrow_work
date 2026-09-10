// 模块说明：tools 包的纯函数与安全护栏单元测试。
//
// 这些用例不启动 Spring，只验证迁移后最容易出错、也最不该出错的部分：
// 路径拒绝、glob 语义、只读 SQL 校验、命令允许列表、SSRF 拦截、读后写校验。
package com.example.backendjava.tools;

// 项目内：glob 工具（验证 ** / * 的匹配语义）
import com.example.backendjava.tools.file.GlobTool;
// 项目内：命令执行工具（验证允许列表与禁用参数）
import com.example.backendjava.tools.exec.RunCommandTool;
// 项目内：联网护栏（验证 SSRF 拦截）
import com.example.backendjava.tools.net.NetGuard;
// 项目内：SQLite 查询工具（验证只读 SQL 校验）
import com.example.backendjava.tools.sql.SqlQueryTool;

// 标准库：Files 修改临时文件内容
import java.nio.file.Files;
// 标准库：Path 临时文件路径
import java.nio.file.Path;
// 标准库：List 命令参数
import java.util.List;
// 测试框架：JUnit 5 断言
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
// 测试框架：JUnit 5 测试方法标记
import org.junit.jupiter.api.Test;
// 测试框架：JUnit 5 临时目录（用例结束自动清理）
import org.junit.jupiter.api.io.TempDir;

/**
 * tools 核心逻辑的单元测试。
 */
class ToolsCoreTest {

    /**
     * 相对路径必须被拒绝：这是所有工具的共同前提。
     */
    @Test
    void resolveAbsPathRejectsRelativePath() {
        assertThrows(IllegalArgumentException.class, () -> ToolUtils.resolveAbsPath("docs"));
    }

    /**
     * 系统目录必须被拒绝（Windows 用 SystemRoot，类 Unix 用 /etc）。
     */
    @Test
    void resolveAbsPathRejectsSystemDirectory() {
        String systemDir = ToolUtils.IS_WINDOWS ? System.getenv("SystemRoot") : "/etc";
        if (systemDir != null && !systemDir.isBlank()) {
            assertThrows(SecurityException.class, () -> ToolUtils.resolveAbsPath(systemDir));
        }
    }

    /**
     * glob 的 ** 要能跨层，* 不能跨层，且大小写不敏感。
     */
    @Test
    void globPatternMatchesNestedPaths() {
        var nested = GlobTool.globToPattern("**/*.vue");
        assertTrue(nested.matcher("src/components/App.vue").matches());
        assertTrue(nested.matcher("App.vue").matches());
        assertTrue(nested.matcher("SRC/App.VUE").matches());
        assertTrue(!nested.matcher("src/App.ts").matches());

        var currentLevel = GlobTool.globToPattern("*.log");
        assertTrue(currentLevel.matcher("app.log").matches());
        assertTrue(!currentLevel.matcher("logs/app.log").matches());
    }

    /**
     * 只读 SQL：允许单条 SELECT/WITH/EXPLAIN，拒绝多语句与写操作。
     */
    @Test
    void readonlySqlValidation() {
        assertNull(SqlQueryTool.checkReadonlySql("-- 看看用户表\nSELECT 1;"));
        assertNull(SqlQueryTool.checkReadonlySql("WITH t AS (SELECT 1) SELECT * FROM t"));
        assertNotNull(SqlQueryTool.checkReadonlySql("SELECT 1; SELECT 2"));
        assertNotNull(SqlQueryTool.checkReadonlySql("UPDATE users SET name='x'"));
        assertNotNull(SqlQueryTool.checkReadonlySql("WITH t AS (SELECT 1) DELETE FROM users"));
    }

    /**
     * 命令允许列表：放行登记过的子命令，拒绝未知程序、未知子命令与禁用参数。
     */
    @Test
    void commandAllowlistValidation() {
        assertNull(RunCommandTool.checkCommand("git", List.of("status", "--short")));
        assertNotNull(RunCommandTool.checkCommand("rm", List.of()));
        assertNotNull(RunCommandTool.checkCommand("git", List.of("commit")));
        assertNotNull(RunCommandTool.checkCommand("git", List.of("status", "-rf")));
        assertNotNull(RunCommandTool.checkCommand("python", List.of("-c", "print(1)")));
    }

    /**
     * SSRF 护栏：本机、内网、file:// 必须拒绝；公网 IP 放行。
     */
    @Test
    void netGuardBlocksLocalAndPrivateTargets() {
        assertNotNull(NetGuard.checkUrl("http://127.0.0.1:8000/api"));
        assertNotNull(NetGuard.checkUrl("http://192.168.1.10/"));
        assertNotNull(NetGuard.checkUrl("http://169.254.169.254/latest/meta-data/"));
        assertNotNull(NetGuard.checkUrl("file:///etc/passwd"));
        // 公网 IP 不需要 DNS 解析，避免测试依赖网络
        assertNull(NetGuard.checkUrl("https://93.184.216.34/"));
    }

    /**
     * 读后写校验：读取之后文件被改过，再次写入必须被拒绝。
     *
     * @param tempDir JUnit 提供的临时目录
     * @throws Exception 写临时文件失败
     */
    @Test
    void fileGuardDetectsChangesAfterRead(@TempDir Path tempDir) throws Exception {
        Path file = tempDir.resolve("note.txt");
        Files.writeString(file, "first");
        FileGuard.recordRead("session-a", file);
        // 刚读完、内容没变：允许写
        assertNull(FileGuard.checkWrite("session-a", file, true));

        Files.writeString(file, "second");
        // 读后被别人改了：拒绝写
        assertNotNull(FileGuard.checkWrite("session-a", file, true));
        // 关闭写前校验时放行（设置 task.write_stale_guard=false 的行为）
        assertNull(FileGuard.checkWrite("session-a", file, false));
    }

    /**
     * 会话默认值必须是最严格的 ask/main，不能因为没设置就默认放行。
     */
    @Test
    void toolSessionDefaultsToAsk() {
        ToolSession.clear();
        SessionContext context = ToolSession.currentContext();
        assertEquals("ask", context.permissionMode());
        assertEquals(ToolSession.SCOPE_MAIN, context.scope());
        ToolSession.clear();
    }
}
