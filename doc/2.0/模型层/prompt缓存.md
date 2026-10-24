# B6 prompt 缓存（增补：改造后可动态加入）

> 依赖锚点：ARCH-1。DeepSeek / OpenAI 服务端自动缓存，Anthropic 需 `cache_control` 标记——
> 是「长系统提示词 + 记忆注入」场景下最直接的成本优化。

## 1. 设计

- **开关** `model.prompt_cache`（默认 on）：factory 构建模型时按 provider 传参。
- **命中率的关键是「前缀稳定」**，因此规定上下文组装顺序（`chat_controller` 组装消息时遵守）：

```
[系统提示词（含 skill 描述，稳定）] → [相关记忆注入段（固定 top_k、确定性排序）] → [历史消息] → [本轮消息]
```

- 记忆注入段排序必须**确定性**（相同输入 → 相同顺序，如按 importance × 相似度得分排序），
  否则每次注入内容变化即全量缓存失效（miss）。
- UX-5 面板补「缓存命中 token」展示（usage 的 `cached_tokens` / `prompt_tokens_details` 字段）。

## 2. 改动文件

| 动作 | 文件 | 内容 |
| --- | --- | --- |
| 扩展 | `backend/app/llm/factory.py` | 缓存参数按 provider 传递（Anthropic 打 cache_control 标记） |
| 扩展 | `backend/app/controllers/chat_controller.py` | 消息组装顺序固定 + 记忆段确定性排序 |
| 扩展 | 前端统计面板（UX-5） | cached_tokens 展示 |

## 3. 验收标准

- [ ] 同会话第 2 轮起 cached_tokens > 0（DeepSeek / OpenAI 验证）。
- [ ] 记忆注入开启时命中率不明显劣化（注入段顺序确定）。
- [ ] 不支持的 provider（如部分 Ollama）静默跳过，不报错。
