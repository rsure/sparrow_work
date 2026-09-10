// 模块说明：设置变更事件——某个设置项被写入成功后广播出去，让关心它的模块刷新自身状态。
package com.example.backendjava.settings;

/**
 * 一次设置变更的通知内容。
 *
 * <p>事件是「不可变的快照」：监听者拿到的就是落库那一刻的值，
 * 不会因为之后又被改了一次而变化。</p>
 *
 * @param key      被修改的设置键，例如 llm.model
 * @param value    写入后的新值（已按声明规范化）
 * @param oldValue 写入前的旧值；之前没配置过时为 null
 */
public record SettingsChangeEvent(
        // 设置键
        String key,
        // 新值
        Object value,
        // 旧值
        Object oldValue
) {
}
