// 模块说明：执行轨迹查询接口（对应 Python 的 OPS-6 回放）。
package com.example.backendjava.service;

// 标准库：Map 用于动态轨迹结构
import java.util.Map;

/**
 * 轨迹服务接口。
 */
public interface TraceService {

    /**
     * 列出有执行轨迹的会话。
     *
     * @param limit 最多返回多少个会话
     * @return 形如 {"sessions":[{session_id,title,event_count,turn_count,started_at,last_at}]}
     */
    Map<String, Object> listSessions(int limit);

    /**
     * 列出某个会话的执行轮次。
     *
     * @param sessionId 会话 id
     * @param limit     最多返回多少轮
     * @return 形如 {"session_id","count","turns":[...]}
     */
    Map<String, Object> listTurns(String sessionId, int limit);

    /**
     * 读取轨迹事件。
     *
     * @param sessionId 会话 id
     * @param turnId    轮次 id；null 表示整个会话
     * @param limit     最多返回多少条
     * @return 形如 {"session_id","turn_id","count","events":[...]}
     */
    Map<String, Object> listEvents(String sessionId, String turnId, int limit);
}
