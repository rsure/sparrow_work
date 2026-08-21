# app/services/workspace_settings_defs.py
"""工作区这一层的设置声明 + 白名单联动订阅（ARCH-3）。

为什么单独一个文件：
    services/settings_registry.py 由「设置体系地基」任务持有，本任务不能改它；
    按 doc/28 §4 的约定，各模块只**声明**自己的设置项，于是本文件就是工作区模块的声明处。
    main.py 只需在 register_defs(BUILTIN_DEFS) 之后调一次 register_workspace_defs()。

本文件同时承担「active 切换 → 工具层白名单自动刷新」的联动（ARCH-3 的核心）：
    tools/tool_utils.py 里的 WORKSPACE_ROOTS 是写文件 / 执行命令的白名单，
    它必须跟着「当前 active 工作区」走。做法是订阅 "workspaces." 前缀的变更事件，
    收到事件就调 tool_utils.refresh_workspace_roots() 重新读一次 active 工作区的根目录并原地更新该列表。
"""

# 让类型注解延迟求值（PEP 563），便于使用 list[...] 等新语法
from __future__ import annotations

# 项目内：设置声明与注册表（SettingDef 描述一项设置，register_defs/subscribe 提供注册与订阅）
from app.services.settings_registry import SettingDef, SettingKind, register_defs, subscribe, unsubscribe

# 工作区设置键：全部工作区 profile 的 JSON 数组（迁移前的旧键是 workspace_roots，不在此列）
KEY_WORKSPACES = "workspaces.list"
# 工作区设置键：当前生效工作区的 id（权威值；profile 里的 active 字段只是冗余标记）
KEY_ACTIVE_ID = "workspaces.active_id"

# 订阅用的键前缀：任何 workspaces.* 的写入都会触发白名单刷新
SUBSCRIBE_PREFIX = "workspaces."

# 本模块声明的全部设置项。main.py 通过 register_workspace_defs() 注册它们。
SETTING_DEFS: list[SettingDef] = [
    SettingDef(
        key=KEY_WORKSPACES,
        label="工作区列表",
        kind=SettingKind.JSON,
        default=[],
        category="workspace",
        since="M1",
        description="全部工作区 profile 的列表；每个元素形如 "
                    '{"id":"w-1","name":"主项目","roots":["D:\\\\work"],"active":true}；'
                    "首次升级时会把旧的 workspace_roots 自动迁移成一个默认工作区",
    ),
    SettingDef(
        key=KEY_ACTIVE_ID,
        label="当前工作区",
        kind=SettingKind.STRING,
        default="",
        category="workspace",
        since="M1",
        description="当前生效的工作区 id；决定文件工具的越界范围、文件树展示根与知识库默认范围，空串表示还没有工作区",
    ),
]


def _refresh_roots_on_change(event: object) -> None:
    """工作区设置发生变化时的回调：把工具层白名单刷新成「当前 active 工作区」的根目录并集。

    :param event: settings_registry.SettingsChangeEvent 变更事件；这里用不到它的字段，
                  只把它当作「该刷新了」的信号，因此标注为 object 避免与注册表产生导入耦合。
    """
    # 项目内：延迟导入 tool_utils。它会连带导入 RAG 解析等较重的东西，
    # 而本模块可能被 main.py 在很早期导入，放到函数里按需引入更安全（也避免循环导入）
    from app.tools.tool_utils import refresh_workspace_roots

    # 刷新失败不应让设置写入失败：白名单读不到就退化成「不限制」，与改造前的行为一致
    try:
        refresh_workspace_roots()
    except Exception:
        return


def register_workspace_defs() -> None:
    """注册工作区的设置声明，并做好「active 切换 → 刷新工具白名单」的订阅与首次同步。

    可以在多处重复调用（例如 main.py 启动时、测试用例前），订阅会先取消再重新登记，
    因此不会因为重复调用而让刷新回调被触发多次。函数本身不会抛异常。
    """
    # 第一步：把两个设置项声明注册进全局注册表（幂等）
    register_defs(SETTING_DEFS)
    # 第二步：订阅 workspaces.* 变更。先 unsubscribe 是为了幂等（unsubscribe 对不存在的订阅是空操作）
    unsubscribe(SUBSCRIBE_PREFIX, _refresh_roots_on_change)
    subscribe(SUBSCRIBE_PREFIX, _refresh_roots_on_change)
    # 第三步：按「当前 active 工作区」同步一次白名单。
    # 启动时必须做，否则在第一次切换之前 WORKSPACE_ROOTS 会一直是空的（= 不限制）
    try:
        from app.tools.tool_utils import refresh_workspace_roots

        refresh_workspace_roots()
    except Exception:
        # 数据库未就绪 / 表不存在时读不到工作区：保持空白名单（不限制），不阻断应用启动
        return


# 模块被导入时就完成一次注册，这样「谁 import 谁负责订阅」，
# 即使别的模块（如直接跑脚本或写单测）先引到本文件，也不会漏掉订阅
register_workspace_defs()