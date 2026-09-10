package com.example.backendjava.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Entity
@Table(name = "chat_message")
public class ChatMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "session_id", nullable = false, length = Integer.MAX_VALUE)
    private String sessionId;

    @Column(name = "role", nullable = false, length = Integer.MAX_VALUE)
    private String role;

    @Column(name = "content", nullable = false, length = Integer.MAX_VALUE)
    private String content;

    @Column(name = "created_at", nullable = false)
    private String createdAt;


    // 该消息所属的对话模式：agent / doc
    @Column(name = "mode")
    private String mode;
    // 助手调用过的工具轨迹，JSON 数组字符串；用户消息为空
    @Column(name = "tool_calls", length = Integer.MAX_VALUE)
    private String toolCalls;
    // 本轮结束原因：done / stopped / error / pending_confirm
    @Column(name = "finish_reason")
    private String finishReason;
    // 本轮耗时（秒）；用户消息为空
    @Column(name = "elapsed")
    private Double elapsed;


}