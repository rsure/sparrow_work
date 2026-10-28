// 模块说明：消息表的数据访问接口。
//
// 注意：Spring Data 的方法名就是 SQL —— 名字写错不会编译报错，而是应用启动时解析失败
// （ChatSessionRepository 就因为 `findByArchived...` 少了一个参数，让整个应用起不来）。
// 所以这里每个方法都写清「参数是干什么的、返回什么顺序」。
package com.example.backendjava.repository;

// 实体：一条消息（属于某个会话，id 自增即时间顺序）
import com.example.backendjava.entity.ChatMessage;
// Spring Data 的分页参数：这里只借它给查询加 LIMIT，不涉及页号
import org.springframework.data.domain.Pageable;
// Spring Data JPA 仓库基类：自带 save / findById / delete 等
import org.springframework.data.jpa.repository.JpaRepository;

// 标准库：List 作为查询结果的容器
import java.util.List;

/**
 * 消息仓库。
 */
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {

    /**
     * 按 id 升序取某个会话的全部消息（从最早到最新）。
     *
     * @param sessionId 会话 id
     * @return 消息列表；没有消息时为空列表
     */
    List<ChatMessage> findBySessionIdOrderByIdAsc(String sessionId);

    /**
     * 按 id 倒序取某个会话的最近若干条消息（最新在前）。
     *
     * <p><b>为什么倒序：</b>升序 + {@code Pageable} 拿到的是「最老的 N 条」，而历史回填要的是
     * 「最新的 N 条」。倒序取完由 {@code ChatPersistence.findRecentMessages} 翻回升序，
     * 对外暴露的顺序仍然是时间正序。</p>
     *
     * @param sessionId 会话 id
     * @param pageable  只用于限制条数（{@code Pageable.ofSize(n)}，n 必须 ≥ 1）
     * @return 按 id 倒序（最新在前）的消息列表
     */
    List<ChatMessage> findBySessionIdOrderByIdDesc(String sessionId, Pageable pageable);
}
