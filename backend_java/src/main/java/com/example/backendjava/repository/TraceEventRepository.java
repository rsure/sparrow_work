package com.example.backendjava.repository;

import com.example.backendjava.entity.TraceEvent;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface TraceEventRepository extends JpaRepository<TraceEvent, Long> {
    // 按会话聚合：返回 (session_id, 事件条数, 最近时间)，用于「轨迹列表」页
    @Query("SELECT e.sessionId AS sessionId, COUNT(e) AS total, MAX(e.createdAt) AS lastAt "
            + "FROM TraceEvent e GROUP BY e.sessionId ORDER BY lastAt DESC")
    List<Object[]> listSessionSummaries(Pageable pageable);

    // 取某会话的全部事件（按 id 升序），前端自己按 turn_id 分组
    List<TraceEvent> findBySessionIdOrderByIdAsc(String sessionId);
}
