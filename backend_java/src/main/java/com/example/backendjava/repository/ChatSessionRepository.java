package com.example.backendjava.repository;

import com.example.backendjava.entity.ChatSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ChatSessionRepository extends JpaRepository<ChatSession, String> {
    List<ChatSession> findByArchivedFalseOrderByPinnedDescUpdatedAtDesc();

    /**
     * 按归档状态查会话：置顶优先、更新时间倒序（列表页用）
     */
    List<ChatSession> findByArchivedOrderByPinnedDescUpdatedAtDesc();
}
