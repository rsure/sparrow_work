// 模块说明：Java 后端的启动入口。只负责启动 Spring 容器与打印启动信息，不写业务逻辑。
package com.example.backendjava;

// Spring Boot 启动器：@SpringBootApplication 组合了配置类、自动配置与组件扫描
import org.springframework.boot.SpringApplication;
// Spring Boot 应用类型：run() 返回 ConfigurableApplicationContext，可用于读取环境信息
import org.springframework.boot.autoconfigure.SpringBootApplication;
// 配置属性绑定：让 AppProperties 上的 @ConfigurationProperties 生效
import org.springframework.boot.context.properties.EnableConfigurationProperties;
// 项目内配置类：集中声明 app.* 配置项
import com.example.backendjava.config.AppProperties;

/**
 * Java 后端启动类。
 *
 * <p>启动方式：</p>
 * <pre>
 *   mvn -f backend_java/pom.xml spring-boot:run
 *   java -jar backend-java.jar
 * </pre>
 *
 * <p>接口统一前缀为 {@code /api}（由 application.yml 的 server.servlet.context-path 提供），
 * 因此健康检查地址是 {@code GET /api/health}，与 Python 后端保持一致。</p>
 */
@SpringBootApplication
@EnableConfigurationProperties(AppProperties.class)
public class BackendJavaApplication {

    /**
     * 进程入口：启动 Spring 容器，并在控制台打印访问地址，方便 Electron 与开发者确认端口。
     *
     * @param args 命令行参数；Spring Boot 会把 --server.port=8000 这类参数当作配置覆盖项
     */
    public static void main(String[] args) {
        // run() 会完成组件扫描、自动配置、内嵌 Tomcat 启动；返回后应用已可接收请求
        var context = SpringApplication.run(BackendJavaApplication.class, args);
        // 从 Environment 读取最终生效的端口，避免用户用 --server.port 覆盖后日志仍打印 8000
        String port = context.getEnvironment().getProperty("local.server.port", "8000");
        // 打印健康检查地址：Electron 主进程正是轮询这个地址判断后端是否就绪
        System.out.printf("[backend-java] 已启动：http://127.0.0.1:%s/api/health%n", port);
    }
}
