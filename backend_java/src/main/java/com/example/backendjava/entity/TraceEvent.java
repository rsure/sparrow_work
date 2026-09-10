package com.example.backendjava.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "trace_event")
public class TraceEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "session_id", nullable = false, length = Integer.MAX_VALUE)
    private String sessionId;

    @Column(name = "turn_id", nullable = false, length = Integer.MAX_VALUE)
    private String turnId;

    @Column(name = "type", nullable = false, length = Integer.MAX_VALUE)
    private String type;

    @Column(name = "payload", nullable = false, length = Integer.MAX_VALUE)
    private String payload = "{}";

    @Column(name = "created_at", nullable = false)
    private String createdAt;

    // getters / setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getTurnId() { return turnId; }
    public void setTurnId(String turnId) { this.turnId = turnId; }
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public String getCreatedAt() { return createdAt; }
    public void setCreatedAt(String createdAt) { this.createdAt = createdAt; }
}