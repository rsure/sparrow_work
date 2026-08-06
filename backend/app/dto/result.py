"""通用返回体 DTO：给不经过 FastAPI 响应模型包装的调用提供统一返回结构。"""

# 标准库：@dataclass 自动生成 __init__/__repr__，Result 只承载数据
from dataclasses import dataclass
# 标准库 typing：Generic/TypeVar 让 Result 能带类型参数，Optional 表示 data 可以为 None
from typing import Generic, TypeVar, Optional
# 承载数据的类型占位符：写 Result[dict] 时 T 就被替换成 dict
T = TypeVar("T")

@dataclass
class Result(Generic[T]):
    """统一返回体：code + message + 可选 data。"""
    # 业务状态码：200 表示成功，其它值表示失败原因（如 404 未找到、500 内部错误）
    code: int
    # 提示文案：成功固定是 success，失败时为错误说明
    message: str
    # 业务数据；失败时可以省略，默认 None
    data: Optional[T] = None

    @staticmethod
    def success(data: T = None) -> "Result[T]":
        """构造成功返回：code 固定 200、message 固定 success。

        :param data: 要携带的业务数据，可以为 None（表示只关心成功与否）
        :return: 成功语义的 Result 实例
        """
        return Result(code=200 , message="success", data=data)

    @staticmethod
    def error(code: int, message: str) -> "Result[T]":
        """构造失败返回：data 留空，只带错误码与原因。

        :param code: 业务错误码，如 404、500
        :param message: 错误提示文案
        :return: 失败语义的 Result 实例
        """
        return Result(code=code, message=message)
