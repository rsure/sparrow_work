# B4 记忆管理 UI（增补：改造后可动态加入）

> 依赖锚点：MEM 落地 + UX-1（右栏 ContextPanel）。
> 没有可视化管理，用户无法信任自动记忆——不知道它记了什么、记错了什么。

## 1. 设计

- **位置**：UX-1 右栏 ContextPanel 加「记忆」Tab（或独立路由 `/memory`）。
- **能力**：
  - 列表按 category / scope / 关键词筛选（依赖 B3 的 scope 字段；B3 未落地时按现状 category 筛选）；
  - 单条编辑（content / category / importance）与删除（软删 30 天可恢复）；
  - 手动添加；
  - **来源跳转**：点 `session_id` 跳到来源会话位置。
- **透明化**：本会话注入了哪些记忆，在右栏展示——与「注入内容只给模型看、不向用户复述」不冲突（用户侧始终可见）。
- **设置区**：`memory.top_k` / `memory.dedupe_threshold` / `memory.importance_min` 滑杆，走 27 规范在设置页「高级」分区自动出现。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `frontend/src/components/memory/MemoryPanel.vue` 等 | 列表 / 编辑 / 筛选组件 |
| 扩展 | `frontend/src/services/memory.ts` | 补管理接口封装 |
| 扩展 | `backend/app/controllers/memory_controller.py` | 列表接口加筛选参数（既有 6 接口上扩展） |

## 3. 验收标准

- [ ] 用户可查看本工作区与 user 层全部记忆，可改、可删、可手动加。
- [ ] 「本会话注入的记忆」在右栏可见。
- [ ] 千条记忆下筛选与分页不卡。
