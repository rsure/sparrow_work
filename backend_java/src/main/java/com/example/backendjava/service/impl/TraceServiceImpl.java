package com.example.backendjava.service.impl;

// 本项目：轨迹实体
import com.example.backendjava.entity.TraceEvent;
// 本项目：轨迹仓库（已提供聚合与按会话查询）
import com.example.backendjava.repository.TraceEventRepository;
// 本项目：轨迹服务接口（本类实现它）
import com.example.backendjava.service.TraceService;
// Jackson：payload 是 JSON 字符串，还原成对象给前端
import com.fasterxml.jackson.databind.ObjectMapper;
// Jakarta 依赖注入：按类型注入字段
import jakarta.annotation.Resource;
// Spring Data：listSessionSummaries 的分页参数
import org.springframework.data.domain.PageRequest;
// Spring：声明为服务组件
import org.springframework.stereotype.Service;

// 标准库：ArrayList 收集列表
import java.util.ArrayList;
// 标准库：LinkedHashMap 保持返回字段顺序
import java.util.LinkedHashMap;
// 标准库：List / Map 返回值类型
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

    /** {@inheritDoc} */
    @Override
    public Map<String, Object> listTurns(String sessionId, int limit) {
        List<TraceEvent> rows = repository.findBySessionIdOrderByIdAsc(sessionId);
        // 按 turn_id 分组，且保持首次出现顺序（LinkedHashMap 保证）
        Map<String, List<TraceEvent>> byTurn = new LinkedHashMap<>();
        for (TraceEvent row : rows) {
            String turnId = row.getTurnId() == null ? "" : row.getTurnId();
            byTurn.computeIfAbsent(turnId, key -> new ArrayList<>()).add(row);
        }
        int safeLimit = limit <= 0 ? 50 : Math.min(limit, 200);
        List<Map<String, Object>> turns = new ArrayList<>();
        int i = 0;
        for (Map.Entry<String, List<TraceEvent>> entry : byTurn.entrySet()) {
            if (i++ >= safeLimit) {
                break;
            }
            List<TraceEvent> events = entry.getValue();
            Map<String, Object> turn = new LinkedHashMap<>();
            turn.put("turn_id", entry.getKey());
            turn.put("event_count", events.size());
            turn.put("started_at", events.get(0).getCreatedAt());
            turn.put("last_at", events.get(events.size() - 1).getCreatedAt());
            turns.add(turn);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("session_id", sessionId);
        result.put("count", turns.size());
        result.put("turns", turns);
        return result;
    }

    /** {@inheritDoc} */
    @Override
    public Map<String, Object> listEvents(String sessionId, String turnId, int limit) {
        List<TraceEvent> rows = repository.findBySessionIdOrderByIdAsc(sessionId);
        // turn_id 为空表示整个会话；否则只保留该轮
        List<TraceEvent> filtered = rows.stream()
                .filter(row -> turnId == null || turnId.isBlank() || turnId.equals(row.getTurnId()))
                .toList();
        int safeLimit = limit <= 0 ? 500 : Math.min(limit, 2000);
        // 取最近 safeLimit 条，但保持时间正序
        int from = Math.max(0, filtered.size() - safeLimit);
        List<Map<String, Object>> events = new ArrayList<>();
        for (int i = from; i < filtered.size(); i++) {
            events.add(toEventMap(filtered.get(i)));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("session_id", sessionId);
        result.put("turn_id", turnId);
        result.put("count", events.size());
        result.put("events", events);
        return result;
    }

    /** {@inheritDoc} */
    @Override
    public Map<String, Object> listSessions(int limit) {
        int safeLimit = limit <= 0 ? 50 : Math.min(limit, 200);
        // 聚合查询：一条 SQL 返回 (session_id, 事件条数, 最近时间)，按最近时间倒序
        List<Object[]> rows = repository.listSessionSummaries(PageRequest.of(0, safeLimit));
        List<Map<String, Object>> sessions = new ArrayList<>();
        for (Object[] row : rows) {
            String sessionId = String.valueOf(row[0]);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("session_id", sessionId);
            item.put("event_count", ((Number) row[1]).longValue());
            item.put("last_at", row[2]);
            // 轮次数与起始时间要逐条扫一遍，单独算
            item.put("turn_count", turnCount(sessionId));
            item.put("started_at", firstAt(sessionId));
            sessions.add(item);
        }
        return Map.of("sessions", sessions);
    }


    /** 一个会话的轮次数：按 turn_id 去重计数。 */
    private long turnCount(String sessionId) {
        return repository.findBySessionIdOrderByIdAsc(sessionId).stream()
                .map(TraceEvent::getTurnId)
                .distinct()
                .count();
    }

    /** 一个会话的第一条事件时间；没有则为 null。 */
    private String firstAt(String sessionId) {
        List<TraceEvent> rows = repository.findBySessionIdOrderByIdAsc(sessionId);
        return rows.isEmpty() ? null : rows.get(0).getCreatedAt();
    }

    /** 轨迹实体 → 字典；payload 解析成对象，前端直接读。 */
    private Map<String, Object> toEventMap(TraceEvent row) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", row.getId());
        map.put("session_id", row.getSessionId());
        map.put("turn_id", row.getTurnId());
        map.put("type", row.getType());
        try {
            map.put("payload", objectMapper.readValue(row.getPayload(), Map.class));
        } catch (Exception e) {
            // payload 存的是 JSON 字符串，解析不动就回空对象，不打断整页
            map.put("payload", Map.of());
        }
        map.put("created_at", row.getCreatedAt());
        return map;
    }
}
