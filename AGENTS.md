# AGENTS.md —— 本项目的基础编码要求（新手学习项目）

> 本文件是**项目级硬性约定**。任何人在本仓库新增或修改代码（包括 AI 助手），都必须先满足下面三条，
> 再谈功能是否实现。评审时按这三条逐项检查，不合规的代码要退回重写。

---

## 0. 项目定位

这是一个**新手学习项目**：Electron（桌面壳）+ Vue3/TypeScript（页面）+ Python/FastAPI（后端）。

学习项目的第一目标不是「跑得快」，而是**每一行代码都能被读懂**。
因此本项目的注释标准比商业项目更严：**宁可多写注释，不要写「猜得出但不确定」的代码。**

目录分工（详细说明见 `项目说明.md`）：

| 目录 | 语言 | 说明 |
| --- | --- | --- |
| `frontend/src/` | TypeScript / Vue3 | 页面、组件、请求封装 |
| `backend/app/` | Python | FastAPI 后端：api → controllers → services → schemas |
| `electron/src/` | TypeScript | Electron 主进程 / preload |
| `scripts/` | Node.js (.mjs) | 开发启动、构建同步等脚本 |

---

## 1. 三条硬性要求

### R1 — 每个字段都要注释说明用途

**定义**：类的属性、Pydantic 模型字段、TypeScript `interface` / `type` 的成员、
常量、模块级变量，**每一个**都要有一句话说明它「是什么、用来干什么、单位/取值范围是什么」。

**Python**

- Pydantic 模型字段：用 `Field(description="...")`（它同时会出现在 `/docs` 接口文档里，是首选写法）。
- `@dataclass` 字段 / 类属性 / 模块级变量：用**上一行的 `#` 注释**或行尾 `#` 注释。

```python
# 进程启动时间，用于计算 uptime（单位：秒，单调时钟）
_STARTED_AT = time.monotonic()


class HealthData(BaseModel):
    """健康检查返回体。"""

    status: str = Field(description="健康状态：ok / degraded")
    uptime_seconds: float = Field(description="本次进程已运行秒数")


@dataclass
class FileInfo:
    """单个文件的扫描结果。"""

    # 文件绝对路径，全局唯一，用作去重主键
    path: str
    # 文件字节数（原始值，格式化交给展示层）
    size: int
```

**TypeScript / Vue**

- `interface` / `type` 的每个成员：在成员**上一行**写 `/** ... */`。

```ts
/** 健康检查数据类型，对应后端 app/schemas/health.py 的 HealthData */
export interface HealthData {
  /** 健康状态：ok=正常，degraded=降级 */
  status: 'ok' | 'degraded'
  /** 本次进程已运行秒数 */
  uptime_seconds: number
}
```

> **禁止**：`a: string`、`count: int` 这种「看名字猜意思」的字段。
> 例如 `status` 必须写清是「哪些取值、各代表什么」，而不是只写「状态」。

---

### R2 — 每个方法 / 函数都要说明用途

**定义**：所有函数、方法（含 Vue 的 composable、`computed`、事件处理函数）都要有一句话说明
**它做什么**；有参数或返回值不好懂时，补一句参数与返回值的含义。

**Python**：用函数内的**第一行三引号 docstring**（不是 `#` 注释），这样 `help()` 也能看到。

```python
def get_health(self) -> HealthData:
    """采集当前进程与运行时的健康快照，供 GET /api/health 使用。"""
```

**TypeScript / Vue**：函数上一行写 `/** ... */`（JSDoc 形式，编辑器悬浮提示会显示）。

```ts
/** 拼接完整接口地址：把 /api 前缀与后端域名补上 */
export function buildUrl(path: string): string {
```

```ts
/** 防抖 ref：写入后 delay 毫秒才真正生效。用于搜索框，避免每敲一个字就请求一次。 */
export function useDebouncedRef<T>(initial: T, delay = 200) {
```

> **禁止**：`/** 获取数据 */` 这种把函数名翻译一遍、信息量为零的注释。
> 要写「为了什么场景、做完之后会发生什么」。

---

### R3 — 每个 import 都要说明用途（为什么引它）

**定义**：每一条 `import` / `from ... import ...` 都要能回答：
**「这条语句是干什么的？引进来之后我用它做什么？」**

对新手来说，这是最重要的一条：读代码时最先卡住的就是「这一堆 import 都是啥」。

**写法**：

1. 一条 import 一行注释：**行尾**加注释（Python `#`，TS `//`）。
2. 多条同源 import 可以合并成一组，在**组的上一行**用块注释统一说明。
3. 相同来源（比如 `vue`）的多条 import，允许在第一条行尾写注释覆盖整组。

**Python**

