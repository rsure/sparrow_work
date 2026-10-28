// 模块说明：对话落库的统一出口 —— 会话与消息的读写都走这里。
//
// 为什么不在 ChatServiceImpl 里直接写 repository：13 个桩方法里有 8 个要查/写会话与消息，
// 集中到一处之后，每个 Service 方法只剩「组装返回值」这一件事。
package com.example.backendjava.chat.runtime;

// 标准库：时间与集合
import java.time.Instant;
// 标准库：可变列表，倒序结果要就地翻转
import java.util.ArrayList;
// 标准库：Collections.reverse 把倒序结果翻回升序
import java.util.Collections;
import java.util.List;
import java.util.Optional;

// 本项目：实体与仓库
import com.example.backendjava.entity.ChatMessage;
import com.example.backendjava.entity.ChatSession;
import com.example.backendjava.repository.ChatMessageRepository;
import com.example.backendjava.repository.ChatSessionRepository;

// Spring Data：分页参数，用来把「只取最近 N 条」下推给 SQL 的 LIMIT
import org.springframework.data.domain.Pageable;
// Spring：把本类注册成容器里的单例 Bean
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
     * 取一个会话最近 limit 条消息，按时间升序返回。
     *
     * <p><b>为什么单独开一个方法：</b>{@link #findMessages(String)} 会把整个会话的消息一次读进内存，
     * 会话一长（几百条以上）就白读了大半。这里让 SQL 的 LIMIT 直接作用在尾部，
     * 只读需要的那几条。</p>
     *
     * @param sessionId 会话 id
     * @param limit     最多取多少条（调用方负责夹到合法范围，必须 ≥ 1）
     * @return 消息列表，最老的在前
     */
    public List<ChatMessage> findRecentMessages(String sessionId, int limit) {
        // 先倒序取「最新 limit 条」，SQL 里就是 ORDER BY id DESC LIMIT n
        List<ChatMessage> newestFirst = new ArrayList<>(
                messages.findBySessionIdOrderByIdDesc(sessionId, Pageable.ofSize(limit)));
        // 翻回升序：对外顺序始终是「最早 → 最新」，视图层不需要再反转
        Collections.reverse(newestFirst);
        return newestFirst;
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
     * 列会话：按归档状态二选一，结果都按「置顶优先、更新时间倒序」排好。
     *
     * @param archived 归档状态：true=只列归档箱（已归档的会话），false=只列未归档的会话
     * @return 会话列表（置顶优先、更新时间倒序）
     */
    public List<ChatSession> persistedSessions(boolean archived) {
        // 归档箱和普通列表共用同一条派生查询：把条件当作参数传进去，不要在方法名里写死 true/false，
        // 否则传进来的参数就没有意义了（也容易和 controller 的 ?archived= 语义对不上）
        return sessions.findByArchivedOrderByPinnedDescUpdatedAtDesc(archived);
    }


}