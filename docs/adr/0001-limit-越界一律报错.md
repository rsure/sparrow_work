# limit 越界一律报错，不静默截断

Status: accepted

## 背景

改之前，`limit` 在仓库里有四种互不相同的处理方式：

- `limit <= 0 ? 20 : Math.min(limit, 100)`（Java `ChatServiceImpl`）：0 和负数被当成「没传」；
- `Math.max(1, Math.min(limit, 50))`（Java `FileServiceImpl`）：静默夹到 [1, 50]；
- `Query(ge=1, le=500)`（Python 多数端点）：越界返回 422；
- 完全不校验（Python `chat_controller` 的两个端点、`rag_store_controller.list_docs`）：`?limit=1000000` 直接交给 SQL。

同一个 `GET /api/chat/history/sessions/{id}`，Java 把 200 截成 100、Python 原样接受 200，前端还硬编码着 `limit=200`。
调用方既拿不到「被截断」的信号，也没有 `has_more` 可看——窗口之外的数据等于悄悄消失。

## 决定

1. **默认值只表达「不传」**：省略 `limit` 时用后端声明的默认值；显式传 0、负数或超过上限，一律报错（Java `400` / Python `422`）。
2. **默认值与上限集中一张表**：Java 用 `common/PageLimits.java`，Python 用 `app/core/limits.py`，两组常量逐项对应，改一处必须同步另一处。
3. **校验放在入口层**：HTTP 端点用声明式校验（Java `@Min/@Max` + `@Validated`，Python `Query(ge=1, le=MAX)`）；非 HTTP 入口（工具、内部服务调用）继续用 `clamp` 兜底，不让负数进 SQL。
4. **窗口信息要能被调用方看见**：`chat history` 响应新增 `has_more`，用「多取一条」（`limit + 1`）判断，不额外做 `COUNT`。
5. **前端不传 `limit`**：条数由后端默认值决定，前端不再硬编码 200 / 20。

## 考虑过的替代方案

- **维持静默 clamp**：改动最小，但调用方永远不知道结果被截断，前端也无法实现「加载更早」。
- **只在前端限制**：`curl`、第三方脚本、两个后端之间仍然各说各话，问题只是从界面挪到接口之外。
- **超限时返回 `warnings` 头或截断标记**：表达能力更强，但要同时改两套后端、两套客户端，收益不抵复杂度。

## 后果

- `?limit=0` 从「拿到 20 条」变成 `400/422`。这是有意的破坏性变更：0 不是一个合法的「一次要 0 条」请求。
- Python 的 `GET /api/rag/documents` 首次有了上限（200）。以前它能一次拉全库文档列表。
- 两端数字必须保持同步。`PageLimits.java` 与 `limits.py` 的注释互相点名，评审时按表核对。
