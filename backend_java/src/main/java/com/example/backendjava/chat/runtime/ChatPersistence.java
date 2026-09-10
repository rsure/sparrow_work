// 模块说明：对话落库的统一出口 —— 会话与消息的读写都走这里。
//
// 为什么不在 ChatServiceImpl 里直接写 repository：13 个桩方法里有 8 个要查/写会话与消息，
// 集中到一处之后，每个 Service 方法只剩「组装返回值」这一件事。
package com.example.backendjava.chat.runtime;

// 标准库：时间与集合
import java.time.Instant;
import java.util.List;
import java.util.Optional;

// 本项目：实体与仓库
import com.example.backendjava.entity.ChatMessage;
import com.example.backendjava.entity.ChatSession;
import com.example.backendjava.repository.ChatMessageRepository;
import com.example.backendjava.repository.ChatSessionRepository;

// Spring：单例
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 对话持久化门面。
 */
@Component
public class ChatPersistence {

    /** 消息仓库。 */
    private final ChatMessageRepository messages;

    /** 会话仓库。 */
    private final ChatSessionRepository sessions;

    /**
     * 构造门面。
     *
     * @param messages 消息仓库
     * @param sessions 会话仓库
     */
    public ChatPersistence(ChatMessageRepository messages, ChatSessionRepository sessions) {
        this.messages = messages;
        this.sessions = sessions;
    }

    /**
     * 写一条消息。
     *
     * @param sessionId    会话 id
     * @param role         user / assistant
     * @param content      正文
     * @param mode         模式
     * @param toolCalls    工具轨迹 JSON，可为 null
     * @param finishReason 结束原因，可为 null
     * @param elapsed      耗时秒数，可为 null
     */
    @Transactional
    public void saveMessage(String sessionId, String role, String content, String mode,
                            String toolCalls, String finishReason, Double elapsed) {
        ChatMessage row = new ChatMessage();
        row.setSessionId(sessionId);
        row.setRole(role);
        row.setContent(content == null ? "" : content);
        row.setMode(mode);
        row.setToolCalls(toolCalls);
        row.setFinishReason(finishReason);
        row.setElapsed(elapsed);
        row.setCreatedAt(Instant.now().toString());
        messages.save(row);
    }

    /**
     * 确保会话存在并刷新 updated_at；首轮用第一句话当标题。
     *
     * @param sessionId 会话 id
     * @param firstText 首条用户消息，用于生成标题
     */
    @Transactional
    public void touchSession(String sessionId, String firstText) {
        ChatSession row = sessions.findById(sessionId).orElseGet(() -> {
            ChatSession created = new ChatSession();
            created.setId(sessionId);
            created.setCreatedAt(Instant.now().toString());
            created.setTitle(titleOf(firstText));
            return created;
        });
        row.setUpdatedAt(Instant.now().toString());
        sessions.save(row);
    }

    /**
     * 查一个会话。
     *
     * @param sessionId 会话 id
     * @return 会话；不存在时为空
     */
    public Optional<ChatSession> findSession(String sessionId) {
        return sessions.findById(sessionId);
    }

    /**
     * 查一个会话的全部消息（按 id 升序）。
     *
     * @param sessionId 会话 id
     * @return 消息列表
     */
    public List<ChatMessage> findMessages(String sessionId) {
        return messages.findBySessionIdOrderByIdAsc(sessionId);
    }

    /**
     * 统计一个会话的消息条数。
     *
     * @param sessionId 会话 id
     * @return 条数
     */
    public int countMessages(String sessionId) {
        return messages.findBySessionIdOrderByIdAsc(sessionId).size();
    }

    /**
     * 从首条消息生成标题：去掉换行、截断 30 字。
     *
     * @param text 首条用户消息
     * @return 标题
     */
    private String titleOf(String text) {
        if (text == null || text.isBlank()) {
            return "新会话";
        }
        String oneLine = text.replaceAll("\\s+", " ").trim();
        return oneLine.length() <= 30 ? oneLine : oneLine.substring(0, 30) + "…";
    }

    /**
     * 列会话：归档与否分两种排序。
     *
     * @param archived 是否包含已归档
     * @return 会话列表（置顶优先、更新时间倒序）
     */
    public List<ChatSession> persistedSessions(boolean archived) {
        return archived
                ? sessions.findByArchivedOrderByPinnedDescUpdatedAtDesc()
                : sessions.findByArchivedFalseOrderByPinnedDescUpdatedAtDesc();
    }


}