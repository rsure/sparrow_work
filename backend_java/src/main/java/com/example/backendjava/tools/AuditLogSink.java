package com.example.backendjava.tools;

import com.example.backendjava.entity.AuditLog;
import com.example.backendjava.repository.AuditLogRepository;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Component;

import java.time.Instant;

// 模块说明：把工具审计事件落到 audit_log 表。
@Component
public class AuditLogSink implements ToolAuditSink {

    @Resource
    private AuditLogRepository auditLogRepository;

    /** {@inheritDoc} */
    @Override
    public void record(ToolAuditEvent event) {
        AuditLog row = new AuditLog();
        row.setSessionId(event.sessionId());
        row.setTool(event.tool());
        row.setArguments(String.valueOf(event.extra().getOrDefault("args", "{}")));
        row.setSuccess("ok".equals(event.outcome()));
        row.setResult(truncate(event.output(), 500));
        row.setCreatedAt(Instant.now().toString());
        auditLogRepository.save(row);
    }

    /**
     * 截断
     * @param value
     * @param maxLength
     * @return
     */
    private String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
