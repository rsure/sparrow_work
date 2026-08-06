"""文件类型工具：把路径判成文件大类（FileKind），以及字节数的人读格式化。"""
# pathlib.Path：借 path.name / path.suffix 判断文件类型
from pathlib import Path
# typing：Literal 限定字符串取值集合，Mapping/Sequence 标注只读容器，Final 表示常量不再被重新赋值
from typing import Literal, Mapping, Sequence, Final


# ---------- 工具函数（提前定义） ----------
def human_size(n: int | float) -> str:
    """字节数转人类可读，如 1536 -> 1.50 KB

    :param n: 字节数（负数保留负号，按绝对值换算）
    :return: 形如 "512 B" / "1.50 KB" / "2.00 MB" 的字符串，最大到 EB
    """
    if n < 0:
        return f"-{human_size(-n)}"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} EB"


# ---------- 文件类型处理 ----------
# 文件大类：只有这 7 个取值，其他模块的类型标注与统计分组都以它为准
FileKind = Literal["document", "image", "video", "audio", "archive", "code", "other"]

# 大类 → 中文展示名，仅用于界面与报告文案，不参与任何逻辑判断
KIND_CN: Final[Mapping[FileKind, str]] = {
    "document": "文档",
    "image":    "图片",
    "video":    "视频",
    "audio":    "音频",
    "archive":  "压缩包",
    "code":     "代码",
    "other":    "其他",
}

# 大类 → 归属的扩展名（小写、带点）；这是"扩展名判断类型"的原始数据来源
KIND_TO_EXT: Final[Mapping[FileKind, Sequence[str]]] = {
    "document": (".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"),
    "image":    (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"),
    "video":    (".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"),
    "audio":    (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"),
    "archive":  (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"),
    "code":     (".ts", ".js", ".py", ".java", ".vue", ".json",
                 ".toml", ".yaml", ".yml", ".rs", ".go", ".sh"),
}

# 扩展名 → 大类的反查表：由 KIND_TO_EXT 反转生成，查一次就出结果，不必每次遍历原表
EXT_TO_KIND: Final[Mapping[str, FileKind]] = {
    ext: kind for kind, exts in KIND_TO_EXT.items() for ext in exts
}

# 没有扩展名、但有固定文件名的特例 → 大类（键均为小写）
_NAME_TO_KIND: Final[Mapping[str, FileKind]] = {
    "makefile": "code",
    "dockerfile": "code",
    ".gitignore": "code",
}


def get_kind(path: Path) -> FileKind:
    """判断一个文件属于哪个大类。

    场景：扫描时给每个 FileInfo 打类型标签，供分组统计与按类型筛选。
    先按完整文件名查特例（Makefile 等），再按扩展名查 EXT_TO_KIND，都没有则归为 "other"。

    :param path: 文件路径（只用到文件名与扩展名，不读文件内容）
    :return: 7 个大类之一，取值见 FileKind
    """
    name = path.name.lower()
    if name in _NAME_TO_KIND:
        return _NAME_TO_KIND[name]
    return EXT_TO_KIND.get(path.suffix.lower(), "other")


# ---------- 数据模型 ----------


