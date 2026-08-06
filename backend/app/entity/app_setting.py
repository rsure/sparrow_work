# app/entity/app_setting.py
"""应用级设置表：键值对形式保存用户配置（工作区、默认开关等）。"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# SQLAlchemy：列类型与 ORM 基类
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

# 项目内：ORM 基类
from app.entity.models import Base


class AppSetting(Base):
    """一条应用设置（key → value 的字符串值，JSON 内容自行序列化）。"""

    # 表名
    __tablename__ = "app_settings"

    # 设置键，作为主键（如 "workspace_roots"）
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 设置值（列表/对象以 JSON 字符串存储）
    value: Mapped[str] = mapped_column(Text, default="")