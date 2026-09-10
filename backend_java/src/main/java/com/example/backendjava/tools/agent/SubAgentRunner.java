// 模块说明：子 Agent 运行器接口（对应 Python subagent_tool.py 的 _run_sub_agent）。
//
// Python 直接构造 LangGraph 的子图；Java 侧的 AgentRuntime 还在搭建中，
// 因此这里定义一个最小接口：谁来跑子 agent、怎么跑由运行时实现，
// DispatchSubagentTool 只负责参数校验、并发上限与超时。
package com.example.backendjava.tools.agent;

/**
 * 子 Agent 运行器。
 */
public interface SubAgentRunner {

    /**
     * 跑一个只读子任务并返回结论文本。
     *
     * @param task      子任务描述
     * @param context   主对话补充的背景
     * @param sessionId 主对话会话 id（实现方据此派生子会话 id）
     * @return 子 agent 的结论
     */
    String run(String task, String context, String sessionId);
}
