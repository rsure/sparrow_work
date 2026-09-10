// 模块说明：健康检查业务逻辑。只采集进程与运行时信息，不访问数据库或外部网络。
package com.example.backendjava.service;

// Spring 服务注解：把本类注册成 Bean，供 HealthController 注入
import org.springframework.stereotype.Service;
// 项目内配置：读取 app.name / app.version / app.env
import com.example.backendjava.config.AppProperties;
// 健康检查响应体
import com.example.backendjava.dto.HealthData;

// 标准库：带时区的当前时间，序列化成 ISO-8601
import java.time.OffsetDateTime;
// 标准库：时间格式化器，固定输出到秒
import java.time.format.DateTimeFormatter;

/**
 * 健康检查服务。
 *
 * <p>实现是完整的：Electron 主进程依赖 {@code GET /api/health} 判断后端是否就绪，
 * 因此这个接口必须在 Java 后端启动后立即可用，不能做成待实现的空接口。</p>
 */
@Service
public class HealthService {

    /** 进程启动时刻（单调时钟，单位纳秒）：用于计算 uptime，不受系统时间调整影响。 */
    private static final long STARTED_AT_NANOS = System.nanoTime();

    /** ISO-8601 格式化器：输出形如 2026-10-21T21:30:00+08:00，精确到秒。 */
    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

    /** 应用配置：服务名、版本、环境都从这里读取。 */
    private final AppProperties properties;

    /**
     * 构造器注入配置。
     *
     * @param properties app.* 配置 Bean
     */
    public HealthService(AppProperties properties) {
        this.properties = properties;
    }

    /**
     * 采集当前进程的健康快照。
     *
     * @return 健康检查响应体；当前实现 status 恒为 ok
     */
    public HealthData getHealth() {
        // 单调时钟差值换算成秒；除以 1e9 得到浮点秒数，保留 3 位小数由 String.format 控制
        double uptimeSeconds = (System.nanoTime() - STARTED_AT_NANOS) / 1_000_000_000.0;
        // 平台描述：同时给出操作系统与 JDK 目录，排查“用错 Java 版本”时非常有用
        String platform = System.getProperty("os.name") + " "
                + System.getProperty("os.version") + " ("
                + System.getProperty("java.home") + ")";
        // 当前时间带本机时区；前端直接展示即可
        String serverTime = OffsetDateTime.now().format(TIME_FORMATTER);

        return new HealthData(
                "ok",
                properties.getName(),
                properties.getVersion(),
                properties.getEnv(),
                // Java 后端没有 Python 版本；保留字段是为了兼容旧前端类型
                "N/A",
                platform,
                // 保留 3 位小数，避免前端看到一长串浮点数
                Math.round(uptimeSeconds * 1000.0) / 1000.0,
                serverTime,
                "Java",
                System.getProperty("java.version")
        );
    }
}
