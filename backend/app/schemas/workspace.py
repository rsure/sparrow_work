# app/schemas/workspace.py
"""工作区（多 profile）的请求/响应模型，对应 doc/28-M0M1实施拆分方案.md §3.6 的接口契约。

与其它 schema 的分工：
    - app/schemas/setting.py 负责「统一设置体系」（单键读写、密钥脱敏）；
    - 本文件负责「工作区这一组有内部结构的数据」，因为工作区是**对象数组**而不是单个标量，
      用独立模型可以让 /docs 里的字段说明直接写清 roots 是什么、active 与 active_id 谁为准。

存储说明：工作区**不建表**，整体以 JSON 数组存在 app_settings 的 workspaces.list 键里
（见 app/services/workspace_service.py）。这里只描述它的对外形状。
"""

# 让类型注解延迟求值（PEP 563），便于使用 str | None、list[str] 等新语法
from __future__ import annotations

# 数据校验：BaseModel 作为模型基类，Field 给每个字段写用途说明（会出现在 /docs）
from pydantic import BaseModel, Field


class WorkspaceProfile(BaseModel):
    """一个工作区 profile：一份「名字 + 一组根目录」的组合（ARCH-3）。

    对应落库 JSON 里的一个元素：{"id":"w-1","name":"主项目","roots":["D:\\work"],"active":true}。
    """

    # 工作区唯一 id，后端分配（形如 w-1；旧数据迁移出来的默认工作区是 w-default）
    id: str = Field(..., description="工作区唯一 id，由后端分配（新增时不传，删除/切换时用它定位）")
    # 工作区展示名，用户可重命名；同一台机器上不要求唯一
    name: str = Field(..., description="工作区名称，用于界面展示，可重命名")
    # 该工作区的根目录绝对路径列表（白名单范围：文件工具只能在这几个目录里写/执行）
    roots: list[str] = Field(
        default_factory=list,
        description="工作区根目录的绝对路径列表；决定文件工具允许写入/执行的目录范围",
    )
    # 是否为当前生效的工作区（**冗余标记**，以 workspaces.active_id 键为准，这里只是方便前端渲染）
    active: bool = Field(
        default=False,
        description="是否为当前生效的工作区；该字段是冗余标记，权威值是 workspaces.active_id",
    )


class WorkspaceCreateIn(BaseModel):
    """新建工作区的请求体（POST /api/settings/workspaces）。"""

    # 工作区名称；去掉首尾空格后不能为空
    name: str = Field(..., min_length=1, description="工作区名称，不能为空；只由首尾空格组成的名字会被拒绝")
    # 根目录绝对路径列表；允许先留空（之后用 PUT 补），空列表表示该工作区暂不限制范围
    roots: list[str] = Field(
        default_factory=list,
        description="工作区根目录的绝对路径列表；允许留空，之后可用 PUT /settings/workspaces/{id} 补充",
    )


class WorkspaceUpdateIn(BaseModel):
    """更新工作区的请求体（PUT /api/settings/workspaces/{id}）。

    两个字段都可省略：省略 name 表示只改根目录，省略 roots 表示只改名，
    都不传则原样返回（不写入）。
    """

    # 新名称；为 None 表示不改名
    name: str | None = Field(default=None, description="新的工作区名称；不传表示保持原名")
    # 新的根目录列表；为 None 表示不改根目录（注意：传空数组表示「清空根目录」，与不传语义不同）
    roots: list[str] | None = Field(
        default=None,
        description="新的根目录绝对路径列表；不传表示保持原样，传空数组表示清空全部根目录",
    )


class WorkspaceActiveIn(BaseModel):
    """切换当前工作区的请求体（POST /api/settings/workspaces/active）。

    同时接受 id 与 workspace_id 两个字段名：前端老代码可能用后者，这里做兼容，
    两个都传时以 id 为准。
    """

    # 目标工作区 id（推荐字段名）
    id: str | None = Field(default=None, description="要设为当前工作区的 id；与 workspace_id 二选一")
    # 目标工作区 id（兼容字段名，等价于 id）
    workspace_id: str | None = Field(default=None, description="id 的兼容别名；两个字段都传时以 id 为准")


class WorkspacesOut(BaseModel):
    """工作区列表响应体（GET /api/settings/workspaces）。"""

    # 全部工作区，顺序与用户创建顺序一致
    workspaces: list[WorkspaceProfile] = Field(
        default_factory=list,
        description="全部工作区列表，顺序与创建顺序一致",
    )
    # 当前生效工作区的 id；一个工作区都没有时为空串
    active_id: str = Field(
        default="",
        description="当前生效的工作区 id；还没有任何工作区时为空字符串",
    )


class WorkspaceDeletedOut(BaseModel):
    """删除工作区的响应体（DELETE /api/settings/workspaces/{id}）。"""

    # 是否确实删掉了一个已存在的工作区（false 表示 id 不存在）
    deleted: bool = Field(..., description="是否确实删除了该工作区；false 表示这个 id 本来就不存在")


class ActiveSwitchOut(BaseModel):
    """切换当前工作区的响应体（POST /api/settings/workspaces/active）。"""

    # 切换后的当前工作区 id
    active_id: str = Field(..., description="切换后当前生效的工作区 id")