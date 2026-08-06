"""通用分页工具：Page 结果容器 + paginate 查询函数。"""

# 标准库 typing：TypeVar 声明可被替换的元素类型，Generic 让 Page 能带类型参数，
# Sequence 用于标注 items 是只读序列（列表、元组都能塞）
from typing import TypeVar, Generic, Sequence
# 标准库：@dataclass 自动生成 __init__/__repr__，Page 只承载数据不需要手写这些方法
from dataclasses import dataclass
# SQLAlchemy 核心：select 构造查询，func 用来 count() 统计总数，Select 用于类型标注
from sqlalchemy import select, func, Select
# SQLAlchemy ORM：Session 负责执行查询
from sqlalchemy.orm import Session

# 分页元素的类型占位符：写 Page[TaskInfo] 时 T 就被替换成 TaskInfo
T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    """分页结果"""
    items: Sequence[T]      # 当前页数据
    total: int              # 总条数
    page: int               # 当前页码(从 1 开始)
    size: int               # 每页条数

    @property
    def pages(self) -> int:
        """总页数：由总条数与每页条数向上取整算出；size 为 0 时返回 0，避免除零。"""
        return (self.total + self.size - 1) // self.size if self.size else 0

    @property
    def has_prev(self) -> bool:
        """是否有上一页（当前页大于 1 时为 True），供前端决定「上一页」按钮是否可点。"""
        return self.page > 1

    @property
    def has_next(self) -> bool:
        """是否有下一页（当前页小于总页数时为 True），供前端决定「下一页」按钮是否可点。"""
        return self.page < self.pages

    def to_dict(self, item_serializer=None) -> dict:
        """把分页结果转成可直接返回给前端的字典。

        :param item_serializer: 可选的单条数据转换函数（如把 ORM 实体转成 dict）；
                                不传则原样输出 items
        :return: 含 items/total/page/size/pages/has_prev/has_next 的字典
        """
        items = (
            [item_serializer(i) for i in self.items]
            if item_serializer
            else list(self.items)
        )
        return {
            "items": items,
            "total": self.total,
            "page": self.page,
            "size": self.size,
            "pages": self.pages,
            "has_prev": self.has_prev,
            "has_next": self.has_next,
        }


def paginate(
    session: Session,
    stmt: Select,
    page: int = 1,
    size: int = 10,
) -> Page:
    """
    通用分页函数

    :param session: SQLAlchemy Session
    :param stmt:    查询语句(不含 limit/offset)
    :param page:    页码,从 1 开始
    :param size:    每页条数
    """
    # 参数保护
    page = max(1, page)
    size = max(1, min(size, 100))  # 限制最大 100 条,防止恶意请求

    # 1. 先算总数(去掉 order_by,提升 count 性能)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = session.scalar(count_stmt) or 0

    # 2. 再查当前页数据
    items = session.scalars(
        stmt.limit(size).offset((page - 1) * size)
    ).all()

    return Page(items=items, total=total, page=page, size=size)
