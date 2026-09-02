"""设置接口。

分三部分（三组路由刻意分开定义，便于不同任务并行改动时互不覆盖）：
    - `router` 上的 ``GET/PUT /settings/workspace``：历史遗留的**扁平**工作区根目录接口，
      前端老代码仍在用，保持可用、不做破坏性改动；
    - 同一个 `router` 上的 ``/settings/workspaces*``：**多 profile 工作区**接口（ARCH-3），
      数据由 services/workspace_service.py 提供；
    - `api_router`：统一的设置体系接口（/settings、/settings/meta、/settings/secrets/*），
      实现 doc/27-设置体系规范.md 的「统一入口 + 组.键命名空间」。
"""
# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# Web 框架：APIRouter 建路由，HTTPException 用于把校验失败转成 4xx 响应
from fastapi import APIRouter, HTTPException

# 数据校验：BaseModel 作为请求体基类，Field 给字段写说明
from pydantic import BaseModel, Field

# 项目内：设置服务
from app.services import setting_service
# 项目内：统一响应外壳
from app.schemas.common import ApiResponse
# 项目内：设置声明式注册表（默认值、类型/范围校验、变更事件发布）
from app.services import settings_registry
# 项目内：密钥存储（只进不出，接口只回脱敏值）
from app.services import secrets as secrets_service
# 项目内：配置导入导出（OPS-5）——导出脱敏快照、导入时按白名单写回
from app.services import settings_transfer
# 项目内：工作区（多 profile）服务，负责 CRUD、切换 active 与旧数据迁移（ARCH-3）
from app.services import workspace_service
# 项目内：设置接口的请求/响应模型
from app.schemas.setting import (
    SecretPointOut,
    SecretPutIn,
    SecretStatusOut,
    SettingMetaOut,
    SettingsBatchIn,
    SettingsExportOut,
    SettingsImportIn,
    SettingsImportOut,
    SettingsImportSkippedOut,
    SettingsOut,
)
# 项目内：工作区接口的请求/响应模型（与上面的单键设置模型分开，因工作区是对象数组）
from app.schemas.workspace import (
    ActiveSwitchOut,
    WorkspaceActiveIn,
    WorkspaceCreateIn,
    WorkspaceDeletedOut,
    WorkspaceProfile,
    WorkspacesOut,
    WorkspaceUpdateIn,
)


class WorkspaceUpdate(BaseModel):
    """设置工作区的请求体。"""

    # 工作区根目录列表（绝对路径）；传空数组表示清除限制
    paths: list[str] = Field(default_factory=list, description="工作区根目录的绝对路径列表")


# 本模块的路由，由 app/api/router.py 挂载
router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/workspace", summary="读取当前配置的工作区根目录")
async def get_workspace() -> ApiResponse[list[str]]:
    """返回用户配置的工作区根目录列表（不存在的目录已被过滤）。"""
    roots = setting_service.get_workspace_roots()
    return ApiResponse(code=0, message="ok", data=[str(p) for p in roots])


@router.put("/workspace", summary="保存工作区根目录（覆盖式）")
async def put_workspace(body: WorkspaceUpdate) -> ApiResponse[list[str]]:
    """保存工作区根目录列表，返回过滤掉不存在项之后真正生效的目录。"""
    roots = setting_service.set_workspace_roots(body.paths)
    return ApiResponse(code=0, message="ok", data=[str(p) for p in roots])


# =========================================================================== #
# 工作区多 profile（ARCH-3）
# =========================================================================== #
# 下面这组路由挂在**同一个 router** 上（沿用上面的历史遗留 router，不新建）：
# 它们的路径与上面的 /settings/workspace（单数）不冲突，前端老代码继续用单数接口即可。
#
# 数据全部由 services/workspace_service.py 提供，落到 app_settings 的两个键上：
#   workspaces.list（JSON 数组）+ workspaces.active_id（当前生效 id）。


@router.get("/workspaces", summary="读取全部工作区（自动迁移旧的 workspace_roots）")
async def list_workspaces() -> ApiResponse[WorkspacesOut]:
    """返回全部工作区 profile 与当前生效的工作区 id。

    首次调用时若检测到旧数据（``workspace_roots`` 键），会自动迁移成一个默认工作区
    （id = ``w-default``），迁移是只读的，旧键保留。

    :return: {"workspaces":[{id,name,roots,active}...], "active_id":"w-1"}
    """
    profiles = workspace_service.list_workspaces()
    return ApiResponse(
        code=0,
        message="ok",
        data=WorkspacesOut(
            workspaces=[WorkspaceProfile(**p) for p in profiles],
            # 取列表里 active=True 的那个作为权威 id；一个工作区都没有时为空串
            active_id=next((p["id"] for p in profiles if p.get("active")), ""),
        ),
    )


