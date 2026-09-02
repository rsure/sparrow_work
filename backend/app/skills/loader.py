# app/skills/loader.py
"""技能发现与解析：扫描目录，把每个 SKILL.md 读成 `SkillSpec`。

目录约定（与 Claude Code 一致，便于用户迁移已有技能）：

    <skills 根目录>/
    └── my-skill/
        ├── SKILL.md        # 必备：frontmatter + 正文
        └── （该技能自带的说明/示例文件，本层不读取）

SKILL.md 格式：

    ---
    name: my-skill
    description: 一句话说明（模型据此判断什么时候该用）
    tools: [read_file, grep_files]     # 可选，仅作声明与展示
    ---
    （正文：给模型的操作说明）

两条刻意的限制：
    1. **只认一层目录**：`root/*/SKILL.md`。深层嵌套会让"技能叫什么"变得含糊，
       也会让误把整棵仓库当技能根目录时扫出一堆垃圾。
    2. **解析失败不影响其它技能**：单个文件写坏只记一条错误，不抛异常——
       用户手写 frontmatter 出错是常态，不能因此让整个扩展能力不可用。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：正则校验技能名；dataclass 描述一个技能；Path 表示路径
import re
from dataclasses import dataclass
from pathlib import Path
# 标准库：读取 frontmatter 用的 YAML 解析（PyYAML 已随 langchain 生态装上，无需新增依赖）
import yaml

# 技能清单文件名（大小写敏感：与社区约定一致）
SKILL_FILENAME = "SKILL.md"

# 技能名允许的字符：小写字母数字 + 连字符/下划线，最长 64。
# 限制它的原因：技能名会进 `/name` 指令与系统提示词，空格/中文会让解析与展示都变复杂。
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# frontmatter 分隔符：文件开头必须是单独一行 "---"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)

# 技能正文最多注入多少字符：防一个巨型 SKILL.md 把上下文吃光（正文按需读取时也受此约束）
MAX_BODY_CHARS = 20_000


class SkillFormatError(ValueError):
    """SKILL.md 格式不合法（缺 frontmatter、name 非法、缺 description 等）。"""


@dataclass(frozen=True)
class SkillSpec:
    """一个已解析的技能。"""

    # 技能唯一 id（小写 kebab-case），也是 `/name` 指令里的名字
    name: str
    # 一句话说明：进系统提示词，模型据此判断何时调用
    description: str
    # 该技能声明会用到的底层工具名（仅声明与展示，不做强制约束）
    tools: tuple[str, ...]
    # 技能正文（给模型的操作说明）
    body: str
    # SKILL.md 的绝对路径（排障与"我要改哪份文件"用）
    path: Path
    # 文件修改时间（用于前端显示"最近更新"，也是将来热重载的判断依据）
    mtime: float

    def to_dict(self, *, enabled: bool = True) -> dict:
        """转成接口/前端使用的字典（**不含正文**，避免列表接口过大）。

        :param enabled: 该技能当前是否启用
        :return: 可 JSON 序列化的字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "path": str(self.path),
            "mtime": self.mtime,
            "enabled": enabled,
            # 正文长度给前端一个"这份技能有多长"的直觉，正文本身走详情接口
            "body_chars": len(self.body),
        }


@dataclass(frozen=True)
class SkillLoadError:
    """一条加载失败记录（路径 + 原因），随列表一起下发给前端。"""

    # 出问题的 SKILL.md 路径
    path: Path
    # 人类可读的失败原因
    reason: str

    def to_dict(self) -> dict:
        """转成可 JSON 序列化的字典。"""
        return {"path": str(self.path), "reason": self.reason}


def default_skills_dir() -> Path:
    """返回用户级技能目录（`<用户数据目录>/app-backend/skills`）。

    与密钥/日志放在同一个应用目录下，卸载时一起清理；
    目录不存在不影响使用（reload 时会自动创建，见 registry.reload）。

    :return: 技能根目录
    """
    # 标准库：跨平台取用户数据目录（与 services/secrets.py 保持同一套约定）
    import os

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif hasattr(os, "uname") and os.uname().sysname == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "app-backend" / "skills"


def parse_skill_file(path: Path) -> SkillSpec:
    """解析一个 SKILL.md。

    :param path: SKILL.md 的路径
    :return: SkillSpec
    :raises SkillFormatError: 缺 frontmatter / name 非法 / 缺 description / 正文为空
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillFormatError(f"读取失败：{exc}") from exc

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise SkillFormatError("缺少 frontmatter（文件开头需要 --- 包裹的元数据块）")

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"frontmatter 不是合法 YAML：{exc}") from exc
    if not isinstance(meta, dict):
        raise SkillFormatError("frontmatter 必须是键值对")

    name = str(meta.get("name") or "").strip()
    if not _NAME_RE.match(name):
        raise SkillFormatError(
            f"name 非法（{name!r}）：只允许小写字母/数字/连字符/下划线，且不超过 64 字符"
        )

    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillFormatError("缺少 description（模型靠它判断什么时候用这个技能）")

    raw_tools = meta.get("tools") or []
    if isinstance(raw_tools, str):
        # 允许写成 "read_file, grep_files"，省去用户记 YAML 列表语法的负担
        raw_tools = [item.strip() for item in raw_tools.split(",") if item.strip()]
    if not isinstance(raw_tools, list):
        raise SkillFormatError("tools 必须是列表（或逗号分隔的字符串）")
    tools = tuple(str(item).strip() for item in raw_tools if str(item).strip())

    body = raw[match.end():].strip()
    if not body:
        raise SkillFormatError("正文为空（没有操作说明，技能无法执行）")
    if len(body) > MAX_BODY_CHARS:
        # 截断而不是报错：宁可少读一点，也不要让用户因为"写太长"而完全用不了
        body = body[:MAX_BODY_CHARS] + "\n\n…（技能正文过长，已截断）"

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    return SkillSpec(
        name=name,
        description=description,
        tools=tools,
        body=body,
        path=path.resolve(),
        mtime=mtime,
    )


def discover(dirs: list[Path]) -> tuple[list[SkillSpec], list[SkillLoadError]]:
    """扫描多个根目录，收集全部技能。

    同名技能以**先出现的目录**为准（调用方按优先级排列目录：用户目录在前、额外目录在后），
    后面的同名项记一条错误，便于用户发现"放错地方了"。

    :param dirs: 技能根目录列表（已展开、已去重）
    :return: (技能列表, 错误列表)
    """
    specs: list[SkillSpec] = []
    errors: list[SkillLoadError] = []
    seen: set[str] = set()

    for root in dirs:
        if not root.is_dir():
            continue
        # 只扫一层：root/*/SKILL.md
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            skill_file = child / SKILL_FILENAME
            if not skill_file.is_file():
                continue
            try:
                spec = parse_skill_file(skill_file)
            except SkillFormatError as exc:
                errors.append(SkillLoadError(path=skill_file, reason=str(exc)))
                continue
            if spec.name in seen:
                errors.append(SkillLoadError(
                    path=skill_file, reason=f"技能名 {spec.name!r} 与前面的目录重复，本条已忽略",
                ))
                continue
            seen.add(spec.name)
            specs.append(spec)

    specs.sort(key=lambda item: item.name)
    return specs, errors
