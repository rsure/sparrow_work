# 后端（FastAPI + uv）

## 目录分层

```
app/
├─ main.py          # 应用工厂 create_app()：CORS、路由、文档
├─ config.py        # Settings（环境变量前缀 APP_）
├─ constants.py     # IS_PACKAGED 等常量
├─ api/router.py    # 路由聚合：新 controller 在此 include_router
├─ controllers/     # HTTP 协议层：参数校验 + 调用 service + 包 ApiResponse
├─ services/        # 业务层：不 import fastapi，方便单测和复用
└─ schemas/         # Pydantic 模型
```

## 常用命令（在 backend/ 目录执行）

```bash
uv sync                              # 安装依赖（首次）
uv run python run.py --reload        # 开发启动 → http://127.0.0.1:8000
uv run python run.py --port 9000     # 指定端口
uv run pytest                        # 跑测试
uv run pyinstaller --noconfirm --clean app-backend.spec   # 打包成可执行后端
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查，前端首页按钮调用 |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI 描述 |

响应统一为 `{ "code": 0, "message": "ok", "data": {...} }`，对应 `app/schemas/common.py`。

## 配置

见 `app/config.py`，环境变量前缀 `APP_`（可复制 `.env.example` 为 `.env`）：
`APP_ENV`、`APP_HOST`、`APP_PORT`、`APP_API_PREFIX`、`APP_CORS_ORIGINS`、`APP_APP_NAME`、`APP_VERSION`。

打包运行时由 Electron 主进程注入 `APP_PORT` / `APP_PACKAGED=1`。
