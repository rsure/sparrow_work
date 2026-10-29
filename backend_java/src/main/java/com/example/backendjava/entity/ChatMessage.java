// 模块说明：对话消息实体。一行 = 一条用户/助手消息，同时保存本轮的工具轨迹与用量。
package com.example.backendjava.entity;

// Jakarta 持久化注解：@Entity / @Table / @Id / @GeneratedValue / @Column
import jakarta.persistence.*;
// Lombok：自动生成 getter / setter，实体只负责承载字段
import lombok.Getter;
import lombok.Setter;

/**
 * 对话消息。
 *
 * <p>用量字段（input_tokens / output_tokens / cost / model）只对助手消息有意义，
 * 用户消息保持 null；聚合会话用量时按 {@code role = "assistant"} 过滤即可。</p>
 *
 * <p>这些字段的列由 Hibernate 的 {@code ddl-auto=update} 在老库上自动补齐，
 * 同时已写进 {@code schema.sql} 的 {@code CREATE TABLE}，新库一次建好。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "chat_message")
public class ChatMessage {

    /** 自增主键；同一会话内越大越新，历史排序与「最近 N 条」都靠它。 */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    /** 所属会话 id，关联 chat_session.id。 */
    @Column(name = "session_id", nullable = false, length = Integer.MAX_VALUE)
    private String sessionId;

    /** 说话人：user=用户 / assistant=助手。 */
    @Column(name = "role", nullable = false, length = Integer.MAX_VALUE)
    private String role;

    /** 消息正文。 */
    @Column(name = "content", nullable = false, length = Integer.MAX_VALUE)
    private String content;

    /** 入库时间，ISO-8601 字符串。 */
    @Column(name = "created_at", nullable = false)
    private String createdAt;

    /** 该消息所属的对话模式：agent=工具 Agent / doc=`\doc` 知识库指令。 */
    @Column(name = "mode")
    private String mode;

    /** 助手调用过的工具轨迹，JSON 数组字符串；用户消息为 null。 */
    @Column(name = "tool_calls", length = Integer.MAX_VALUE)
    private String toolCalls;

    /** 本轮结束原因：done / stopped / error / pending_confirm。 */
    @Column(name = "finish_reason")
    private String finishReason;

    /** 本轮耗时（秒）；用户消息为 null。 */
    @Column(name = "elapsed")
    private Double elapsed;

    /** 本轮输入 token 数；供应商没回 usage 时为 null。 */
    @Column(name = "input_tokens")
    private Long inputTokens;

    /** 本轮输出 token 数；供应商没回 usage 时为 null。 */
    @Column(name = "output_tokens")
    private Long outputTokens;

    /** 本轮折算费用（元）；单价未知（自定义模型没填价）时为 0.0。 */
    @Column(name = "cost")
    private Double cost;

    /** 本轮实际使用的模型名；doc 模式等未调用模型的轮次为 null。 */
    @Column(name = "model")
    private String model;
}