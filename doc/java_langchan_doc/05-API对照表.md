# 05 · Python → Java API 对照表

> 所有 Java 路径都省略统一前缀 `/api`（由 `server.servlet.context-path` 提供）。
> 状态：✅ 已实现 / 🚧 接口已给出、实现返回 501 / ⏳ 计划中。

---

## 1. 健康检查

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/health` | `HealthController.health` | `ApiResponse<HealthData>` | ✅ |

---

## 2. 模型

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/llm/providers` | `LlmController.providers` | `ApiResponse<List<ProviderInfo>>` | ✅ |
| POST | `/llm/probe` | `LlmController.probe` | `ApiResponse<ProbeResult>` | ✅（OpenAI 兼容；其它供应商待补工厂） |

---

## 3. 对话

> 注意：Python 侧的 `/chat/*` 辅助端点返回**裸 JSON**；Java 侧保持兼容，
> 只有 `/chat/stream` 与 `/chat/resume` 返回 SSE。

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| POST | `/chat/stream` | `ChatController.stream` | `text/event-stream` | 🚧 |
| POST | `/chat/resume` | `ChatController.resume` | `text/event-stream` | 🚧 |
| POST | `/chat/stop` | `ChatController.stop` | `{stopped, session_id}` | 🚧 |
| POST | `/chat/{sessionId}/steer` | `ChatController.steer` | `{session_id, steer_id, content, queued, pending}` | 🚧 |
| POST | `/chat/{sessionId}/tool-cancel` | `ChatController.cancelTool` | `{session_id, cancelled, tool}` | 🚧 |
| GET | `/chat/sessions` | `ChatController.listSessions` | `{sessions:[...]}` | 🚧 |
| GET | `/chat/history/sessions/{sessionId}` | `ChatController.history` | `{session_id, messages:[...]}` | 🚧 |
| PATCH | `/chat/history/sessions/{sessionId}` | `ChatController.patchSession` | `ChatSessionPatchResult` | 🚧 |
| GET | `/chat/history/sessions/{sessionId}/export` | `ChatController.export` | `ExportedSession` | 🚧 |
| GET | `/chat/history/sessions/{sessionId}/usage` | `ChatController.usage` | `SessionUsage` | 🚧 |
| DELETE | `/chat/history/sessions/{sessionId}` | `ChatController.deleteHistory` | `{deleted, session_id}` | 🚧 |
| GET | `/chat/sessions/{sessionId}` | `ChatController.sessionInfo` | `SessionInfo` | 🚧 |
| DELETE | `/chat/sessions/{sessionId}` | `ChatController.clearSession` | `{cleared, session_id}` | 🚧 |
| GET | `/chat/tool-output/{ref}` | `ChatController.toolOutput` | `ToolOutputPayload` | 🚧 |
| GET | `/chat/events` | `ChatController.events` | 事件协议字典 | 🚧 |

### SSE 事件

| 事件 | 负载 | 说明 |
| --- | --- | --- |
| `thinking` | `{session_id, stage}` | 阶段提示 |
| `token` | `{text}` | 增量文本 |
| `tool_start` | `{name, input, tool_call_id}` | 工具开始 |
| `tool_end` | `{name, output, ok, elapsed}` | 工具结束 |
| `confirm_required` | `{session_id, interrupt_id, action, preview}` | 等待确认 |
| `done` | `{session_id, answer, tools, usage, elapsed}` | 正常结束 |
| `stopped` | `{session_id, answer, reason}` | 用户终止 |
| `error` | `{message, type?}` | 出错 |

---

