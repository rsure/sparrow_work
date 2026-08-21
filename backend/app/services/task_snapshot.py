# app/services/task_snapshot.py
"""子任务级文件快照与回滚（TASK Phase 2 §5.3 L4）。

要解决的问题：
    一个子任务可能改了 5 个文件、第 6 个文件校验失败。老链路只会把"校验未通过"
    回给模型重试一次，工作区里却留着半新半旧的文件——用户下次打开项目就懵了。
    所以在子任务**开始前**把它声明要改的文件备份一份，失败时按子任务粒度整体还原。

为什么备份到应用数据目录而不是工作区里：
    工作区里多一个 `.task_snapshots/` 会被扫描、被索引、被用户看到；
    而且工作区本身可能是只读挂载。放在 `data_dir()` 下与日志、密钥同一处，好清理。

为什么记录"原本不存在"的文件：
    回滚时不能只是"把备份复制回去"——如果子任务**新建**了文件，备份里没有它，
    那种情况下正确的动作是**删除**它。所以每条记录都带 `existed` 标志。

所有函数都"失败不抛"（返回结构化结果）：快照只是保险，不能因为它让对话中断。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：复制/删除目录（备份与清理）
import shutil
# 标准库：算内容哈希（回滚前后可对比，也便于日志排查）
import hashlib
# 标准库：路径对象与存在性判断
from pathlib import Path
# 标准库：记录日志（快照失败只记日志，不打断对话）
import logging

# 项目内：用户数据目录（与日志、密钥、诊断包同一处）
from app.core.paths import data_dir

# 本模块的日志器
log = logging.getLogger(__name__)

# 快照根目录名（在 data_dir() 之下）
SNAPSHOT_DIR_NAME = ".task_snapshots"
# 单个文件备份上限（字节）：超过就不备份（多为视频/模型权重，复制一份代价太高）
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


def snapshots_root() -> Path:
    """返回快照根目录（不存在时自动创建）。

    :return: 绝对路径，如 `.../app-backend/.task_snapshots`
    """
    directory = data_dir() / SNAPSHOT_DIR_NAME
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return directory


def _safe_name(raw: str, limit: int = 40) -> str:
    """把 id/文件名变成可安全用于目录名的片段。

    :param raw: 原始文本（子任务 id、文件名等）
    :param limit: 截断长度上限
    :return: 去掉路径分隔符与 Windows 非法字符后的片段；全空时返回 "x"
    """
    cleaned = "".join(ch if ch not in '\\/:*?"<>|' and not ch.isspace() else "_" for ch in str(raw))
    cleaned = cleaned.strip("._-")[:limit]
    return cleaned or "x"


def _digest(path: Path) -> str:
    """算文件内容的 sha256（读不出来时返回空串，不抛异常）。

    :param path: 文件路径
    :return: 十六进制摘要；读失败返回空串
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def snapshot_dir(turn_id: str) -> Path:
    """返回某一轮的快照目录（不存在时自动创建）。

    :param turn_id: 执行轨迹 id（一轮一个）
    :return: 该轮的快照目录
    """
    directory = snapshots_root() / _safe_name(turn_id, 32)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return directory


def snapshot_files(paths: list[str], turn_id: str, subtask_id: str) -> list[dict]:
    """把子任务声明要改的文件备份一份。

    :param paths: 子任务 `files` 里声明的绝对路径（可能不存在，可能重复）
    :param turn_id: 本轮轨迹 id，用作目录名
    :param subtask_id: 子任务 id，用作目录名
    :return: 记录列表，每条形如
             {"path": str, "existed": bool, "backup": str|None, "hash": str, "skipped": str|None}
             回滚时就按这个列表逐条处理（`skipped` 非空表示故意没备份，回滚时也跳过）。
    """
    if not paths:
        return []

    target = snapshot_dir(turn_id) / _safe_name(subtask_id, 32)
    entries: list[dict] = []
    seen: set[str] = set()

    for raw in paths:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        path = Path(text)
        entry: dict = {"path": text, "existed": False, "backup": None, "hash": "", "skipped": None}

        try:
            if not path.is_file():
                # 计划里写了但磁盘上还没有：不算错，回滚时"确保它不存在"
                entries.append(entry)
                continue
            size = path.stat().st_size
            if size > MAX_SNAPSHOT_BYTES:
                entry["skipped"] = f"文件过大（{size} 字节），未快照"
                entries.append(entry)
                continue
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                entry["skipped"] = f"快照目录创建失败：{e}"
                entries.append(entry)
                continue
            # 不同目录下可能有同名文件，加一段内容哈希前缀避免互相覆盖
            backup = target / f"{_digest(path)[:8]}-{_safe_name(path.name, 60)}"
            shutil.copy2(path, backup)
            entry["existed"] = True
            entry["backup"] = str(backup)
            entry["hash"] = _digest(path)
        except OSError as e:
            entry["skipped"] = f"快照失败：{e}"
            log.warning("task_snapshot: 备份 %s 失败：%s", text, e)

        entries.append(entry)

    return entries


def restore(entries: list[dict]) -> dict:
    """按快照记录还原文件。

    处理三种情况：
        1. 备份存在 → 复制回原路径（父目录不存在时重建）
        2. 原本不存在（`existed` 为 False）→ 删除该文件（子任务新建的，回滚要撤掉）
        3. 备份失败/过大（`skipped` 非空）→ 跳过，只记一条说明

    :param entries: `snapshot_files` 的返回值
    :return: {"restored": int, "removed": int, "skipped": list[str], "failed": list[str]}
    """
    restored = 0
    removed = 0
    skipped: list[str] = []
    failed: list[str] = []

    for entry in entries:
        path_text = str(entry.get("path") or "")
        if not path_text:
            continue
        path = Path(path_text)

        if entry.get("skipped"):
            skipped.append(f"{path_text}：{entry['skipped']}")
            continue

        backup_text = entry.get("backup")
        try:
            if backup_text and Path(str(backup_text)).is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(backup_text), path)
                restored += 1
                continue

            if not entry.get("existed") and path.exists():
                # 原本没有、现在有了：这是子任务新建的，回滚就是删掉它
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed += 1
                continue

            # existed=True 但没有备份（备份丢失）：只能记下来，不能瞎猜
            if entry.get("existed"):
                failed.append(f"{path_text}：备份文件已丢失，无法还原")
        except OSError as e:
            failed.append(f"{path_text}：{e}")
            log.warning("task_snapshot: 还原 %s 失败：%s", path_text, e)

    return {"restored": restored, "removed": removed, "skipped": skipped, "failed": failed}


def cleanup(turn_id: str) -> None:
    """删掉某一轮的全部快照（一轮结束后调用，避免数据目录无限增长）。

    :param turn_id: 本轮轨迹 id
    """
    directory = snapshots_root() / _safe_name(turn_id, 32)
    try:
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
    except OSError as e:
        log.warning("task_snapshot: 清理 %s 失败：%s", directory, e)
