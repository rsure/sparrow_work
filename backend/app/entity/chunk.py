"""元数据表实体 Chunk：一个可检索、可溯源的文本切片。

注意：本文件映射的表名是 ``mata_data``，与 app/entity/models.py 里的 ``Chunk``（表 ``chunks``）
同名但不是同一张表，改动前请先确认调用方用的是哪一个。
"""
# 给类自动生成 __init__ / __eq__ / __repr__（本类配合 SQLAlchemy 声明式实体使用）
from dataclasses import dataclass
# 计算切片正文的摘要：content_hash 属性用它做增量索引的内容比对
import hashlib
# SQLAlchemy 列类型：String(长度) 变长字符串、Integer 整数
from sqlalchemy import String, Integer
# ORM 三件套：Mapped 标注列类型、mapped_column 声明列、reconstructor 标记「从库加载后」的钩子
from sqlalchemy.orm import Mapped, mapped_column, reconstructor
# 项目内：SQLAlchemy 声明式基类，继承它才能把本类映射成数据库表
from app.db.db_config import Base

'''
元数据表
'''
@dataclass
class Chunk(Base):
    """元数据表实体：一行 = 文档里的一个切片，记录位置、内容与所用向量模型。"""

    # 物理表名：存放切片元数据的表
    __tablename__ = "mata_data"
    # 主键：切片 id（32 位十六进制字符串，由调用方生成）
    id : Mapped[str] = mapped_column(String(32), primary_key=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)  # 引用溯源：「来自docs/PLAN.md」。没它回答无法验证
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 去重与合并（相邻块可拼回一段）；调试定位
    start_line: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 切片起始行号（1 起始），用于跳回原文
    end_line: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 让用户跳回原文；也是你排查切片 bug 的唯一手段
    heading_path: Mapped[str] = mapped_column(String(500))  # ① 给 chunk 补语义前缀；② 前端按章节折叠展示
    content_hash: Mapped[str] = mapped_column(String(500))  # 增量索引：内容没变就不重新向量化（省钱）
    model: Mapped[str] = mapped_column(String(100))  # 记录向量由哪个模型算的。换模型必须整库重建（见 22.2）

    @property
    def locator(self) -> str:
        """给人看的引用定位串，例：docs/PLAN.md:113-116（路径:起始行-结束行）。"""
        return f"{self.path}:{self.start_line}-{self.end_line}"

    @property
    def content_hash(self) -> str:
        """按正文 self.text 现算 SHA-1 十六进制串。

        注意：本类里 content_hash 被定义了两次（上面的 mapped_column 与这里的 @property），
        且 self.text 并不是本类的映射列 —— 这两处疑似遗留问题，本次只补注释、未做任何改动。
        """
        return hashlib.sha1(self.text.encode("utf-8")).hexdigest()
