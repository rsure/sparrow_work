# B1 git 工具（增补：改造后可动态加入）

> 依赖锚点：EXT-3 工具注册表（M4），无其它前置。
> 价值：对 coding agent，git 既是**安全网**（改坏可回滚）也是**工具**（diff/blame 定位问题），优先级高于 EXT-3 里的 `sql_query` / `browser`。

## 1. 工具清单与权限

| 工具 | 用途 | 权限（policy.py 三态） |
| --- | --- | --- |
| `git_diff` | 工作区 / 暂存 / 某次提交的 diff | 只读 ALLOW |
| `git_log` | 提交历史（文件 / 作者 / 时间段过滤） | 只读 ALLOW |
| `git_blame` | 某文件某行的最后修改来源 | 只读 ALLOW |
| `git_commit` | 暂存并提交（message 必填） | 需确认 ASK |
| `git_revert_paths` | 把指定文件恢复到某提交（单文件级 checkout，不动全库） | 需确认 ASK |

- 全部工具只对**当前 active 工作区**（ARCH-3）内的 git 仓库生效，非 git 目录返回明确错误。
- diff 输出走 **EXT-5 输出外壳**（大 diff 截断 + 续读）。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `backend/app/tools/git_tool.py` | 上述 5 个工具（subprocess 调 git，禁 `shell=True`，防注入） |
| 扩展 | `backend/app/tools/policy.py` | 三态权限注册（`verify_all_tools_registered` 自检通过） |
| 扩展 | 前端工具轨迹卡片 | diff 用 UX-3 的代码高亮渲染 |

## 3. 验收标准

- [ ] agent 能通过 diff + blame 回答「这行是谁、什么时候、为什么改的」。
- [ ] commit / revert 弹确认；revert 后文件内容与目标提交一致。
- [ ] 非 git 工作区调用返回友好错误，不崩。
