"""目录扫描服务：递归遍历目录，产出 FileInfo 列表与跳过记录（纯同步、不涉及 HTTP 与数据库）。"""
# pathlib.Path：路径对象，做存在性/类型判断并拼子路径
from pathlib import Path
# datetime：把 stat 的修改时间戳（st_mtime）转成 datetime
from datetime import datetime
# dataclass：把扫描开关收敛成 ScanOptions 配置对象
from dataclasses import dataclass

# 项目内：单个文件的扫描结果快照
from app.entity.file_Info import FileInfo
# 项目内：按文件名/扩展名判断文件大类
from app.entity.file_kind import get_kind
# 项目内：扫描结果集合（文件列表 + 跳过记录）
from app.entity.scan_result import ScanResult
# 项目内：带状态码的业务异常，控制器会据此返回对应 HTTP 状态
from app.schemas.scan_exception import ScanException


# ---------- 扫描配置 ----------
@dataclass
class ScanOptions:
    """扫描行为配置"""
    skip_hidden: bool = True       # 跳过 . 开头的文件和目录
    skip_symlink: bool = True      # 跳过符号链接
    follow_symlink_dir: bool = False  # 是否跟随软链接目录（os.walk 用）
    # 黑名单目录名（按目录名精确匹配，不区分路径）：出现在这些目录里的文件一律不扫
    skip_dirs: frozenset[str] = frozenset({
        # 常见无需扫描的目录
        ".git", ".svn", ".hg",
        "node_modules", "__pycache__",
        ".venv", "venv", ".idea", ".vscode",
    })


def startScan(
    path: str,
    *,
    options: ScanOptions | None = None,
) -> ScanResult:
    """
    扫描指定目录。

    :param path: 绝对路径
    :param options: 扫描配置，None 用默认
    :return: ScanResult
    """
    opts = options or ScanOptions()
    p = Path(path)

    # ---- 输入校验 ----
    if not p.is_absolute():
        raise ScanException(500, "只能输入绝对路径，如 F:\\demo")
    if not p.exists():
        raise ScanException(404, f"路径不存在: {p}")
    if not p.is_dir():
        raise ScanException(400, f"不是目录: {p}")

    files, skipped = scanDir(p, opts)
    return ScanResult(path=str(p), files=files, skipped=skipped)


def scanDir(
    path: Path,
    options: ScanOptions | None = None,
) -> tuple[list[FileInfo], list[str]]:
    """
    递归扫描目录，返回 (文件列表, 跳过记录)。

    任何单个文件/目录的异常都会被记录到 skipped，不影响整体流程。
    """
    opts = options or ScanOptions()
    files: list[FileInfo] = []
    skipped: list[str] = []

    # 单文件直接处理
    if path.is_file():
        info, err = _safe_get_file_info(path, opts)
        if info:
            files.append(info)
        if err:
            skipped.append(err)
        return files, skipped

    # 目录：用 os.walk 以便剪枝和容错
    import os       # 标准库：递归遍历目录树（os.walk），支持原地剪枝与 onerror 容错

    for root, dirs, names in os.walk(
        path,
        topdown=True,
        onerror=lambda e: skipped.append(f"[目录访问失败] {e.filename}: {e.strerror}"),
        followlinks=opts.follow_symlink_dir,
    ):
        # 原地剪枝：跳过隐藏目录 / 黑名单目录 / 软链接目录
        pruned = []
        for d in dirs:
            full = Path(root) / d

            if opts.skip_hidden and d.startswith("."):
                skipped.append(f"[跳过隐藏目录] {full}")
                continue
            if d in opts.skip_dirs:
                skipped.append(f"[跳过目录] {full}")
                continue
            if opts.skip_symlink:
                try:
                    if full.is_symlink():
                        skipped.append(f"[跳过软链接目录] {full}")
                        continue
                except OSError as e:
                    skipped.append(f"[软链接检查失败] {full}: {e}")
                    continue
            pruned.append(d)
        dirs[:] = pruned  # 关键：原地修改生效

        # 处理文件
        for name in names:
            full = Path(root) / name
            info, err = _safe_get_file_info(full, opts)
            if info:
                files.append(info)
            if err:
                skipped.append(err)

    return files, skipped


def _safe_get_file_info(
    file: Path,
    opts: ScanOptions,
) -> tuple[FileInfo | None, str | None]:
    """
    安全构造 FileInfo。返回 (FileInfo | None, 错误信息 | None)。
    不会抛异常。
    """
    try:
        # 1. 跳过隐藏文件
        if opts.skip_hidden and file.name.startswith("."):
            return None, f"[跳过隐藏文件] {file}"

        # 2. 跳过符号链接
        if opts.skip_symlink and file.is_symlink():
            return None, f"[跳过软链接] {file}"

        # 3. 跳过目录（防止传入目录）
        if file.is_dir():
            return None, None

        # 4. 取 stat 一次，复用
        st = file.stat()

        return (
            FileInfo(
                path=file,
                name=file.name,
                kind=get_kind(file),
                is_directory=False,
                file_size=st.st_size,
                modified_at=datetime.fromtimestamp(st.st_mtime),
            ),
            None,
        )
    except PermissionError as e:
        return None, f"[权限拒绝] {file}: {e.strerror or e}"
    except FileNotFoundError as e:
        return None, f"[文件不存在/断链] {file}: {e.strerror or e}"
    except OSError as e:
        return None, f"[IO错误] {file}: {e.strerror or e}"
    except Exception as e:
        # 兜底，绝不让扫描崩
        return None, f"[未知错误] {file}: {type(e).__name__}: {e}"


# ---------- 使用示例 ----------
if __name__ == "__main__":
    # 默认配置：跳过隐藏 + 跳过软链接
    result = startScan(r"D:\Users\leade\downloads")
    print(result.to_json())

    # 自定义配置：保留隐藏文件，跳过软链接
    opts = ScanOptions(skip_hidden=False, skip_symlink=True)
    result = startScan(r"D:\Users\leade\downloads", options=opts)
    print(result.to_json())