package com.example.backendjava.service.impl;

import com.example.backendjava.entity.AuditLog;
import com.example.backendjava.repository.AuditLogRepository;
import com.example.backendjava.service.AuditService;
import jakarta.annotation.Resource;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
@Service
public class AuditServiceImpl implements AuditService {
    @Resource
    AuditLogRepository auditLogRepository;


    /** {@inheritDoc} */
    @Override
    public List<Map<String, Object>> list(String sessionId, String tool, int limit) {
        // 分页与过滤都在数据库侧完成，避免把整表加载进内存
        Pageable pageable = PageRequest.of(0, limit <= 0 ? 100 : limit,
                Sort.by(Sort.Direction.DESC, "id"));
        Specification<AuditLog> spec = Specification.unrestricted();
        if (sessionId != null && !sessionId.isBlank()) {
            spec = spec.and(eq("sessionId", sessionId));
        }
        if(tool != null && !tool.isBlank()){
            spec.and(eq( "tool", tool));
        }

        return auditLogRepository.findAll(spec, pageable).getContent().stream()
                .map(this::toMap)   // 字段名转成 snake_case，与前端对齐
                .toList();
    }

    /**
     * 条件为真才拼 equal 谓词，否则返回 {@code null} 被 {@link Specification} 忽略。
     */
    private static Specification<AuditLog> eq( String column, Object value) {
        return (root, query, cb) -> cb.equal(root.get(column), value);
    }

    private Map<String, Object> toMap(AuditLog auditLog) {
        //TODO
        return new HashMap<>();
    }


}
