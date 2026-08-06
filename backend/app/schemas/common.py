"""通用响应模型。"""

# 让类型注解延迟求值（PEP 563），便于用 `X | None` 这种新语法
from __future__ import annotations

# 标准库 typing：Generic 让响应外壳能带类型参数，TypeVar 声明这个可被替换的类型变量
from typing import Generic, TypeVar

# 数据校验：BaseModel 作为模型基类自动做类型校验；Field 给字段写说明（前端 /docs 可见）
from pydantic import BaseModel, Field

# 响应数据的类型占位符：写 ApiResponse[HealthData] 时 T 就被替换成 HealthData
T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应外壳：controller 层统一返回该结构，前端只需处理一种形状。"""

    code: int = Field(default=0, description="业务状态码：0 表示成功，非 0 表示业务失败（如 404 未找到、422 解析失败）")
    message: str = Field(default="ok", description="提示文案：成功固定为 ok，失败时是错误原因，可直接展示给用户")
    data: T | None = Field(default=None, description="业务数据；成功时是具体模型实例，失败时为 null")
