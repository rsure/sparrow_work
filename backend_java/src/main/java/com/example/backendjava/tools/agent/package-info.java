// 模块说明：子 Agent 工具子包。
//
// 包含：dispatch_subagent（派发只读子任务）与 SubAgentRunner（运行器接口）。
// 真正的子图执行由 AgentRuntime 实现 SubAgentRunner；工具层只负责参数校验、
// 并发上限、超时与结论截断。
package com.example.backendjava.tools.agent;