@router.post("/workspaces", summary="新建工作区")
async def create_workspace(body: WorkspaceCreateIn) -> ApiResponse[WorkspaceProfile]:
    """新建一个工作区，返回分配好 id 的完整对象。

    新建**不会**抢走当前工作区；但如果这是第一个工作区，它会自动成为当前工作区，
    避免用户新建完还得手动切一次。

    :param body: 见 WorkspaceCreateIn
    :return: 新建出的工作区对象
    :raises HTTPException 400: 名称为空或根目录不是字符串列表
    """
    try:
        profile = workspace_service.create_workspace(body.name, body.roots)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(code=0, message="ok", data=WorkspaceProfile(**profile))


@router.put("/workspaces/{workspace_id}", summary="更新工作区（改名/改根目录）")
async def update_workspace(workspace_id: str, body: WorkspaceUpdateIn) -> ApiResponse[WorkspaceProfile]:
    """更新指定工作区；两个字段都可省略，省略即保持原值。

    :param workspace_id: 目标工作区 id
    :param body: 见 WorkspaceUpdateIn（name / roots 均可选）
    :return: 更新后的工作区对象
    :raises HTTPException 404: 该 id 的工作区不存在；400: 根目录不是字符串列表
    """
    try:
        profile = workspace_service.update_workspace(workspace_id, body.name, body.roots)
    except ValueError as e:
        # id 不存在对前端来说是「资源找不到」，用 404 比 400 更贴切
        status = 404 if "不存在" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from e
    return ApiResponse(code=0, message="ok", data=WorkspaceProfile(**profile))


@router.delete("/workspaces/{workspace_id}", summary="删除工作区")
async def delete_workspace(workspace_id: str) -> ApiResponse[WorkspaceDeletedOut]:
    """删除指定工作区；若删掉的是当前工作区，会把当前工作区顺延到剩下的第一个。

    :param workspace_id: 目标工作区 id
    :return: {"deleted": 是否确实删掉了}
    """
    deleted = workspace_service.delete_workspace(workspace_id)
    return ApiResponse(code=0, message="ok", data=WorkspaceDeletedOut(deleted=deleted))


