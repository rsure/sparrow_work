"""一次目录扫描的结果集合：文件明细 + 跳过记录，以及文本 / Markdown / JSON 三种导出格式。"""
# dataclass 自动生成 __init__；field(default_factory=...) 让每个实例拿到各自的空列表（避免可变默认值被共享）
from dataclasses import dataclass, field
# defaultdict：分组统计时"首次访问自动建 [0, 0]"，省掉 if 判断
from collections import defaultdict
# json：to_json() 把结果导出成 JSON 字符串（接口返回或写文件）
import json

# 项目内：单个文件的扫描快照
from app.entity.file_Info import FileInfo
# 项目内：文件大类枚举、字节数人读格式化、大类的中文名
from app.entity.file_kind import FileKind, human_size, KIND_CN


@dataclass
class ScanResult:
    """一次扫描的结果：根路径 + 文件明细 + 跳过记录。"""

    # 扫描的根路径（字符串，直接展示给用户）
    path: str
    # 扫描到的全部文件（不截断），Top N 只影响导出时的展示
    files: list[FileInfo] = field(default_factory=list)
    # 被跳过的文件/目录及原因文本（如 "[跳过隐藏目录] ..."），用于排查"为什么没扫到"
    skipped: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        """所有文件字节数之和（单位：字节）。"""
        return sum(f.file_size for f in self.files)

    @property
    def total_count(self) -> int:
        """扫描到的文件个数。"""
        return len(self.files)

    def group_by_kind(self) -> dict[FileKind, tuple[int, int]]:
        """按文件大类分组统计，供报表的"按类型统计"区块使用。

        :return: {大类: (文件数, 总字节数)}，只包含实际出现的大类
        """
        counter: dict[FileKind, list[int]] = defaultdict(lambda: [0, 0])
        for f in self.files:
            counter[f.kind][0] += 1
            counter[f.kind][1] += f.file_size
        return {k: (v[0], v[1]) for k, v in counter.items()}

    def top_x(self, x: int = 10) -> list[FileInfo]:
        """取体积最大的前 x 个文件。

        :param x: 取多少个；<= 0 时返回空列表（调用方无需自己判断边界）
        :return: 按 file_size 降序排列的文件列表
        """
        if x <= 0:
            return []
        return sorted(self.files, key=lambda f: f.file_size, reverse=True)[:x]

    # ---------------- 格式化 ----------------
    def tostring(
        self,
        *,
        top_n: int = 10,
        show_kinds: bool = True,
        show_top: bool = True,
        show_skipped: bool = True,
    ) -> str:
        """渲染成终端友好的纯文本报告（表头 + 按类型统计 + Top N 大文件 + 跳过项）。

        场景：命令行调试、脚本里直接打印扫描结果。
        :param top_n: "最大 N 个文件"区块列出多少个
        :param show_kinds: 是否输出"按类型统计"区块
        :param show_top: 是否输出"最大 N 个文件"区块
        :param show_skipped: 是否输出"跳过的文件"区块
        :return: 多行字符串（各区块宽度统一按 62 列排版）
        """
        W = 62  # 报告总宽度（字符数），标题栏与分隔线都用它
        lines: list[str] = []

        # 标题栏
        lines.append("=" * W)
        lines.append("扫描结果 (ScanResult)".center(W))
        lines.append("=" * W)
        lines.append(f"路径      : {self.path}")
        lines.append(f"文件总数  : {self.total_count:,}")
        lines.append(f"总大小    : {human_size(self.total_size)}"
                     f"  ({self.total_size:,} 字节)")
        if self.skipped:
            lines.append(f"跳过      : {len(self.skipped)} 项")
        lines.append("-" * W)

        # 按类型分组
        if show_kinds and self.files:
            groups = self.group_by_kind()
            total = self.total_size or 1   # 防除零：没有文件时用 1 占位

            lines.append("按类型统计:")
            lines.append(f"  {'类型':<10}{'数量':>8}{'大小':>14}{'占比':>10}")
            lines.append("  " + "-" * 44)

            for kind, (cnt, size) in sorted(
                groups.items(), key=lambda x: -x[1][1]
            ):
                label = f"{kind}({KIND_CN.get(kind, kind)})"
                pct = size / total * 100
                bar = "█" * int(pct / 5)   # 每个方块代表 5% 占比
                lines.append(
                    f"  {label:<10}{cnt:>8,}{human_size(size):>14}"
                    f"{pct:>9.1f}%  {bar}"
                )
            lines.append("-" * W)

        # Top N 大文件
        if show_top and self.files:
            lines.append(f"最大 {top_n} 个文件:")
            for i, f in enumerate(self.top_x(top_n), 1):
                p = str(f.path)
                if len(p) > 44:
                    p = p[:20] + "..." + p[-21:]   # 中间省略，保留头尾便于辨认
                lines.append(
                    f"  {i:>2}. {human_size(f.file_size):>10}  "
                    f"[{f.kind:<8}] {p}"
                )
            if self.total_count > top_n:
                rest = self.total_count - top_n
                lines.append(f"  ... 还有 {rest:,} 个文件未列出")
            lines.append("-" * W)

        # 跳过项
        if show_skipped and self.skipped:
            lines.append(f"跳过的文件 ({len(self.skipped)}):")
            for s in self.skipped[:10]:    # 最多列 10 条，避免刷屏
                lines.append(f"  ! {s}")
            if len(self.skipped) > 10:
                lines.append(f"  ... 还有 {len(self.skipped) - 10} 项")
            lines.append("-" * W)

        lines.append("=" * W)
        return "\n".join(lines)

    def __str__(self) -> str:
        """print(result) / str(result) 时等价于 tostring()，方便脚本里直接打印。"""
        return self.tostring()

    def to_markdown(self, *, top_n: int = 10) -> str:
        """渲染成 Markdown 报告（标题 + 摘要 + 类型统计表 + Top N 列表）。

        场景：写进笔记、PR 描述或前端富文本展示。
        :param top_n: "最大 N 个文件"区块列出多少个
        """
        lines = [f"# 扫描结果: `{self.path}`", ""]
        lines.append(f"- 文件数: **{self.total_count:,}**")
        lines.append(f"- 总大小: **{human_size(self.total_size)}**")
        if self.skipped:
            lines.append(f"- 跳过: **{len(self.skipped)}** 项")
        lines.append("")
        lines.append("## 按类型统计")
        lines.append("")
        lines.append("| 类型 | 数量 | 大小 | 占比 |")
        lines.append("|------|-----:|-----:|-----:|")
        total = self.total_size or 1   # 防除零
        for kind, (cnt, size) in sorted(
            self.group_by_kind().items(), key=lambda x: -x[1][1]
        ):
            lines.append(
                f"| {kind} | {cnt:,} | {human_size(size)} | "
                f"{size / total * 100:.1f}% |"
            )

        if self.files:
            lines.append("")
            lines.append(f"## 最大 {top_n} 个文件")
            lines.append("")
            for i, f in enumerate(self.top_x(top_n), 1):
                lines.append(
                    f"{i}. `{f.path}` — {human_size(f.file_size)}"
                )
        return "\n".join(lines)

    def to_json(self, indent: int = 2, *, top_n: int = 10) -> str:
        """渲染成 JSON 字符串（含分组统计与 Top N）。

        场景：接口返回、写文件留档；ensure_ascii=False 保证中文不被转义成 \\uXXXX。
        :param indent: 缩进空格数
        :param top_n: "top" 数组里保留多少个文件
        """
        return json.dumps(
            {
                "path": self.path,
                "total_count": self.total_count,
                "total_size": self.total_size,
                "total_size_human": human_size(self.total_size),
                "groups": {
                    k: {
                        "count": c,
                        "size": s,
                        "size_human": human_size(s),
                    }
                    for k, (c, s) in self.group_by_kind().items()
                },
                "top": [
                    {
                        "path": str(f.path),
                        "size": f.file_size,
                        "size_human": human_size(f.file_size),
                        "kind": f.kind,
                        "modified_at": f.modified_at.isoformat(),
                    }
                    for f in self.top_x(top_n)
                ],
                "skipped": self.skipped,
            },
            ensure_ascii=False,
            indent=indent,
        )
