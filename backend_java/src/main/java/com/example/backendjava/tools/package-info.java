// 模块说明：Agent 原子工具层（由 Python 侧 app/tools/* 迁移而来）。
//
// 目录结构（根包放公共底座，子包按工具类型拆分）：
//   tools/                公共底座：路径/遍历/锁/预算/策略/输出治理/工具基类/注册表
//   tools/file/           文件类工具：list_dir、read_file、grep_files、glob、
//                         write_file、edit_file、file_ops
//   tools/exec/           命令执行：run_command
//   tools/sql/            SQLite 查询：sql_query
//   tools/net/            联网类：web_search、web_fetch、http_request + NetGuard / HtmlUtils
//   tools/rag/            知识库类：list_indexed_docs、index_path、delete_index、rag_search
//                         + IndexedDocSupport
//   tools/skill/          技能类：list_skills、read_skill
//   tools/agent/          子 Agent：dispatch_subagent + SubAgentRunner
//
// 与 Python 模块的对应关系（便于双向对照阅读）：
//   tool_utils.py       -> ToolUtils / PathPolicy / WalkStats / TextReadResult
//   policy.py           -> ToolPolicyRegistry / ToolKind / ToolLevel / ToolAction /
//                          ToolDecision / ToolPolicySpec / SessionContext /
//                          ToolApprovalGateway / ToolAuditSink / ToolSteeringSource
//   session.py          -> ToolSession
//   budget.py           -> ToolBudgetRegistry
//   file_guard.py       -> FileGuard
//   path_lock.py        -> PathLock
//   net_guard.py        -> net/NetGuard
//   output_contract.py  -> OutputContract
//   file_read_tool.py   -> file/ListDirTool / file/ReadFileTool / file/GrepFilesTool /
//                          rag/ListIndexedDocsTool / rag/IndexPathTool /
//                          rag/DeleteIndexTool / rag/RagSearchTool
//   file_write_tool.py  -> file/WriteFileTool / file/EditFileTool
//   file_ops_tool.py    -> file/FileOpsTool
//   glob_tool.py        -> file/GlobTool
//   run_command_tool.py -> exec/RunCommandTool
//   sql_tool.py         -> sql/SqlQueryTool
//   web_tool.py         -> net/WebSearchTool / net/WebFetchTool
//   http_tool.py        -> net/HttpRequestTool
//   skill_tool.py       -> skill/ListSkillsTool / skill/ReadSkillTool
//   subagent_tool.py    -> agent/DispatchSubagentTool
//
// 与 Python 侧的三处架构差异（不是遗漏，是 Java 依赖不同）：
//   1. LangChain 的 @tool / LangGraph 的 interrupt() 由 Spring 的 AgentTool + ToolApprovalGateway
//      替代：工具自己只声明"要做什么"，确认与中断由运行时代理完成；
//   2. Python 的 ContextVar 用 ThreadLocal 实现（ToolSession），工具仍在同步线程里执行；
//   3. Python 的 RAG / 技能 / 子 Agent 服务直接 import，Java 侧这些服务可能还没有实现，
//      因此统一用 ObjectProvider 延迟获取；取不到时返回可读的 FAIL，而不是让 Spring 启动失败。
package com.example.backendjava.tools;
