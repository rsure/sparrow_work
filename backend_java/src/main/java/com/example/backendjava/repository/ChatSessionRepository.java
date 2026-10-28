// 模块说明：会话表（chat_session）的数据访问层。
// 只有「怎么查」的方法声明，没有 SQL：方法名按 Spring Data JPA 的「派生查询」规则翻译成 JPQL。
package com.example.backendjava.repository;

// 实体：本仓库操作的每一行都是一条会话记录
import com.example.backendjava.entity.ChatSession;
// Spring Data 通用仓库：自带 save / findById / findAll / deleteById 等基础方法，不必自己写
import org.springframework.data.jpa.repository.JpaRepository;

// 方法返回值用 List 承载「多条会话」，按顺序返回
import java.util.List;

/**
 * 会话仓库：侧边栏列表与归档箱的查询入口。
 *
 * <p>主键类型是 {@code String}，因为会话 id 由业务侧生成（如 {@code sess-xxxx}），不是数据库自增。</p>
 *
 * <p><b>注意</b>：派生查询的方法名里出现字段名（如 {@code Archived}）时，该方法就必须带同类型的入参；
 * 只有 {@code ...False} / {@code ...True} / {@code ...IsNull} 这类关键字才是「写死条件、不要入参」。
 * 之前写成 {@code findByArchivedOrderBy...()} 却又不带参数，Spring 启动时会直接报
 * 「expects at least 1 arguments but only found 0」，导致整个应用起不来。</p>
 */
public interface ChatSessionRepository extends JpaRepository<ChatSession, String> {

    /**
     * 查「未归档」会话：置顶优先、更新时间倒序。
     *
     * <p>{@code ArchivedFalse} 是写死条件（{@code archived = false}），所以没有入参。</p>
     *
     * <p><b>目前没有调用方</b>，保留它是为了和下面那条方法做对照：
     * 同样查未归档，一个把条件写死在方法名里、一个有入参，读代码时一眼能看出两种写法的差别。
     * 真正在用的一律是下面带 {@code boolean archived} 的那条。</p>
     *
     * @return 未归档会话列表
     */
    List<ChatSession> findByArchivedFalseOrderByPinnedDescUpdatedAtDesc();

    /**
     * 按归档状态查会话：置顶优先、更新时间倒序（侧边栏与归档箱都用它）。
     *
     * <p>名字里的 {@code Archived} 是一个<b>查询条件</b>而不是关键字，因此必须接收一个布尔入参：
     * 传 {@code true} 得到「已归档」的会话，传 {@code false} 得到「未归档」的会话
     * （后者与 {@link #findByArchivedFalseOrderByPinnedDescUpdatedAtDesc()} 结果相同，
     * 所以实际调用方只用这一条）。</p>
     *
     * @param archived 归档状态：true=只查归档箱，false=只查未归档
     * @return 符合条件的会话列表（置顶优先、更新时间倒序）
     */
    List<ChatSession> findByArchivedOrderByPinnedDescUpdatedAtDesc(boolean archived);
}
