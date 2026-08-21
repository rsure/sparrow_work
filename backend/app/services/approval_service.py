# app/services/approval_service.py
"""工作区级授权（UX-7 `permission.mode=workspace`）的读写。

调用链只有四处：
    - `tools/policy.py` 的 `_resolve_ask()`：决策前查 exists()，用户勾了"记住"就 upsert()；
    - `setting_controller` 的 `/settings/approvals`：列出 / 撤销（可选能力）；
    - 删除工作区时清理该工作区的授权（见 workspace_service，可选）；
    - 测试直接调用。

失败语义（重要）：
    查询失败一律当作"没有授权"（返回 False）——即回到"每次询问"，
    绝不会因为读库出错而放行一个本该确认的操作。这是 fail-safe 的方向。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# SQLAlchemy：select 查询、delete 批量删除
from sqlalchemy import delete, select

# 项目内：会话上下文管理器（自动 commit / rollback）
from app.db.db_config import get_session
# 项目内：授权表实体
from app.entity.approval import Approval


def exists(workspace_id: str, tool: str) -> bool:
    """查询某工作区是否已授权过某工具（决策前的唯一判断入口）。

    :param workspace_id: 工作区 id；空串直接返回 False（没有工作区就没有"工作区授权"这回事）
    :param tool: 工具名
    :return: 已授权返回 True
    """
    if not workspace_id or not tool:
        return False
    try:
        with get_session() as s:
            row = s.scalars(
                select(Approval.id)
                .where(Approval.workspace_id == workspace_id, Approval.tool == tool)
                .limit(1)
            ).first()
            return row is not None
    except Exception:
        # 读库失败 → 当作没授权 → 回到"每次询问"，方向必须偏严
        return False


def upsert(workspace_id: str, tool: str, kind: str = "", target: str = "") -> None:
    """写入（或刷新）一条授权记录。已存在时只更新 kind/target，不重复插入。

    :param workspace_id: 工作区 id；空串时直接忽略（无法表达"工作区授权"）
    :param tool: 工具名
    :param kind: 操作类型，仅展示用
    :param target: 首次授权目标，仅审计用
    """
    if not workspace_id or not tool:
        return
    with get_session() as s:
        row = s.scalars(
            select(Approval).where(
                Approval.workspace_id == workspace_id, Approval.tool == tool
            ).limit(1)
        ).first()
        if row is None:
            s.add(Approval(workspace_id=workspace_id, tool=tool, kind=kind, target=target))
        else:
            row.kind = kind or row.kind
            row.target = target or row.target


def list_for(workspace_id: str) -> list[dict]:
    """列出某工作区的全部授权（设置页展示 / 撤销用）。

    :param workspace_id: 工作区 id
    :return: [{tool, kind, target, created_at}]，按工具名排序
    """
    if not workspace_id:
        return []
    with get_session() as s:
        rows = s.scalars(
            select(Approval).where(Approval.workspace_id == workspace_id).order_by(Approval.tool)
        ).all()
        return [
            {
                "tool": row.tool,
                "kind": row.kind,
                "target": row.target,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


def revoke(workspace_id: str, tool: str | None = None) -> int:
    """撤销授权：给了 tool 只撤这一条，没给就撤该工作区全部。

    :param workspace_id: 工作区 id
    :param tool: 要撤销的工具名；None 表示全部
    :return: 实际删除的条数
    """
    if not workspace_id:
        return 0
    with get_session() as s:
        stmt = delete(Approval).where(Approval.workspace_id == workspace_id)
        if tool:
            stmt = stmt.where(Approval.tool == tool)
        result = s.execute(stmt)
        return int(result.rowcount or 0)