## 4. 文件扫描

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/scan/pages` | `ScanController.pages` | `ApiResponse<PageResult<TaskInfo>>` | 🚧 |
| POST | `/scan/start` | `ScanController.start` | `ApiResponse<String>` | 🚧 |
| GET | `/scan/stream` | `ScanController.streamStatus` | SSE | 🚧 |
| GET | `/scan/files/stream` | `ScanController.streamFiles` | SSE | 🚧 |
| GET | `/scan/status` | `ScanController.status` | `ApiResponse<ScanProgress>` | 🚧 |
| POST | `/scan/cancel` | `ScanController.cancel` | `ApiResponse<ScanCancelResult>` | 🚧 |
| GET | `/scan/info` | `ScanController.info` | `ApiResponse<Object>` | 🚧 |
| POST | `/scan/result` | `ScanController.result` | `ApiResponse<Object>` | 🚧 |

---

## 5. RAG 文档库

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| POST | `/rag/documents` | `RagController.indexFile` | `ApiResponse<IndexResult>` | 🚧 |
| POST | `/rag/documents/text` | `RagController.indexText` | `ApiResponse<IndexResult>` | 🚧 |
| DELETE | `/rag/documents/by-source` | `RagController.deleteBySource` | `ApiResponse<Map>` | 🚧 |
| DELETE | `/rag/documents/{docId}` | `RagController.deleteById` | `ApiResponse<Map>` | 🚧 |
| POST | `/rag/documents/batch-delete` | `RagController.batchDelete` | `ApiResponse<Map>` | 🚧 |
| GET | `/rag/documents/{docId}` | `RagController.getDocument` | `ApiResponse<RagDocument>` | 🚧 |
| GET | `/rag/documents` | `RagController.listDocuments` | `ApiResponse<List<RagDocument>>` | 🚧 |
| POST | `/rag/search` | `RagController.search` | `ApiResponse<List<SearchHit>>` | 🚧 |
| POST | `/rag/index/rebuild` | `RagController.rebuildIndex` | `ApiResponse<Map>` | 🚧 |

---

## 6. 设置 / 工作区 / 密钥

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/settings/workspace` | `SettingsController.getWorkspace` | `ApiResponse<List<String>>` | 🚧 |
| PUT | `/settings/workspace` | `SettingsController.putWorkspace` | `ApiResponse<List<String>>` | 🚧 |
| GET | `/settings/workspaces` | `SettingsController.listWorkspaces` | `ApiResponse<WorkspacesView>` | 🚧 |
| POST | `/settings/workspaces` | `SettingsController.createWorkspace` | `ApiResponse<WorkspaceProfile>` | 🚧 |
| PUT | `/settings/workspaces/{id}` | `SettingsController.updateWorkspace` | `ApiResponse<WorkspaceProfile>` | 🚧 |
| DELETE | `/settings/workspaces/{id}` | `SettingsController.deleteWorkspace` | `ApiResponse<WorkspaceDeletedResult>` | 🚧 |
| POST | `/settings/workspaces/active` | `SettingsController.activateWorkspace` | `ApiResponse<ActiveSwitchResult>` | 🚧 |
| GET | `/settings` | `SettingsController.getSettings` | `ApiResponse<SettingsView>` | 🚧 |
| GET | `/settings/meta` | `SettingsController.getSettingsMeta` | `ApiResponse<List<SettingMeta>>` | 🚧 |
| PUT | `/settings` | `SettingsController.saveSettings` | `ApiResponse<SettingsView>` | 🚧 |
| GET | `/settings/export` | `SettingsController.exportSettings` | `ApiResponse<SettingsExport>` | 🚧 |
| POST | `/settings/import` | `SettingsController.importSettings` | `ApiResponse<SettingsImportResult>` | 🚧 |
| GET | `/settings/secrets/{key}` | `SettingsController.getSecretStatus` | `ApiResponse<SecretStatus>` | 🚧 |
| PUT | `/settings/secrets/{key}` | `SettingsController.putSecret` | `ApiResponse<SecretStatus>` | 🚧 |
| DELETE | `/settings/secrets/{key}` | `SettingsController.deleteSecret` | `ApiResponse<Void>` | 🚧 |

---

## 7. 技能 / MCP / 命令

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/skills` | `SkillController.listSkills` | 裸 JSON 快照 | 🚧 |
| POST | `/skills/reload` | `SkillController.reloadSkills` | 裸 JSON 快照 | 🚧 |
| GET | `/skills/{name}` | `SkillController.getSkill` | 裸 JSON 详情 | 🚧 |
| GET | `/mcp/servers` | `McpController.listServers` | 裸 JSON 快照 | 🚧 |
| POST | `/mcp/reload` | `McpController.reload` | 裸 JSON 快照 | 🚧 |
| POST | `/mcp/test` | `McpController.test` | 裸 JSON 试连结果 | 🚧 |
| GET | `/commands` | `CommandController.listCommands` | `{"commands":[...]}` | 🚧 |

---

## 8. 记忆 / 轨迹 / 审计

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/memory` | `MemoryController.list` | 裸 JSON | 🚧 |
| GET | `/memory/stats` | `MemoryController.stats` | 裸 JSON | 🚧 |
| POST | `/memory/search` | `MemoryController.search` | 裸 JSON | 🚧 |
| POST | `/memory/query` | `MemoryController.query` | SSE | 🚧 |
| POST | `/memory` | `MemoryController.create` | 裸 JSON | 🚧 |
| DELETE | `/memory/{memoryId}` | `MemoryController.delete` | 裸 JSON | 🚧 |
| DELETE | `/memory` | `MemoryController.clear` | 裸 JSON | 🚧 |
| POST | `/memory/extract` | `MemoryController.extract` | 裸 JSON | 🚧 |
| POST | `/memory/prune` | `MemoryController.prune` | 裸 JSON | 🚧 |
| POST | `/memory/reindex` | `MemoryController.reindex` | 裸 JSON | 🚧 |
| GET | `/trace/sessions` | `TraceController.listSessions` | 裸 JSON | 🚧 |
| GET | `/trace/sessions/{id}/turns` | `TraceController.listTurns` | 裸 JSON | 🚧 |
| GET | `/trace/sessions/{id}` | `TraceController.listEvents` | 裸 JSON | 🚧 |
| GET | `/audit` | `AuditController.list` | `ApiResponse<List<Map>>` | 🚧 |

---

## 9. 文件 / 诊断

| 方法 | 路径 | Java Controller | 返回 | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/file/catalog` | `FileController.catalog` | `ApiResponse<List<Map>>` | 🚧 |
| GET | `/file/preview` | `FileController.preview` | `ApiResponse<Map>` | 🚧 |
| GET | `/file/search` | `FileController.search` | `ApiResponse<Map>` | 🚧 |
| GET | `/file/raw` | `FileController.raw` | 文件字节 | 🚧 |
| GET | `/diagnostic/summary` | `DiagnosticController.summary` | 裸 JSON | 🚧 |
| GET | `/diagnostic/export` | `DiagnosticController.export` | zip 字节 | 🚧 |

---

## 10. 实现优先级建议

1. `SettingsService`（所有模块都依赖设置与持久化）；
2. `ChatService` 的 SSE 直答版；
3. `AgentRuntime` + LangGraph4j + 检查点；
4. 工具集（先只读，再写盘/执行）；
5. `RagService`；
6. `McpService`；
7. 技能/命令/记忆/轨迹/审计/诊断；
8. 文件预览与扫描。

每完成一项，把本表的状态从 🚧 改成 ✅，并更新 `doc/java_langchan_doc/README.md` 的完成度表。
