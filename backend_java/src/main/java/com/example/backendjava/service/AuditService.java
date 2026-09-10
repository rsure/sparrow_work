// 模块说明：工具调用审计查询接口。
package com.example.backendjava.service;

// 标准库：List 用于审计记录列表
import java.util.List;
// 标准库：Map 用于动态记录结构
import java.util.Map;

/**
 * 审计服务接口。
 */
public interface AuditService {

    /**
     * 查询审计记录，按时间倒序。
     *
     * @param sessionId 只看某个会话；null 表示全部
     * @param tool      只看某个工具；null 表示全部
     * @param limit     最多返回多少条
     * @return 审计记录列表
     */
    List<Map<String, Object>> list(String sessionId, String tool, int limit);
}
