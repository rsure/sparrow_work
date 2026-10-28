# sparrow_work 的通用语言

sparrow_work 是一个「Electron 壳 + Vue3 页面 + Python/Java 双后端」的桌面学习项目。
这份词汇表只收录**跨语言接口**与**对话域**里反复出现、又最容易被叫混的词——
改代码前先在这里对齐用词，接口两端（`backend/` 与 `backend_java/`）才不会各说各话。

## 分页与窗口

**limit（单次窗口）**:
一次请求最多返回多少条记录；只表达「这一次要多少」，不表达「总共有多少」。
_Avoid_: pageSize、size、count、top

**默认值（default limit）**:
调用方不传 limit 时后端采用的条数。默认值只在后端声明一处（Java 的 `PageLimits`、Python 的 `limits.py`），前端不猜、不复制。
_Avoid_: 前端默认、fallback 值

**上限（max limit）**:
单个端点允许的最大 limit。显式传超过上限的值属于调用错误，直接报错（Java 400 / Python 422），不静默截断成上限。
_Avoid_: cap、capacity、最大条数（说不清是「上限」还是「默认」）

**has_more**:
响应里的布尔字段，表示「窗口之外、更早的一侧还有记录」。它只回答「还有没有」，不回答「一共有多少」。
_Avoid_: hasNext、more、total、count（这些词会让人以为能算总数）

## 对话记录

**会话（session）**:
一次持续对话的单位，有标题、置顶、归档三个状态；消息（message）都挂在会话下面。
_Avoid_: thread、conversation、chat（chat 指整个功能，不是单个会话）

**轮次（turn）**:
会话里一次「用户提问 + 助手回答」的完整交互。一条用户消息加一条助手消息构成一轮。
_Avoid_: 对话、条目（entry）

**归档箱（archived）**:
会话的第二种存放位置：归档后不出现在默认列表里，但仍可检索与恢复。
_Avoid_: 回收站、垃圾箱（删掉的会话才是真没了）
