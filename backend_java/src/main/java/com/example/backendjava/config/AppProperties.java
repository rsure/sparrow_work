// 模块说明：app.* 配置项的 JavaBean。所有字段都可以通过 application.yml 或环境变量覆盖。
package com.example.backendjava.config;

// Spring Boot 配置绑定注解：把 app.xxx 配置项按名称绑定到本类字段
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 应用级配置。
 *
 * <p>对应 application.yml 中的 {@code app:} 节点；环境变量写法为
 * {@code APP_APP_NAME}、{@code APP_VERSION}、{@code APP_ENV}、{@code APP_CORS_ORIGINS}、
 * {@code APP_CHECKPOINT_DB_PATH}（Spring 的宽松绑定会把短横线转成下划线）。</p>
 */
@ConfigurationProperties(prefix = "app")
public class AppProperties {

    /** 服务名：会出现在 /api/health 响应里，用于区分当前连的是哪个后端（Java 或 Python）。 */
    private String name = "vue3-electron-fastapi-java";

    /** 服务版本号：仅用于展示与排查版本不一致，不与 pom.xml 自动同步。 */
    private String version = "0.1.0";

    /** 运行环境：development=开发 / production=生产，会影响日志级别与错误详情展示。 */
    private String env = "development";

    /**
     * 允许跨域的来源，逗号分隔；星号表示允许所有来源。
     *
     * <p>本项目是单机桌面应用，开发态前端跑在 5173，打包后页面是 file://（Origin 为 null），
     * 所以默认放开所有来源。生产化时应改成明确白名单。</p>
     */
    private String corsOrigins = "*";

    /**
     * LangGraph4j 检查点数据库路径（SQLite 文件）。
     *
     * <p>默认与业务库共用 app.db；检查点会自己建表，与业务表互不冲突。
     * 改成单独文件（如 checkpoints.db）可以避免业务迁移与检查点表混在一起。</p>
     */
    private String checkpointDbPath = "app.db";

    /** 返回服务名；Spring 配置绑定与 HealthService 都会调用。 */
    public String getName() {
        return name;
    }

    /** 设置服务名；对应 app.name。 */
    public void setName(String name) {
        this.name = name;
    }

    /** 返回版本号；用于健康检查与诊断信息。 */
    public String getVersion() {
        return version;
    }

    /** 设置版本号；对应 app.version。 */
    public void setVersion(String version) {
        this.version = version;
    }

    /** 返回运行环境标识；用于健康检查与日志。 */
    public String getEnv() {
        return env;
    }

    /** 设置运行环境标识；对应 app.env。 */
    public void setEnv(String env) {
        this.env = env;
    }

    /** 返回跨域来源配置；CorsConfig 会解析它。 */
    public String getCorsOrigins() {
        return corsOrigins;
    }

    /** 设置跨域来源配置；支持逗号分隔或单个星号。 */
    public void setCorsOrigins(String corsOrigins) {
        this.corsOrigins = corsOrigins;
    }

    /** 返回检查点数据库路径；GraphConfig 用它创建 SQLiteSaver。 */
    public String getCheckpointDbPath() {
        return checkpointDbPath;
    }

    /** 设置检查点数据库路径；对应 app.checkpoint-db-path。 */
    public void setCheckpointDbPath(String checkpointDbPath) {
        this.checkpointDbPath = checkpointDbPath;
    }
}
