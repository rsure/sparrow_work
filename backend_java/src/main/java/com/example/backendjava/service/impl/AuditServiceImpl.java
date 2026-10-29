// 模块说明：审计日志查询服务。只做「按会话/工具过滤 + 倒序分页 + 字段名转 snake_case」三件事。
package com.example.backendjava.service.impl;

// 项目内：limit 的默认值与上限契约表（与 Python 侧 app/core/limits.py 一一对应）
import com.example.backendjava.common.PageLimits;
// 项目内：审计日志实体（一行 = 一次工具调用）
import com.example.backendjava.entity.AuditLog;
// 项目内：审计日志仓库，支持按 Specification 动态拼条件
import com.example.backendjava.repository.AuditLogRepository;
// 项目内：审计业务接口（本类实现它）
import com.example.backendjava.service.AuditService;

// Jakarta 依赖注入注解：按类型注入字段，与项目现有写法保持一致
import jakarta.annotation.Resource;
// Spring Data：分页请求（页码 + 每页条数 + 排序）
import org.springframework.data.domain.PageRequest;
// Spring Data：分页参数接口，findAll(spec, pageable) 的形参类型
import org.springframework.data.domain.Pageable;
// Spring Data：排序规则，审计列表固定按 id 倒序（最新的在最前）
import org.springframework.data.domain.Sort;
// Spring Data：JPA 条件表达式，用来按 session_id / tool 动态过滤
import org.springframework.data.jpa.domain.Specification;
// Spring：把本类注册成 AuditService 的实现
import org.springframework.stereotype.Service;

// 标准库：LinkedHashMap 保证输出字段顺序稳定，便于对照接口文档
import java.util.LinkedHashMap;
// 标准库：List 返回审计行列表
import java.util.List;
// 标准库：Map 承载 snake_case 字典
import java.util.Map;

/**
 * 审计日志查询服务实现。
 *
 * <p><b>易错点：</b>{@link Specification#and} 返回的是<b>新对象</b>，不会修改原对象；
 * 拼条件时必须把返回值赋回变量，否则条件会被静默丢弃——这正是旧代码「按工具筛选无效」的原因。</p>
 */
@Service
public class AuditServiceImpl implements AuditService {

    /** 审计日志仓库：列表查询走它。 */
    @Resource
    private AuditLogRepository auditLogRepository;

    /**
     * 查询审计日志：支持按会话与工具过滤，按 id 倒序分页。
     *
     * @param sessionId 会话 id；null 或空白表示不过滤
     * @param tool      工具名；null 或空白表示不过滤
     * @param limit     最多返回多少条（内部会再夹一次上限）
     * @return snake_case 的审计行列表，最新的在最前
     */
    @Override
    public List<Map<String, Object>> list(String sessionId, String tool, int limit) {
        // 分页与过滤都在数据库侧完成，避免把整表加载进内存
        // limit 的上限由 controller 的 @Max 拦过，这里再夹一次是给「内部直接调用」兜底
        Pageable pageable = PageRequest.of(0, PageLimits.clamp(limit, PageLimits.MAX_AUDIT),
                Sort.by(Sort.Direction.DESC, "id"));

        // 从「无条件」开始往上叠：unrestricted() 等价于 WHERE 1=1
        Specification<AuditLog> spec = Specification.unrestricted();
        if (sessionId != null && !sessionId.isBlank()) {
            spec = spec.and(eq("sessionId", sessionId));
        }
        if (tool != null && !tool.isBlank()) {
            // 必须赋回 spec：and() 返回新对象，不赋回等于没加这个条件
            spec = spec.and(eq("tool", tool));
        }

        return auditLogRepository.findAll(spec, pageable).getContent().stream()
                .map(this::toMap)   // 字段名转成 snake_case，与前端对齐
                .toList();
    }

    /**
     * 构造一个 equal 谓词。
     *
     * @param column 实体属性名（不是数据库列名），如 sessionId / tool
     * @param value  要匹配的值
     * @return JPA 条件
     */
    private static Specification<AuditLog> eq(String column, Object value) {
        return (root, query, cb) -> cb.equal(root.get(column), value);
    }

    /**
     * 审计实体 → snake_case 字典（与前端审计页字段对齐）。
     *
     * @param row 审计实体
     * @return 字典
     */
    private Map<String, Object> toMap(AuditLog row) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", row.getId());
        map.put("session_id", row.getSessionId());
        map.put("tool", row.getTool());
        map.put("arguments", row.getArguments());
        map.put("success", Boolean.TRUE.equals(row.getSuccess()));
        map.put("result", row.getResult());
        map.put("created_at", row.getCreatedAt());
        return map;
    }
}