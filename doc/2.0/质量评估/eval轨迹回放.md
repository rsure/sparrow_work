# B8 eval：任务轨迹回放与断言（增补：改造后可动态加入）

> 依赖锚点：OPS-6 trace（数据源）。没有 eval，改 prompt / 换 provider / 升级模型后
> 无法知道 agent 是变好还是变坏——这是检验 21~27 全部验收标准是否真达成的手段。

## 1. 设计

- **用例形态**：`scripts/eval/cases/*.yaml`：

```yaml
name: 统计项目TODO并写报告          # 用例名
task: 扫描整个项目统计 TODO 并写报告
workspace: tests/fixtures/demo_repo   # 固定 fixture 工作区，保证可重复
assert:                              # 断言（全部满足才通过）
  - answer_contains: ["TODO", "报告"]   # 最终回答包含关键词
  - tool_sequence_contains: [scan]      # 工具调用序列包含
  - max_cost: 0.5                       # 成本上限（元，UX-5 口径）
  - max_turns: 8                        # 轮次上限
```

- **回放模式**：**真实跑**（真模型 + 工具在 fixture 工作区真实执行）。首版不做工具 mock——
  桌面单机场景真实跑更可信，成本用 B5 的便宜角色模型控制。
- **报告**：`scripts/eval/run.py` 跑全部用例 → 生成 md 报告（通过率 / 平均成本 / 轮次 / 失败用例的 trace 链接）。
- **触发时机**：手动；每次更换默认 provider / 升级 prompt 强烈建议跑。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `scripts/eval/cases/*.yaml`、`scripts/eval/run.py` | 用例与执行器（Node .mjs 或 Python，与 `scripts/` 现有形态对齐） |
| 扩展 | 后端 | 无改动（trace 已有，`run.py` 直接读 trace 表 / 调 chat 接口） |

## 3. 验收标准

- [ ] `run.py` 一键跑通全部用例并输出 md 报告。
- [ ] 换 provider 前后各跑一次，报告能对比出质量 / 成本差异。
- [ ] 失败用例能从报告跳到对应 trace，复现全过程。