```python
# 标准库：跨平台读取环境变量、判断冻结（打包）环境
import os
import sys
# 格式化时间戳，返回给前端展示服务器当前时间
from datetime import datetime, timezone
# Web 框架：FastAPI 负责路由与校验，Request 用于异常处理器读取请求
from fastapi import FastAPI, Request
# 开发态跨域：允许 Vite(5173) 直接访问 8000 端口
from fastapi.middleware.cors import CORSMiddleware
# 项目内：全局配置对象（端口、CORS 白名单等）
from app.config import settings
```

**TypeScript**

```ts
// Vue 响应式核心：createApp 创建应用实例
import { createApp } from 'vue'
// 根组件：整个页面的挂载点
import App from './App.vue'
// 路由表：hash 模式路由，适配 Electron 打包后的 file:// 协议
import router from './router'
// Vant 组件库的全量样式（本项目按需注册组件，但样式一次性引入）
import 'vant/lib/index.css'
```

**Vue SFC 内**

```vue
<script setup lang="ts">
// 响应式工具：computed 派生只读状态，ref 声明可变状态
import { computed, ref } from 'vue'
// 接口封装：buildUrl 拿地址，fetchHealth 请求后端
import { buildUrl, fetchHealth, type HealthData } from '@/services'
</script>
```

> **注意**：不要给 `import` 写「引入 vue 库」这种同义反复。
> 要写**在本文件里它承担什么职责**，例如「createApp 创建应用实例」。

---

## 2. 一条 import 的判定标准（自查用）

对每条 import 问自己：

1. 这个包/模块**是什么**？（标准库 / 第三方 / 项目内）
2. 我引它进来**做什么**？
3. 如果只引了一个名字，这个名字对应什么能力？

三个问题都能用一句话回答，才算合格。

---

## 3. 其它配套约定（沿用现有代码风格）

- 注释语言：**中文**。
- 文件（模块）顶部要有**模块级说明**：Python 用模块 docstring，TS/Vue 用文件头 `/** ... */`。
- 块注释用 `#`（Python）/ `//`（TS）；文档注释用 `"""`（Python 函数/类）/ `/** */`（TS）。
- 命名：`snake_case`（Python）、`camelCase`（TS 变量/函数）、`PascalCase`（类/组件）。
  后端接口字段用 `snake_case`，前端类型沿用后端字段名，不做转换（见 `frontend/src/services/types.ts`）。
- 不改动业务逻辑：**本规范只允许增加注释与说明**，不要在补注释时顺手重构行为。

---

## 4. 提交前自查清单

- [ ] 新增的每个字段，都有说明用途的注释 / `Field(description=...)`。
- [ ] 新增的每个函数、方法，都有 docstring 或 JSDoc。
- [ ] 新增的每条 import，都有说明用途的行尾注释或组注释。
- [ ] 文件顶部有模块说明。
- [ ] `pnpm run typecheck` 与 `pnpm run test:backend` 通过（后端/前端改动时）。
- [ ] 改到 `backend_java/` 时 `pnpm run test:backend:java` 通过。
- [ ] 前端代码改动时 `pnpm run test:frontend` 通过；改到 `composables/`、`services/request|http`、
      `components/MarkdownView|FilePathChip` 时，对应的 `frontend/tests/**/*.spec.ts` 要一起更新
      （约定见 `doc/29-前端测试基建.md`）。测试文件本身同样要满足上面四条注释要求。

---

## 5. Java 后端（`backend_java/`）附加规范

Java 侧同样遵守 R1~R3，另外要求：

- 文件顶部有「模块说明」注释；
- 每个类字段、record 组件、枚举常量都要有中文说明；
- 每个方法/构造器都要有中文 Javadoc（做什么、参数、返回、异常）；
- 每条 `import` 行尾都要说明在本文件里的职责；
- 重要 `if/else`、`catch`、边界判断、并发控制必须有「为什么」注释；
- JSON 字段用 `snake_case`，Java 字段用驼峰 + `@JsonProperty`；
- Controller 只做协议适配，业务放在 Service；不要直接 new 模型/图。

完整示例、禁止清单与 AI 提示词模板见
[`doc/java_langchan_doc/04-AI代码生成规范.md`](./doc/java_langchan_doc/04-AI代码生成规范.md)。

---

## Agent skills

### Issue tracker

Issue 与 spec 是 `.scratch/<feature-slug>/` 下的 markdown 文件（本地 Markdown 方式，不用 GitHub Issues）。见 `docs/agents/issue-tracker.md`。

### Domain docs

单上下文布局：仓库根目录一个 `GLOSSARY.md`，加一份 `docs/adr/`。见 `docs/agents/domain.md`。
