// 模块说明：父进程守护。Electron 被强杀时，通过 stdin 管道关闭感知并让 Java 后端自行退出。
package com.example.backendjava.config;

// Spring Boot 启动完成回调：容器就绪后执行一次，不阻塞主启动流程
import org.springframework.boot.ApplicationRunner;
// Spring Boot 启动参数：ApplicationRunner.run() 的形参类型
import org.springframework.boot.ApplicationArguments;
// Spring 组件注解：把本类注册成 Bean，ApplicationRunner 会被自动调用
import org.springframework.stereotype.Component;

/**
 * 父进程守护线程。
 *
 * <p>Electron 主进程启动后端时会设置 {@code APP_PARENT_GUARD=1}，并持续向子进程 stdin 写心跳。
 * 当 Electron 正常退出或被任务管理器强杀时，管道关闭，本线程的 {@code System.in.read()}
 * 会返回 -1；此时主动退出 JVM，避免留下占着 8000 端口的孤儿进程。</p>
 *
 * <p>开发态直接用 {@code mvn spring-boot:run} 启动时没有该环境变量，本线程不会启动。</p>
 */
@Component
public class ParentProcessGuard implements ApplicationRunner {

    /**
     * 容器启动完成后检查是否需要开启守护线程。
     *
     * @param args Spring 解析后的启动参数，本类不使用
     */
    @Override
    public void run(ApplicationArguments args) {
        // 只有 Electron 注入该变量时才启用；否则 stdin 可能是终端，读阻塞没有意义
        if (!"1".equals(System.getenv("APP_PARENT_GUARD"))) {
            return;
        }

        // 守护线程：不阻止 JVM 正常退出；它的唯一职责是等待 stdin EOF
        Thread guard = new Thread(() -> {
            try {
                // read() 每收到一个心跳字节就返回一次；管道关闭时返回 -1
                while (System.in.read() != -1) {
                    // 收到心跳，父进程仍在，继续等待下一个字节
                }
            } catch (Exception ignored) {
                // 读 stdin 出错通常也意味着父进程已消失，直接走退出逻辑
            }
            // 父进程消失：立即结束进程，释放端口与数据库连接
            System.out.println("[backend-java] 检测到父进程退出，后端自行关闭");
            System.exit(0);
        }, "parent-process-guard");

        // 设为守护线程，避免它单独撑住 JVM 生命周期
        guard.setDaemon(true);
        guard.start();
    }
}
