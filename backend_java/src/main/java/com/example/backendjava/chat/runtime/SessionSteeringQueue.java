// 模块说明：会话级插话队列 —— 实现 ToolSteeringSource，把用户的插话塞进工具结果里。
//
// 为什么走这个接口：ToolRuntime 每执行完一个工具就会调 drain(sessionId)，
// 把队列里的插话拼到工具结果后面（带 INJECT_PREFIX 前缀），模型下一轮就能看到。
// 这样「执行中插话」不用打断模型，也不用重发请求。
package com.example.backendjava.chat.runtime;

// 标准库：队列与并发容器
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;

// 本项目：插话接口
import com.example.backendjava.tools.ToolSteeringSource;

// Spring：注册成 Bean，ToolRuntime 通过 ObjectProvider 注入
import org.springframework.stereotype.Component;

/**
 * 会话级插话队列。
 */
@Component
public class SessionSteeringQueue implements ToolSteeringSource {

    /** 一条待注入的插话。 */
    private record Item(String steerId, String content) {
    }

    /** 会话 id → 待注入插话。 */
    private final Map<String, ConcurrentLinkedQueue<Item>> queues = new ConcurrentHashMap<>();

    /** 会话总线：注入时发 steer_injected 事件。 */
    private final ChatSessionBus bus;

    /** 事件工厂。 */
    private final com.example.backendjava.chat.event.ChatEvents events;

    /**
     * 构造队列。
     *
     * @param bus    会话总线
     * @param events 事件工厂
     */
    public SessionSteeringQueue(ChatSessionBus bus, com.example.backendjava.chat.event.ChatEvents events) {
        this.bus = bus;
        this.events = events;
    }

    /**
     * 入队一条插话。
     *
     * @param sessionId 会话 id
     * @param content   插话内容
     * @return 插话 id
     */
    public String offer(String sessionId, String content) {
        String steerId = UUID.randomUUID().toString();
        queues.computeIfAbsent(sessionId, key -> new ConcurrentLinkedQueue<>())
                .add(new Item(steerId, content));
        return steerId;
    }

    /**
     * 读取当前队列长度。
     *
     * @param sessionId 会话 id
     * @return 待注入条数
     */
    public int pending(String sessionId) {
        ConcurrentLinkedQueue<Item> queue = queues.get(sessionId);
        return queue == null ? 0 : queue.size();
    }

    /**
     * 取走全部待注入插话（由 ToolRuntime 在工具边界调用）。
     *
     * @param sessionId 会话 id
     * @return 插话文本列表；没有则返回空列表
     */
    @Override
    public List<String> drain(String sessionId) {
        ConcurrentLinkedQueue<Item> queue = queues.get(sessionId);
        if (queue == null || queue.isEmpty()) {
            return List.of();
        }
        List<String> texts = new ArrayList<>();
        Item item;
        while ((item = queue.poll()) != null) {
            texts.add(item.content());
            // 每注入一条就通知前端「这条已经进去了」
            bus.emit(sessionId, events.steerInjected(sessionId, item.steerId()));
        }
        return texts;
    }
}