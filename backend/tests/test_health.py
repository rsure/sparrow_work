"""健康检查接口自测。

运行方式：在 backend/ 目录执行 `uv run pytest`（或项目根目录 `pnpm run test:backend`）。
"""

# 让类型注解延迟求值（PEP 563），这样旧版 Python 也能写 X | None 这类新语法
from __future__ import annotations

# 测试客户端：不真正监听端口，直接在进程内调用 FastAPI 应用
from fastapi.testclient import TestClient

# 被测对象：项目根应用实例（里面已装配 /api 路由与全局配置）
from app.main import app

# 全局复用的测试客户端，等价于「一个已经连上后端的浏览器」
client = TestClient(app)


def test_health_ok() -> None:
    """GET /api/health 应返回 200 且 code=0，并带上解释器版本等运行时信息。"""
    # 发起请求
    resp = client.get("/api/health")
    # 断言 HTTP 层成功
    assert resp.status_code == 200
    # 取出统一响应外壳 { code, message, data }
    body = resp.json()
    # 断言业务层成功
    assert body["code"] == 0
    # 断言健康状态为 ok
    assert body["data"]["status"] == "ok"
    # 断言返回了运行时字段（前端首页会展示它）
    assert "python_version" in body["data"]
