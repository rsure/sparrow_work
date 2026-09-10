// 模块说明：执行中插话的读取接口（对应 Python policy.py 的 _append_steer_notes / steering.drain）。
//
// 为什么把插话写进「工具结果」而不是新的一条 user 消息：
//   正在跑的 Agent 图只接受一次输入，中途插入新消息需要改图结构与恢复机制；
//   而工具结果本来就会在下一步喂给模型，把插话写进这里，模型看到的效果完全一样。
// Java 侧的插话队列由 AgentRuntime 实现；没有实现时 ToolRuntime 直接跳过。
package com.example.backendjava.tools;

// 标准库：List 返回排队的插话
import java.util.List;

/**
 * 执行中插话的来源。
 */
public interface ToolSteeringSource {

    /** 插话行的前缀：让模型一眼看出这是用户刚补充的话，而不是工具输出。 */
    String INJECT_PREFIX = "（用户插话）";

    /** 插话块末尾的提示：要求模型把插话并入后续步骤。 */
    String INJECT_HINT = "以上是用户在工具执行期间补充的指令，请在后续步骤中一并考虑。";

    /**
     * 取走某个会话当前排队的插话（取走即清空，避免重复注入）。
     *
     * @param sessionId 会话 id
     * @return 插话文本列表；没有插话时返回空列表
     */
    List<String> drain(String sessionId);
}
