package com.example.backendjava.service.impl;

import com.example.backendjava.repository.TraceEventRepository;
import com.example.backendjava.service.TraceService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

// 模块说明：执行轨迹查询服务实现
@Service
public class TraceServiceImpl implements TraceService {

    /** 轨迹仓库。 */
    @Resource
    private TraceEventRepository repository;

    /** JSON 反序列化（payload 存的是字符串，返回给前端要还原成对象）。 */
    @Resource
    private ObjectMapper objectMapper;

    @Override
    public Map<String, Object> listTurns(String sessionId, int limit) {
        //TODO
        return Map.of();
    }

    @Override
    public Map<String, Object> listEvents(String sessionId, String turnId, int limit) {
        //TODO
        return Map.of();
    }

    /** {@inheritDoc} */
    @Override
    public Map<String, Object> listSessions(int limit) {
        // 用 JDBC 模板或仓库派生查询都行；这里给 SQL 思路：
        //   SELECT session_id, COUNT(*) AS turns, MAX(created_at) AS last_at
        //   FROM trace_event GROUP BY session_id ORDER BY last_at DESC LIMIT ?
        // 建议直接在 TraceEventRepository 里加一个 @Query 方法（见下方 6.1.1）
        return Map.of("sessions", List.of());
    }

}
