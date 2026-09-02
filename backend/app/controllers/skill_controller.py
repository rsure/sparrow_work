# app/controllers/skill_controller.py
"""技能管理接口（EXT-1）。

三个端点：
    GET  /api/skills            列出技能（含解析错误、扫描目录、总开关状态）
    GET  /api/skills/{name}     读取某个技能的完整正文（设置页"查看说明"用）
    POST /api/skills/reload     重新扫描目录（装好新技能后点刷新）

为什么不提供"在线安装"接口：
    技能的安装动作本质是"把一组文件放到磁盘"，用系统文件管理器做更直观，
    也避免后端去写用户任意目录。首版只做"发现 + 启停 + 重载"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter 建路由，HTTPException 把"技能不存在"转成 404
from fastapi import APIRouter, HTTPException

# 项目内：技能注册表
from app.skills import registry as skill_registry


# 本模块的路由，由 app/api/router.py 挂载（统一前缀 /api）
router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", summary="列出已安装的技能")
async def list_skills() -> dict:
    """返回技能清单与扫描状态。

    包含三类信息：
        skills  —— 已解析成功的技能（不含正文，只有元数据）
        errors  —— 解析失败的 SKILL.md（路径 + 原因），让用户能自己修
        dirs    —— 实际扫描的目录（用户经常"放错地方"，把目录回显出来最省事）

    :return: {"enabled", "disabled", "dirs", "skills", "errors"}
    """
    return skill_registry.snapshot()


@router.post("/reload", summary="重新扫描技能目录")
async def reload_skills() -> dict:
    """重新扫描磁盘，刷新注册表。

    额外做一件事：清空 LLM 缓存（`state.invalidate()`），
    让系统提示词里的技能清单在**下一轮对话**就更新，而不是等用户重启。

    :return: 重载后的快照
    """
    state = skill_registry.reload(force=True)
    # 项目内：延迟导入，避免控制器导入期就把模型层拉起来
    from app.llm import state as llm_state

    llm_state.invalidate()
    return state


@router.get("/{name}", summary="读取某个技能的完整正文")
async def get_skill(name: str) -> dict:
    """读取技能正文（设置页「查看说明」用）。

    :param name: 技能名
    :return: {"name", "description", "tools", "body", "path", "enabled"}
    :raises HTTPException 404: 技能不存在
    """
    spec = skill_registry.get_skill(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"没有名为 {name} 的技能")
    payload = spec.to_dict(enabled=not skill_registry.is_disabled(spec.name))
    # 详情接口才返回正文（列表接口刻意不带，避免几十个技能一次塞满响应）
    payload["body"] = spec.body
    return payload
