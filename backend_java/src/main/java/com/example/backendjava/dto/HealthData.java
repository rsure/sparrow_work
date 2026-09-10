// 模块说明：健康检查响应体，字段与 Python 侧 app/schemas/health.py 及前端 HealthData 类型对齐。
package com.example.backendjava.dto;

// Jackson 注解：把 Java 的驼峰字段映射成前端使用的 snake_case
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 健康检查返回体。
 *
 * @param status        健康状态：ok=正常；degraded=降级（预留）
 * @param service       服务标识名，取自配置 app.name
 * @param version       后端版本号，取自配置 app.version
 * @param env           运行环境：development / production
 * @param pythonVersion Python 解释器版本；Java 后端填 "N/A"，保留该字段是为了兼容旧前端
 * @param platform      运行平台描述，如 "Windows 11 10.0 (C:\\...\\jdk-17)"
 * @param uptimeSeconds 本次进程已运行秒数
 * @param serverTime    服务器当前时间，ISO-8601 字符串（含时区）
 * @param runtime       运行时类型：Java / Python；新前端优先显示它
 * @param runtimeVersion 运行时版本，如 "17.0.20.1"；新前端优先显示它
 */
public record HealthData(
        // 健康状态：当前实现恒为 ok；依赖不可用时可以返回 degraded
        String status,
        // 服务名：让前端能确认自己连的是 Java 后端还是 Python 后端
        String service,
        // 后端版本号：用于排查前后端版本不一致
        String version,
        // 运行环境标识：development / production
        String env,
        // Python 版本：Java 后端没有该值，填 "N/A" 以保持 JSON 字段兼容
        @JsonProperty("python_version") String pythonVersion,
        // 运行平台：操作系统 + 版本 + JDK 安装目录
        String platform,
        // 已运行秒数：从进程启动开始累计，保留 3 位小数
        @JsonProperty("uptime_seconds") double uptimeSeconds,
        // 服务器当前时间：ISO-8601 字符串，前端直接展示
        @JsonProperty("server_time") String serverTime,
        // 运行时类型：Java；前端可用它替换“Python”标签
        String runtime,
        // 运行时版本：例如 17.0.20.1
        @JsonProperty("runtime_version") String runtimeVersion
) {
}
