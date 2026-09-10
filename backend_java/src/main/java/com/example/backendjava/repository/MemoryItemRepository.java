package com.example.backendjava.repository;

import com.example.backendjava.entity.MemoryItem;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface MemoryItemRepository extends JpaRepository<MemoryItem, String> {
    List<MemoryItem> findByWorkspaceId(String workspaceId);
}