@router.post("/workspaces/active", summary="切换当前工作区")
async def set_active_workspace(body: WorkspaceActiveIn) -> ApiResponse[ActiveSwitchOut]:
    """把指定工作区设为当前生效工作区。

    切换后立即生效：服务层写入 ``workspaces.active_id`` 后会发布变更事件，
    工具层的写/执行白名单（``tool_utils.WORKSPACE_ROOTS``）随之刷新，
    文件树与越界判断范围立刻跟随（ARCH-3 验收项）。

    请求体同时接受 ``id`` 与 ``workspace_id`` 两个字段名，这里做兼容。

    :param body: 见 WorkspaceActiveIn
    :return: {"active_id": 切换后的 id}
    :raises HTTPException 404: 目标 id 不存在；400: 两个字段都没传
    """
    target_id = (body.id or body.workspace_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="请提供要切换的工作区 id（字段 id 或 workspace_id）")
    try:
        profile = workspace_service.set_active(target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ApiResponse(code=0, message="ok", data=ActiveSwitchOut(active_id=profile["id"]))


# =========================================================================== #
# 统一设置体系（doc/27-设置体系规范.md）
# =========================================================================== #
# 单独一个 router，与上面的 workspace 路由分开：
# 这样「工作区多profile」任务只需往 router 上追加子路由，不会与本段代码互相覆盖。
api_router = APIRouter(prefix="/settings", tags=["settings"])


@api_router.get("", summary="读取全部非密钥设置项的当前值")
async def read_settings() -> ApiResponse[SettingsOut]:
    """返回所有普通设置项的当前值（已落库值优先，未落库则用声明默认值）。

    安全红线：**任何密钥都不会出现在本接口的响应里**（既没有明文，也没有脱敏值）。
    密钥状态请单独查 GET /settings/secrets/{key}。

    :return: {"code":0,"message":"ok","data":{"values":{"llm.model":"deepseek-chat", ...}}}
    """
    return ApiResponse(code=0, message="ok", data=SettingsOut(values=settings_registry.get_all_settings()))


@api_router.get("/meta", summary="读取设置项的 schema（不含当前值）")
async def read_settings_meta() -> ApiResponse[list[SettingMetaOut]]:
    """返回全量设置项的类型/默认值/范围/分组，供设置页自动渲染分区。

    本接口**只含元数据、不含任何值**，因此前端可以在启动时拉一次并缓存，
    之后即使某个键没有落库也能渲染出正确的控件与提示文案。

    :return: SettingMetaOut 数组，按键名排序
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=[SettingMetaOut(**d.to_dict()) for d in settings_registry.list_defs()],
    )


@api_router.put("", summary="批量保存普通设置（按声明校验后落库）")
async def update_settings(body: SettingsBatchIn) -> ApiResponse[SettingsOut]:
    """批量保存普通设置：逐键按 SETTING_DEFS 做类型与范围校验，全部通过后一次性落库。

    写入采用「全量校验通过才落库」：只要有一个键非法，整个请求都不写，
    避免配置处于「改了一半」的不一致状态。

    :param body: 见 SettingsBatchIn
    :return: 保存后全部非密钥设置项的当前值
    :raises HTTPException 400: 键未声明、类型/范围不合法，或试图通过本接口写密钥
    """
    try:
        values = settings_registry.put_settings(body.values)
    except KeyError as e:
        # 未声明的键：告诉前端是哪个键拼错了，便于它定位
        raise HTTPException(status_code=400, detail=f"未声明的设置键：{e}") from e
    except ValueError as e:
        # 类型/范围不合法，或试图用普通接口写密钥
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(code=0, message="ok", data=SettingsOut(values=values))


@api_router.get("/export", summary="导出脱敏配置（OPS-5，不含任何密钥）")
async def export_settings() -> ApiResponse[SettingsExportOut]:
    """导出当前全部非密钥设置项的快照，供用户备份或迁移到另一台机器。

    安全红线（与 §「导出」docstring 一致）：
        - 不导出 secrets.* 命名空间的任何键；
        - 密钥只导出「设置过没有」的布尔清单，导出文件里没有密钥值；
        - MCP 的 env / headers 这类容器里的值也会被抹成占位符，
          并把该键记进 redacted_keys，导入时整键跳过。

    :return: 见 SettingsExportOut
    """
    payload = settings_transfer.build_export()
    return ApiResponse(
        code=0,
        message="ok",
        data=SettingsExportOut(
            format=payload["format"],
            exported_at=payload["exported_at"],
            app_version=payload["app_version"],
            values=payload["values"],
            redacted_keys=payload["redacted_keys"],
            secrets=[SecretPointOut(**item) for item in payload["secrets"]],
        ),
    )


@api_router.post("/import", summary="导入一份脱敏配置（只写合法且未脱敏的键）")
async def import_settings(body: SettingsImportIn) -> ApiResponse[SettingsImportOut]:
    """把导出的配置写回本机：逐键校验，只写合法的那些，其余记进 skipped。

    为什么不是"全量校验通过才落库"（与 PUT /api/settings 不同）：
        配置文件是跨机器/跨版本搬过来的，里面**必然**有本机没声明的键
        （旧版本没有的新键、别人机器上的自定义项）。按整体原子写入的话，
        一个陌生键就会让整份配置导入失败，用户只能手工删 JSON。
        所以这里按单键取舍：能用的键尽量写进去，不能用的如实告诉用户。

    :param body: 见 SettingsImportIn
    :return: 见 SettingsImportOut（applied / skipped / 导入后的全量值）
    :raises HTTPException 400: 不是 JSON 对象、format 不匹配、values 缺失
    """
    try:
        result = settings_transfer.apply_import(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiResponse(
        code=0,
        message="ok",
        data=SettingsImportOut(
            applied=result["applied"],
            skipped=[SettingsImportSkippedOut(**item) for item in result["skipped"]],
            values=result["values"],
        ),
    )


@api_router.get("/secrets/{key}", summary="查询某个密钥是否已设置（只回脱敏值）")
async def read_secret_status(key: str) -> ApiResponse[SecretStatusOut]:
    """返回某个密钥的设置状态。

    安全红线：**只回脱敏值**（形如 ``sk-****ijkl``），永远不回完整密钥。
    请求里的 key 不带 ``secrets.`` 前缀，例如 ``deepseek.api_key``。

    :param key: 密钥名，如 "deepseek.api_key"
    :return: {"set": 已设置与否, "masked": 脱敏值或 null}
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=SecretStatusOut(set=secrets_service.has_secret(key), masked=secrets_service.masked_secret(key)),
    )


@api_router.put("/secrets/{key}", summary="保存密钥（只进不出）")
async def put_secret(key: str, body: SecretPutIn) -> ApiResponse[SecretStatusOut]:
    """保存一个密钥并返回其脱敏状态。

    密钥优先存进系统钥匙串；钥匙串不可用时降级为 Fernet 密文存库，
    两种情况下 app.db 里都不会出现明文密钥。

    :param key: 密钥名（不带 ``secrets.`` 前缀），如 "deepseek.api_key"
    :param body: 见 SecretPutIn
    :return: 保存后的脱敏状态
    :raises HTTPException 400: 密钥名为空或密钥值为空
    """
    try:
        secrets_service.set_secret(key, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 存完之后立刻回一个脱敏值，前端无需再发一次 GET 就能刷新输入框
    return ApiResponse(
        code=0,
        message="ok",
        data=SecretStatusOut(set=True, masked=secrets_service.mask_secret(body.value)),
    )


@api_router.delete("/secrets/{key}", summary="删除某个密钥")
async def remove_secret(key: str) -> ApiResponse[dict]:
    """删除一个密钥，使其回到「未设置」状态。

    :param key: 密钥名（不带 ``secrets.`` 前缀）
    :return: {"deleted": 是否确实删掉了一个已存在的密钥}
    """
    return ApiResponse(code=0, message="ok", data={"deleted": secrets_service.delete_secret(key)})
