"""健康检查相关模型。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 数据校验：BaseModel 作为模型基类自动做类型校验；Field 给字段写说明（前端 /docs 可见）
from pydantic import BaseModel, Field


class HealthData(BaseModel):
    """健康检查返回体（对应前端 services/health.ts 里的 HealthData 类型）。"""

    status: str = Field(description="健康状态：ok=正常；degraded=降级（预留取值，依赖不可用时使用，当前实现恒为 ok）")
    service: str = Field(description="服务标识名，取自配置 app_name，用于区分是哪个后端")
    version: str = Field(description="后端版本号，与配置 Settings.version 一致，用于排查版本不符问题")
    env: str = Field(description="运行环境：development=开发 / production=生产")
    python_version: str = Field(description="当前 Python 解释器版本，如 3.12.4，排查环境依赖问题用")
    platform: str = Field(description="运行平台描述，格式为「系统 版本 (解释器绝对路径)」")
    uptime_seconds: float = Field(description="本次进程已运行秒数，从进程启动开始累计（保留 3 位小数）")
    server_time: str = Field(description="服务器当前时间，ISO8601 字符串（含时区，精确到秒）")
