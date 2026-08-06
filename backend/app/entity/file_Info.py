"""文件信息实体：扫描结果里单个文件的不可变快照，以及它的 dict / JSON 序列化形状。"""
# dataclass 自动生成 __init__/__eq__/__repr__；frozen/slots 在下面类的装饰器上说明
from dataclasses import dataclass
# pathlib.Path：用对象表示文件路径，跨平台处理分隔符，并直接拿 name / suffix
from pathlib import Path
# 记录文件最后修改时间；发给前端前统一转成 ISO8601 字符串
from datetime import datetime

# 项目内：文件大类枚举（document / image / code ...），由扩展名推导而来
from app.entity.file_kind import FileKind


# frozen=True：实例创建后不可修改，可安全共享/当字典键；slots=True：省内存且防止拼错属性名
@dataclass(frozen=True, slots=True)
class FileInfo:
    """单个文件的扫描结果快照。"""

    # 文件绝对路径（Path 对象），全局唯一，用作去重主键
    path: Path
    # 文件名（含扩展名、不含目录），如 PLAN.md，用于列表展示
    name: str
    # 文件字节数（原始值，格式化成人读形式交给展示层）
    file_size: int
    # 文件大类：document / image / video / audio / archive / code / other
    kind: FileKind
    # 是否目录：本模型描述的是文件，恒为 False，保留该字段是为了序列化形状统一
    is_directory: bool
    # 最后修改时间（本地时区的 datetime，输出接口时转 ISO8601）
    modified_at: datetime

    def to_dict(self) -> dict:
        """转成下划线命名的 dict：用于落库（task_info.files_json）与后端内部传递。"""
        return {
            "path": str(self.path),
            "name": self.name,
            "file_size": self.file_size,
            "kind": self.kind,
            "is_directory": self.is_directory,
            "modified_at": self.modified_at.isoformat(),
        }

    def to_api_dict(self) -> dict:
        """前端 FileEntry（services/file.ts）需要的 camelCase 形状，供流式/接口响应用。"""
        return {
            "path": str(self.path),
            "name": self.name,
            "fileSize": self.file_size,
            "kind": self.kind,
            "isDirectory": self.is_directory,
            "modifiedAt": self.modified_at.isoformat(),
            "indexed": False,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileInfo":
        """to_dict 的逆操作：把落库的下划线 dict 还原成 FileInfo。

        场景：task_service 读历史任务时把 files_json 还原成文件列表。
        :param d: to_dict 产生的 dict（modified_at 为 ISO8601 字符串）
        :return: 还原后的 FileInfo
        """
        return cls(
            path=Path(d["path"]),
            name=d["name"],
            file_size=d["file_size"],
            kind=d["kind"],
            is_directory=d["is_directory"],
            modified_at=datetime.fromisoformat(d["modified_at"]),
        )
