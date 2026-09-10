// 模块说明：通用分页结果，对应 Python 侧 app/db/paginate.py 的 Page.to_dict()。
package com.example.backendjava.common;

// Jackson 注解：让 Java 的 hasNext/hasPrev 序列化成前端的 has_next/has_prev
import com.fasterxml.jackson.annotation.JsonProperty;

// 标准库：List 作为当前页数据的容器
import java.util.List;

/**
 * 分页结果。
 *
 * @param items   当前页数据
 * @param total   总条数
 * @param page    当前页码（从 1 开始）
 * @param size    每页条数
 * @param pages   总页数（由 total 与 size 向上取整）
 * @param hasPrev 是否有上一页
 * @param hasNext 是否有下一页
 * @param <T>     当前页元素类型
 */
public record PageResult<T>(
        // 当前页数据；顺序由具体查询决定
        List<T> items,
        // 总条数；不受分页影响
        long total,
        // 当前页码；从 1 开始
        int page,
        // 每页条数；调用方传入，服务端会限制在 1~100
        int size,
        // 总页数；size=0 时为 0，避免除零
        int pages,
        // 是否有上一页：page > 1
        @JsonProperty("has_prev") boolean hasPrev,
        // 是否有下一页：page < pages
        @JsonProperty("has_next") boolean hasNext
) {

    /**
     * 根据当前页数据与总数计算分页元信息。
     *
     * @param items 当前页数据
     * @param total 总条数
     * @param page  当前页码（小于 1 时按 1 处理）
     * @param size  每页条数（小于 1 时按 1 处理，大于 100 时按 100 处理）
     * @param <T>   元素类型
     * @return 计算好 pages / hasPrev / hasNext 的分页结果
     */
    public static <T> PageResult<T> of(List<T> items, long total, int page, int size) {
        // 参数保护：与 Python 的 paginate() 保持一致，避免非法页码导致负数偏移
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 100));
        // 向上取整计算总页数；safeSize 已经保证大于 0
        int pages = (int) ((total + safeSize - 1) / safeSize);
        // 上一页是否存在只取决于当前页，不依赖总页数
        boolean hasPrev = safePage > 1;
        // 下一页是否存在：当前页小于总页数
        boolean hasNext = safePage < pages;
        return new PageResult<>(items, total, safePage, safeSize, pages, hasPrev, hasNext);
    }
}
