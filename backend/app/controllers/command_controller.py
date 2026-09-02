# app/controllers/command_controller.py
"""斜杠命令接口（UX-8）：给前端输入框的 `/` 菜单提供一份"现在能用什么"的清单。

只有一个只读接口，没有请求体——命令清单的"真源"在
app/services/command_service.py（内置命令常量 + 技能注册表），本文件只做 HTTP 包装。

为什么不缓存：技能列表可能因为用户在设置里改目录、外部文件变动而变；
这个接口是"用户敲 `/` 时才请求一次"的低频调用，每次现算最省心，也不会给出过期清单。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter 声明 /commands 路由
from fastapi import APIRouter

# 项目内：命令注册表（内置命令 + 已安装技能的统一清单）
from app.services import command_service


# 路由前缀挂成 /commands：最终地址是 /api/commands（/api 前缀在 app/api/router.py 里统一加）
router = APIRouter(prefix="/commands", tags=["commands"])


@router.get("", summary="可用斜杠命令清单（内置命令 + 已安装技能）")
async def list_commands() -> dict:
    """列出输入框里敲 `/` 可以选的命令。

    返回的每一条都带 `source` 与 `action`，前端据此决定怎么执行：
        - source="builtin"：由前端自己执行 action（doc/model/clear/export/help）；
        - source="skill"：前端把原始文本 `/技能名 参数` 发给后端，后端展开成提示词。

    :return: {"commands": [{name, description, args_hint, source, action}, ...]}
    """
    return {"commands": command_service.list_commands()}
