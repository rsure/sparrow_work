# B2 repo 地图与符号级检索（增补：改造后可动态加入）

> 依赖锚点：EXT-5 输出契约（防索引结果爆上下文）。
> 现状 FAISS 是文档级 RAG，agent 找「某个函数在哪」只能 grep 硬翻，费 token 且慢。

## 1. 设计

- **符号索引**：扫描工作区代码文件（`.py/.ts/.vue/.js/.mjs`），用**正则提取**函数 / 类 / 组件定义
  （`def` / `class` / `function` / `const X =` / `defineComponent` 等），存 SQLite：
  `(workspace_id, symbol, kind, file, line)`。首版不用 tree-sitter / LSP——正则够用且零新依赖。
- **repo_map 工具**：`repo_map(path_glob)` 输出目录树 + 每文件符号一行摘要（走 EXT-5 截断），供模型建立全局认知。
- **符号检索工具**：`symbol_search(name, kind?)`，前缀 / 模糊匹配，返回 `(symbol, file:line)` 列表。
- **增量更新**：随扫描模块（`sanner_*`）的文件变更事件刷新；或懒加载「首次访问 + mtime 失效」。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `backend/app/services/symbol_index.py` | 提取 / 存储 / 检索（独立 SQLite，按工作区隔离） |
| 新增 | `backend/app/tools/repo_map_tool.py` | `repo_map` / `symbol_search` 两个只读工具 |
| 扩展 | `backend/app/tools/policy.py` | 只读 ALLOW 注册 |

## 3. 验收标准

- [ ] 「X 函数在哪定义」类问题走 `symbol_search` 一次命中，不再全库 grep。
- [ ] `repo_map` 输出经过 EXT-5 截断，万行项目不爆上下文。
- [ ] 文件修改后索引在下次检索前失效重扫（mtime 校验生效）。
