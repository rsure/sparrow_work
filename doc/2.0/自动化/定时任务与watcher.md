# B9 定时任务与文件 watcher（增补：改造后可动态加入）

> 依赖锚点：无强依赖；建议收尾阶段做。这是桌面客户端相对 CLI agent 的差异化能力。

## 1. 设计

- **automation 实体**：`(id, name, trigger[cron|interval|file_change], schedule, watch_paths, prompt, workspace_id, enabled, last_run_at)`。
- **调度**：后端 `asyncio` 后台任务，应用打开即生效；首版**不做**系统级常驻服务，UI 明示「关闭应用后不执行」。
- **执行**：触发即创建**独立会话**（不污染当前会话），走完整 agent 链路；无人值守时 ASK 权限动作**自动跳过并记录**，不挂起。
- **watcher**：`watchdog` 监控 `watch_paths`，防抖 5 秒聚合后把变化摘要注入 prompt 触发一次。
- **通知**：完成后 Electron 系统通知（`Notification` API），会话出现在侧边栏。
- **设置**：`automation.scheduler_enabled` / `automation.watcher_enabled`（均默认 off）。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `backend/app/entity/automation.py` + `services/automation_service.py` | 实体 + 调度循环 + 防抖 |
| 新增 | `backend/app/controllers/automation_controller.py` | CRUD + 手动触发 + 运行历史 |
| 扩展 | `electron/src/main/` | 系统通知 |
| 新增 | 前端「自动化」管理页 | 任务列表编辑（设置开关走 27 规范自动渲染） |
| 扩展 | `backend/pyproject.toml` | `watchdog` 依赖 |

## 3. 验收标准

- [ ] 定时任务按 cron 触发，结果出现在独立会话并弹系统通知。
- [ ] watcher 在文件变化 5 秒后聚合触发一次，不风暴。
- [ ] 无人值守时 ASK 动作被跳过并记录，任务不挂起。
