# app/services/settings_registry.py
"""
设置声明式注册表：全局唯一的设置读写入口（普通设置存app_settings 表，密钥除外）。

设计要点（对应 doc/27-设置体系规范.md）：
    - 各模块只「声明」自己的设置项（SettingDef 列表），不自己建表、不自己开接口；
    - 读写统一走本模块：get_setting() / put_settings()，调用方不需要写 if-else 兜底默认值；
    - 写入时按声明做类型与范围校验，通过后落库并 publish 变更事件；
    - 订阅者按「键前缀」订阅（如订阅 "llm." 触发 agent 失效重建），事件驱动、不轮询。

分层边界（重要）：
    - 普通设置 → app_settings 表（本模块负责）；
    - 密钥 → 系统钥匙串 / Fernet 密文（见 services/secrets.py），**不走**本模块的批量接口；
    - 安全红线（如 DENY 硬护栏）→ 代码常量，不进注册表、不开放开关。

模块导入时**不会**自动注册任何设置项（避免 import 期就依赖数据库），
由 app/main.py 在create_app() 里显式调用 register_defs(BUILTIN_DEFS) 完成注册。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None、dict[str, Any] 等新语法
from __future__ import annotations

# 标准库：枚举定义支持的六种设置类型（bool/int/float/string/json/select）
from enum import Enum
# 标准库：dataclass 描述 SettingDef（不可变声明）与 SettingsChangeEvent（变更事件负载）
from dataclasses import dataclass, field
# 标准库：Any 标注各类型设置的值；Callable 标注事件订阅回调；JSON 序列化 json 类型设置
from typing import Any, Callable
import json

# 项目内：普通设置的落库读写（app_settings 表）；延迟导入避免循环依赖
from app.services import setting_service


# --------------------------------------------------------------------------- #
# 1. 设置类型
# --------------------------------------------------------------------------- #
class SettingKind(str, Enum):
    """设置项的值类型：决定写入时如何校验与转换。六种类型覆盖 doc/27 §4 的全部需求。"""

    # 开关型：只接受 true/false（JSON 里就是布尔字面量）
    BOOL = "bool"
    # 整数型：接受 int，或能无损转成 int 的字符串；可配 min/max 范围
    INT = "int"
    # 浮点型：接受 float/int；可配 min/max 范围
    FLOAT = "float"
    # 字符串型：原样保存，不做类型转换
    STRING = "string"
    # JSON 型：任意可序列化结构（列表/对象），保存前会做一次序列化校验
    JSON = "json"
    # 选择型：字符串，且必须落在该SettingDef.options 列出的候选值里
    SELECT = "select"

    @classmethod
    def parse(cls, raw: "SettingKind | str") -> "SettingKind":
        """把声明里写的类型（枚举或字符串）统一成 SettingKind。

        :param raw: SettingKind 本身，或其字符串形式（如 "int"）
        :return: 对应的 SettingKind 枚举成员
        :raises ValueError: 类型名不在六种受支持类型里
        """
        if isinstance(raw, cls):
            return raw
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            supported = "、".join(k.value for k in cls)
            raise ValueError(f"不支持的设置类型 {raw!r}，受支持的类型有：{supported}") from None

    def coerce(self, value: Any, key: str = "") -> Any:
        """按本类型校验并规范化一个写入值。

        这是「声明式校验」的核心：类型不符、区间越界、select 候选不匹配都在这里被拦下，
        调用方（controller）拿到的一定是已经合法的值。

        :param value: 待校验的原始值（来自 HTTP 请求体，类型不可信）
        :param key: 设置键，仅用于拼接错误信息，让报错能指明是哪个键
        :return: 规范化后的值（INT 会转成 int、FLOAT 转成 float、JSON 会保持原结构）
        :raises ValueError: 类型不匹配或超出声明的范围
        """
        # 错误信息前缀：有键名时带上，便于前端直接定位到具体设置项
        where = f"设置 {key} " if key else ""

        if self is SettingKind.BOOL:
            # bool 是 int 的子类，必须先判bool，否则 True 会被当成整数 1 放行
            if not isinstance(value, bool):
                raise ValueError(f"{where}要求布尔值（true/false），收到 {type(value).__name__}")
            return value

        if self is SettingKind.INT:
            # 显式拒绝 bool：前端传 true 几乎一定是 bug，放行会静默存成 1
            if isinstance(value, bool):
                raise ValueError(f"{where}要求整数，收到布尔值")
            if isinstance(value, int):
                number = value
            elif isinstance(value, float) and value.is_integer():
                number = int(value)
            elif isinstance(value, str):
                try:
                    number = int(value.strip())
                except ValueError:
                    raise ValueError(f"{where}要求整数，收到 {value!r}") from None
            else:
                raise ValueError(f"{where}要求整数，收到 {type(value).__name__}")
            return number

        if self is SettingKind.FLOAT:
            # bool 同样要拒绝：True 转成 1.0 几乎一定是误用
            if isinstance(value, bool):
                raise ValueError(f"{where}要求数字，收到布尔值")
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.strip())
                except ValueError:
                    raise ValueError(f"{where}要求数字，收到 {value!r}") from None
            raise ValueError(f"{where}要求数字，收到 {type(value).__name__}")

        if self is SettingKind.STRING:
            # 只接受字符串；数字也不自动转，避免前端不小心把版本号之类的存成数字
            if not isinstance(value, str):
                raise ValueError(f"{where}要求字符串，收到 {type(value).__name__}")
            return value

        if self is SettingKind.JSON:
            # 只校验「能不能序列化」，不做结构约束：各模块对自己的 json 结构负责
            try:
                json.dumps(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{where}要求可序列化的 JSON 值：{e}") from None
            return value

        # SELECT：字符串 + 必须由 SettingDef.options 兜底校验（本方法拿不到 options，
        # 所以这里只做类型检查，候选校验在 SettingDef.check_range 里统一做）
        if not isinstance(value, str):
            raise ValueError(f"{where}要求字符串（从固定候选中选一个），收到 {type(value).__name__}")
        return value

    def to_dict(self) -> str:
        """返回该类型的字符串形式（供 GET /api/settings/meta 下发给前端渲染控件）。"""
        return self.value


# --------------------------------------------------------------------------- #
# 2. 设置声明
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SettingDef:
    """一个设置项的静态声明：键、类型、默认值、取值范围与展示信息。

    声明只含元数据、不含逻辑——这是 doc/27 §9「注册表不成为隐形耦合点」的保证：
    各模块用这份声明自动获得「读取有默认值兜底 + 写入有校验 + 设置页能自动渲染」三件事，
    而不需要自己写任何存储或接口代码。
    """

    # 设置键，格式固定为「组.键」（如 "llm.model"），全局唯一
    key: str
    # 值类型，决定校验与转换方式
    kind: SettingKind
    # 默认值：用户没配置过时get_setting 返回它（调用方因此不必写 if-else 兜底）
    default: Any
    # 中文展示名（设置页的标题）。留空时前端回退显示 key——
    # 刻意不强制：新增设置项时"先能跑"比"先取个好名字"重要
    label: str = ""
    # select 候选值的中文标签，必须与 options 一一对应（如 options=("dark","light") → ("深色","浅色")）。
    # 为什么要单独一份：值本身是存库的契约（英文/短横线），不能为了显示去改它
    option_labels: tuple[str, ...] | None = None
    # 设置页分组（category）：前端按它自动分区渲染，新增模块无需改前端
    category: str = "advanced"
    # 数值下界，仅对 INT / FLOAT 生效；None 表示不限
    min: float | None = None
    # 数值上界，仅对 INT / FLOAT 生效；None 表示不限
    max: float | None = None
    # select 类型的候选值元组；其它类型为 None
    options: tuple[str, ...] | None = None
    # 首次引入的里程碑（追溯用，例如 "M0"）
    since: str = "M1"
    # 面向用户的一句话说明，会随 GET /api/settings/meta 下发给设置页当提示文案
    description: str = ""
    # 是否为密钥项。密钥走 services/secrets.py，不落app_settings；
    # 该标记只用于让 meta 接口明确排除它们（当前内置声明里没有密钥项）
    secret: bool = False

    def __post_init__(self) -> None:
        """声明期的自检：把明显写错的声明在注册时就拦下，而不是等到用户写入时才报错。"""
        # 键必须是「组.键」两段式：这是 doc/27 §1「模块命名空间」的基础约定
        if "." not in self.key or self.key.startswith(".") or self.key.endswith("."):
            raise ValueError(f"设置键 {self.key!r} 必须形如「组.键」，例如 llm.model")
        # select 类型必须给候选值，否则前端渲染成自由文本框、用户能存进非法值
        if self.kind is SettingKind.SELECT and not self.options:
            raise ValueError(f"设置 {self.key} 声明为 select，但没给options 候选值")
        # 候选值的中文标签必须与候选值等长：长度不齐会让下拉项错位（显示 A 的值、存 B 的值）
        if self.option_labels is not None:
            if self.kind is not SettingKind.SELECT:
                raise ValueError(f"设置 {self.key} 不是 select，不该声明 option_labels")
            if self.options and len(self.option_labels) != len(self.options):
                raise ValueError(
                    f"设置 {self.key} 的 option_labels 有 {len(self.option_labels)} 项，"
                    f"与 options 的 {len(self.options)} 项不一致"
                )
        # 数值范围必须自洽：min 不能大于 max
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"设置 {self.key} 的 min({self.min}) 大于 max({self.max})")
        # 默认值必须能通过自身的类型与范围校验，避免「默认值本身就是非法的」
        self.check_range(self.kind.coerce(self.default, self.key))

    def check_range(self, value: Any) -> Any:
        """在类型转换之后，再校验数值区间与 select 候选值。

        :param value: 已通过 kind.coerce 的值
        :return: 原样返回该值（校验不通过时抛异常）
        :raises ValueError: 超出 [min, max] 区间，或不在 options 候选内
        """
        # select 的候选校验放这里：coerce 拿不到 options，只能做类型检查
        if self.kind is SettingKind.SELECT and self.options and value not in self.options:
            candidates = "、".join(self.options)
            raise ValueError(f"设置 {self.key} 只能取以下候选值之一：{candidates}；收到 {value!r}")
        # 区间校验只对数值类型有意义
        if self.kind in (SettingKind.INT, SettingKind.FLOAT):
            if self.min is not None and value < self.min:
                raise ValueError(f"设置 {self.key} 不能小于 {self.min}（收到 {value}）")
            if self.max is not None and value > self.max:
                raise ValueError(f"设置 {self.key} 不能大于 {self.max}（收到 {value}）")
        return value

    def coerce(self, value: Any) -> Any:
        """校验并规范化一个写入值（类型转换 + 区间/候选校验）。

        :param value: 待写入的原始值
        :return: 规范化后的值，可直接落库
        :raises ValueError: 类型或取值不合法
        """
        return self.check_range(self.kind.coerce(value, self.key))

    def to_dict(self) -> dict[str, Any]:
        """转成 GET /api/settings/meta 下发的 schema 形状（**只含元数据，不含当前值**）。"""
        return {
            "key": self.key,
            "type": self.kind.to_dict(),
            "label": self.label,
            "default": self.default,
            "option_labels": list(self.option_labels) if self.option_labels else None,
            "min": self.min,
            "max": self.max,
            "options": list(self.options) if self.options else None,
            "category": self.category,
            "since": self.since,
            "description": self.description,
            "secret": self.secret,
        }


# --------------------------------------------------------------------------- #
# 3. 内置声明
# --------------------------------------------------------------------------- #
# 项目内置的全部设置项。后续模块（T02 模型层、T03 工作区、T04 前端……）通过
# register_defs() 追加自己的声明，**不要修改这个常量**，这样每个任务的改动边界互不重叠。
BUILTIN_DEFS: list[SettingDef] = [
    # ---------------- 模型（category=model）----------------
    SettingDef(
        key="llm.provider", label="模型供应商", kind=SettingKind.SELECT, default="deepseek",
        category="model", options=("deepseek", "openai", "anthropic", "google", "ollama"), option_labels=("DeepSeek", "OpenAI", "Anthropic", "Google", "Ollama 本地"),
        since="M1", description="当前使用的模型供应商；切换后新对话立即生效，无需重启后端",
    ),
    SettingDef(
        key="llm.model", label="模型名称", kind=SettingKind.STRING, default="deepseek-flash",
        category="model", since="M1",
        description=(
            "API 调用时用的具体模型名，可直接手写任意名字（新模型不必等我们改代码）："
            "内置清单见设置页「模型」下拉，清单里没有的名字会自动登记到「自定义模型」"
        ),
    ),
    SettingDef(
        key="llm.base_url", label="接口地址", kind=SettingKind.STRING, default="",
        category="model", since="M1",
        description="OpenAI 兼容端点的接口地址；留空表示用供应商官方地址",
    ),
    SettingDef(
        key="llm.temperature", label="随机性（温度）", kind=SettingKind.FLOAT, default=0.0, min=0.0, max=2.0,
        category="model", since="M1", description="生成随机性：0 最稳定，越大越发散",
    ),
    SettingDef(
        key="llm.max_tokens", label="单轮输出上限", kind=SettingKind.INT, default=0, min=0, max=200000,
        category="model", since="M1", description="单轮生成上限；0 表示不传，用供应商默认值",
    ),
    SettingDef(
        key="llm.custom_models", label="自定义模型", kind=SettingKind.JSON, default=[],
        category="model", since="M1",
        description=(
            "自定义模型列表（JSON 数组），用来补充注册表里没有的新模型。每项形如 "
            '{"provider":"deepseek","model":"deepseek-v9","label":"V9","context_window":1000000,'
            '"supports_tools":true,"price_in":2,"price_out":8}；'
            "context_window 必填（压缩阈值靠它），缺了该项会被忽略"
        ),
    ),
    SettingDef(
        key="llm.custom_providers", label="自定义端点", kind=SettingKind.JSON, default=[],
        category="model", since="M1",
        description=(
            "自定义 OpenAI 兼容端点列表（JSON 数组），多个中转站可并存、各自密钥独立。"
            '每项形如 {"id":"myapi","label":"我的中转","base_url":"https://x.example/v1"}'
        ),
    ),
    # ---------------- 工具（category=tools）----------------
    SettingDef(
        key="tools.allow_web", label="允许联网", kind=SettingKind.BOOL, default=False,
        category="tools", since="M1",
        description="是否允许 Agent 联网（web_search / web_fetch）；默认关闭",
    ),
    # ---------------- 上下文（category=context）----------------
    SettingDef(
        key="context.max_tool_output_chars", label="工具输出上限（字符）", kind=SettingKind.INT, default=8000,
        min=1000, max=200000, category="context", since="M1",
        description="单次工具输出的截断阈值（字符数）；超出部分截断并落盘，可续读",
    ),
    SettingDef(
        key="context.tool_output_truncate", label="截断超长输出", kind=SettingKind.BOOL, default=True,
        category="context", since="M1", description="是否对超长的工具输出做截断处理",
    ),
    SettingDef(
        key="context.auto_compress", label="自动压缩上下文", kind=SettingKind.BOOL, default=True,
        category="context", since="M1", description="对话过长时是否自动摘要压缩早期消息",
    ),
    SettingDef(
        key="context.compress_threshold", label="压缩触发比例", kind=SettingKind.FLOAT, default=0.7,
        min=0.1, max=0.95, category="context", since="M1",
        description="上下文占用达到模型窗口该比例时触发压缩",
    ),
    SettingDef(
        key="context.keep_recent_n", label="压缩时保留消息数", kind=SettingKind.INT, default=10, min=1, max=100,
        category="context", since="M1", description="压缩时保留最近多少条消息不参与摘要",
    ),
    # ---------------- Agent 行为（category=agent）----------------
    SettingDef(
        key="agent.max_iterations", label="单轮步数上限", kind=SettingKind.INT, default=25, min=1, max=50,
        category="agent", since="M1",
        description="单轮对话的工具迭代上限；模型一次 + 工具一次各算一步",
    ),
    SettingDef(
        key="agent.steering_enabled", label="允许执行中插话", kind=SettingKind.BOOL, default=True,
        category="agent", since="M1", description="执行过程中允许用户插话干预下一步",
    ),
    SettingDef(
        key="agent.subagent_enabled", label="启用子 agent", kind=SettingKind.BOOL, default=False,
        category="agent", since="M1",
        description=(
            "开启后主对话多一个 dispatch_subagent 工具：把「只需要读」的子任务派给隔离的"
            "只读子 agent，主对话只回收结论。子 agent 不能写盘、不能执行命令、不能联网"
        ),
    ),
    SettingDef(
        key="agent.subagent_max_parallel", label="子 agent 并发上限", kind=SettingKind.INT, default=2, min=1, max=8,
        category="agent", since="M1",
        description="同时最多跑几个子 agent；超出的派发会被直接拒绝，让主对话自己串行处理",
    ),
    # ---------------- 高级（category=advanced）----------------
    SettingDef(
        key="trace.enabled", label="留存执行轨迹", kind=SettingKind.BOOL, default=True,
        category="advanced", since="M1", description="是否留存结构化的 Agent 执行轨迹",
    ),
    SettingDef(
        key="memory.enabled", label="工作空间记忆", kind=SettingKind.BOOL, default=True,
        category="advanced", since="M1", description="工作空间记忆总开关",
    ),
    SettingDef(
        key="memory.top_k", label="记忆注入条数", kind=SettingKind.INT, default=5, min=1, max=50,
        category="advanced", since="M1", description="每轮注入上下文的工作空间记忆条数",
    ),
]


# --------------------------------------------------------------------------- #
# 4. 注册表（模块级单例）
# --------------------------------------------------------------------------- #
# 全部已注册的设置声明：键 →声明。由 register_defs() 填充，app启动时调用一次。
REGISTRY: dict[str, SettingDef] = {}

# 事件订阅表：前缀 → 回调列表。键是「订阅前缀」（如 "llm."、"workspaces."、"" 表示全量）。
# 存列表而不是单回调，是为了允许同一前缀有多个订阅者（如模型层与 UI 都关心 llm.*）。
_LISTENERS: dict[str, list[Callable[["SettingsChangeEvent"], None]]] = {}

# 密钥键的命名空间前缀：任何以此开头的键都不允许走普通设置接口批量写入（见 put_settings）
SECRET_KEY_PREFIX = "secrets."

# 内置声明是否已装载过。注册表为空时（典型场景：单元测试或脚本直接 import 本模块，
# 没走 app/main.py 的 create_app）由_ensure_bootstrapped() 惰性补装，
# 这样「忘记注册」不会变成一个只在特定入口才复现的怪问题。
_bootstrapped = False


def _ensure_bootstrapped() -> None:
    """确保内置声明已装载（幂等）。

    为什么要有这个兜底：正常路径是 app/main.py 的 create_app() 调 register_defs(BUILTIN_DEFS)，
    但测试、一次性脚本、以及「先import 后启动」的场景都可能绕开它。
    这里在真正读设置时才补装，保证任何入口下 get_setting/list_defs 都可用。

    注意：**注册表非空时不补装**——各模块可能已经追加了自己的声明，
    此时再塞一遍内置声明没有意义（虽然覆盖同名是无害的）。
    """
    global _bootstrapped
    if _bootstrapped or REGISTRY:
        _bootstrapped = True
        return
    register_defs(BUILTIN_DEFS)
    _bootstrapped = True


@dataclass
class SettingsChangeEvent:
    """一次设置变更事件：写成功后发布，订阅者按需响应（重建 agent、刷新界面等）。"""

    # 发生变更的设置键（如 "llm.provider"）
    key: str
    # 变更后的新值（已通过声明校验）
    value: Any
    # 变更前的旧值；新增键时为None
    old_value: Any = field(default=None)


def register_defs(defs: list[SettingDef] | tuple[SettingDef, ...]) -> None:
    """把一批设置声明注册进全局注册表（幂等：重复注册会覆盖，后启动的模块优先）。

    允许覆盖同名声明，是为了让「后注册的模块能修正内置默认值」成为可能；
    但正常情况下不同模块不应该声明同一个键——那属于设计错误。

    :param defs: 要注册的 SettingDef 列表
    :raises ValueError: 列表里有 SettingDef 之外的元素
    """
    for item in defs:
        if not isinstance(item, SettingDef):
            raise ValueError(f"register_defs 只接受 SettingDef，收到 {type(item).__name__}")
        REGISTRY[item.key] = item


def get_def(key: str) -> SettingDef:
    """取某个设置键的声明（注册表为空时会自动装载内置声明）。

    :param key: 设置键，如 "llm.model"
    :return: 对应的 SettingDef
    :raises KeyError: 该键没有注册（调用方多半是拼错了键名）
    """
    _ensure_bootstrapped()
    if key not in REGISTRY:
        raise KeyError(f"未声明的设置键：{key}")
    return REGISTRY[key]


def list_defs() -> list[SettingDef]:
    """返回全部已注册的设置声明（按键排序，保证输出稳定）。

    :return: SettingDef 列表
    """
    _ensure_bootstrapped()
    return [REGISTRY[k] for k in sorted(REGISTRY)]


def get_setting(key: str) -> Any:
    """读取某个设置项的当前值：**已落库值优先，未落库则回落到声明默认值**。

    这就是「模块只声明、不写兜底逻辑」的落点——调用方直接get_setting("llm.model")，
    拿到的永远是合法值，不需要判断「用户到底配过没有」。

    数据库不可用（表不存在、首次启动尚未建表）时同样回落到默认值，
    保证设置读取永远不会把调用方的业务流程打断。

    :param key: 设置键
    :return: 当前生效的值
    :raises KeyError: 该键没有注册
    """
    definition = get_def(key)
    try:
        stored = setting_service.get_setting_value(key)
    except Exception:
        # 读库失败不能让调用方崩掉：设置只是「配置」，读不到就用默认值继续跑
        return definition.default
    if stored is None:
        return definition.default
    # 落库值理论上已被校验过，这里再过一次coerce 是为了兜住「手工改库」写坏的情况
    try:
        return definition.coerce(stored)
    except ValueError:
        return definition.default


def get_all_settings() -> dict[str, Any]:
    """读取全部**非密钥**设置项的当前值，供 GET /api/settings 一次性下发。

    :return: 键 → 当前值 的字典（不含任何 secrets.* 键）
    :raises ValueError: 不该出现——若发生说明注册表被塞进了密钥声明，请检查 secret 标记
    """
    values: dict[str, Any] = {}
    for definition in list_defs():
        # 密钥绝不出现在全量设置接口里：这是 doc/21 ARCH-2 §2.4 的安全红线
        if definition.secret or definition.key.startswith(SECRET_KEY_PREFIX):
            raise ValueError(f"设置键 {definition.key} 属于密钥命名空间，不能进全量设置接口")
        values[definition.key] = get_setting(definition.key)
    return values


def put_settings(partial: dict[str, Any]) -> dict[str, Any]:
    """批量校验并保存普通设置，成功后逐键发布变更事件。

    写入采用「先全部校验、再一次性落库」的策略：只要有一个键不合法，
    整个请求都不落库，避免「改了一半」导致配置处于不一致状态。

    :param partial: 键 → 新值 的字典（只需包含要改的键）
    :return: 保存后**全部**非密钥设置项的当前值
    :raises KeyError: 含有未注册的键
    :raises ValueError: 含有密钥键，或某个键的类型/取值不合法
    """
    if not isinstance(partial, dict):
        raise ValueError(f"设置值必须是键值对对象，收到 {type(partial).__name__}")

    # ---- 阶段一：全量校验（任何一键不合法就整体拒绝，此时尚未落库）----
    # 先记录旧值，供事件负载使用；顺序无关，校验全部通过后才写
    staged: list[tuple[SettingDef, Any, Any]] = []
    for key, raw in partial.items():
        # 密钥必须走专门的 secrets 接口：这里显式拦截，避免绕过「只进不出」的管控
        if key.startswith(SECRET_KEY_PREFIX):
            raise ValueError(f"设置键 {key} 属于密钥命名空间，请改用 /api/settings/secrets 接口")
        definition = get_def(key)          # 未注册的键在这里抛 KeyError
        normalized = definition.coerce(raw)  # 类型 + 区间 + 候选校验
        staged.append((definition, key, normalized))

    # ---- 阶段二：落库 ----
    #逐键写入（setting_service 内部按 key upsert）；此处不再逐键校验，
    # 因为阶段一已经保证全部合法
    for definition, key, normalized in staged:
        setting_service.set_setting_value(key, definition.kind, normalized)

    # ---- 阶段三：发布事件（在落库之后，保证订阅者读库时能读到新值）----
    for definition, key, normalized in staged:
        publish(key, normalized, old_value=_safe_old_value(definition))

    return get_all_settings()


def _safe_old_value(definition: SettingDef) -> Any:
    """读取某个设置项的「变更前值」，仅用于填充事件负载；读失败返回 None。

    :param definition: 设置声明
    :return: 旧值；读不到时为 None（订阅者应能容忍 old_value 为空）
    """
    try:
        stored = setting_service.get_setting_value(definition.key)
    except Exception:
        return None
    return stored


def publish(key: str, value: Any, old_value: Any = None) -> None:
    """发布一条设置变更事件，通知所有按前缀匹配的订阅者。

    前缀匹配规则：订阅前缀 "llm." 匹配 "llm.model"；前缀 "" 匹配全部键。
    某个订阅者抛异常不影响其它订阅者与调用方（设置已经落库，不该被监听器拖垮）。

    :param key: 变更的设置键
    :param value: 变更后的新值
    :param old_value: 变更前的旧值；新增键时为 None
    """
    event = SettingsChangeEvent(key=key, value=value, old_value=old_value)
    for prefix, callbacks in list(_LISTENERS.items()):
        # "" 是通配前缀，其余按 startswith 匹配
        if prefix and not key.startswith(prefix):
            continue
        for callback in list(callbacks):
            try:
                callback(event)
            except Exception:
                # 订阅者自己的问题不该让设置写入失败，这里吞掉即可
                # （生产环境应接入日志；本项目暂无统一日志组件，先保证主流程不被影响）
                continue


def subscribe(prefix: str, callback: Callable[[SettingsChangeEvent], None]) -> None:
    """订阅某个前缀下的设置变更（如订阅 "llm." 以便设置变了就重建 agent）。

    :param prefix: 键前缀；空串表示订阅全部设置变更
    :param callback: 收到事件时调用的函数，入参是 SettingsChangeEvent
    """
    _LISTENERS.setdefault(prefix, []).append(callback)


def unsubscribe(prefix: str, callback: Callable[[SettingsChangeEvent], None]) -> None:
    """取消订阅（订阅应随模块生命周期注销，避免监听器泄漏）。

    :param prefix: 订阅时用的前缀
    :param callback: 订阅时传入的同一个函数对象
    """
    callbacks = _LISTENERS.get(prefix)
    if not callbacks or callback not in callbacks:
        return
    callbacks.remove(callback)
    # 列表空了就把这个前缀整个删掉，避免 _LISTENERS 里堆积空列表
    if not callbacks:
        _LISTENERS.pop(prefix, None)


def reset_for_test() -> None:
    """清空注册表与订阅表，供测试用例在setup/teardown 之间隔离状态。

    注意：**不会**还原已经落库的值，只清内存里的声明与监听器。
    测试自己负责清理写入的设置键（见 tests/ 下各用例的 fixture）。
    """
    global _bootstrapped
    REGISTRY.clear()
    _LISTENERS.clear()
    _bootstrapped = False