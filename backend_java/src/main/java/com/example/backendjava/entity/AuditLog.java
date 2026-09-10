package com.example.backendjava.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "audit_log")
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "session_id", length = Integer.MAX_VALUE)
    private String sessionId;

    @Column(name = "tool", nullable = false, length = Integer.MAX_VALUE)
    private String tool;

    @Column(name = "arguments", nullable = false, length = Integer.MAX_VALUE)
    private String arguments = "{}";

    @Column(name = "success", nullable = false)
    private Boolean success = false;

    @Column(name = "result", nullable = false, length = Integer.MAX_VALUE)
    private String result = "";

    @Column(name = "created_at", nullable = false)
    private String createdAt;

    // getters / setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getTool() { return tool; }
    public void setTool(String tool) { this.tool = tool; }
    public String getArguments() { return arguments; }
    public void setArguments(String arguments) { this.arguments = arguments; }
    public Boolean getSuccess() { return success; }
    public void setSuccess(Boolean success) { this.success = success; }
    public String getResult() { return result; }
    public void setResult(String result) { this.result = result; }
    public String getCreatedAt() { return createdAt; }
    public void setCreatedAt(String createdAt) { this.createdAt = createdAt; }
}