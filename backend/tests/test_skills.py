"""EXT-1 技能系统的回归测试。

覆盖四层，每层的失败方式都不一样：
    1. loader    —— 手写 frontmatter 出错是常态，必须"坏一个不影响其它"；
    2. registry  —— 启停开关、目录优先级、提示词摘要；
    3. slash     —— `/技能名 参数` 的识别边界（不能把 `/usr/bin` 当技能）；
    4. tools     —— list_skills / read_skill 能被模型调用，且禁用后拒绝。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：临时目录与路径
from pathlib import Path

# 测试框架：pytest 断言与 monkeypatch
import pytest

# 项目内：被测试的四层
from app.skills import loader, registry, slash
from app.tools import skill_tool


_GOOD_SKILL = """---
name: {name}
description: {desc}
tools: [read_file]
---
第一步：读文件。
第二步：总结。
"""


def _write_skill(root: Path, dirname: str, name: str, desc: str = "测试技能") -> Path:
    """在 root/dirname/SKILL.md 写一个合法技能。

    :param root: 技能根目录
    :param dirname: 子目录名
    :param name: frontmatter 里的技能名
    :param desc: 描述
    :return: SKILL.md 路径
    """
    folder = root / dirname
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / loader.SKILL_FILENAME
    path.write_text(_GOOD_SKILL.format(name=name, desc=desc), encoding="utf-8")
    return path


@pytest.fixture()
def skill_root(tmp_path: Path) -> Path:
    """准备一个隔离的技能根目录（2 个合法 + 1 个坏 + 1 个重名）。"""
    root = tmp_path / "skills"
    _write_skill(root, "alpha", "alpha", "处理 Excel 表格")
    _write_skill(root, "beta", "beta", "写周报")
    # 坏文件：缺 frontmatter
    bad = root / "broken"
    bad.mkdir()
    (bad / loader.SKILL_FILENAME).write_text("正文没有 frontmatter", encoding="utf-8")
    # 重名：与 alpha 同名，应被忽略并记一条错误
    _write_skill(root, "alpha-copy", "alpha", "重复的技能名")
    return root


def test_parse_skill_file() -> None:
    """合法 SKILL.md 应解析出名字/描述/工具/正文。"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = _write_skill(Path(tmp), "demo", "demo-skill", "演示用")
        spec = loader.parse_skill_file(path)

    assert spec.name == "demo-skill"
    assert spec.description == "演示用"
    assert spec.tools == ("read_file",)
    assert "第一步" in spec.body


def test_parse_rejects_bad_frontmatter(tmp_path: Path) -> None:
    """缺 frontmatter / 名字非法 / 缺描述都要明确报错（而不是静默加载一个空技能）。"""
    cases = {
        "no-frontmatter": "正文",
        "bad-name": "---\nname: 中文名字\ndescription: x\n---\n正文",
        "no-desc": "---\nname: ok-name\n---\n正文",
        "empty-body": "---\nname: ok-name\ndescription: x\n---\n",
    }
    for folder, content in cases.items():
        target = tmp_path / folder
        target.mkdir()
        path = target / loader.SKILL_FILENAME
        path.write_text(content, encoding="utf-8")
        with pytest.raises(loader.SkillFormatError):
            loader.parse_skill_file(path)


def test_discover_isolates_broken_and_duplicate(skill_root: Path) -> None:
    """坏文件与重名只记错误，不影响其它技能被加载。"""
    specs, errors = loader.discover([skill_root])

    assert {spec.name for spec in specs} == {"alpha", "beta"}
    assert len(errors) == 2
    reasons = " ".join(error.reason for error in errors)
    assert "frontmatter" in reasons or "重复" in reasons


def test_registry_respects_switch_and_disable(skill_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """总开关 / 单技能禁用 / 提示词摘要三者联动。"""
    settings = {"skill.enabled": True, "skill.disabled": ["beta"], "skill.dirs": []}
    monkeypatch.setattr(registry, "default_skills_dir", lambda: skill_root)
    monkeypatch.setattr(registry, "_read_json_setting", lambda key, default: settings.get(key, default))

    snapshot = registry.reload(force=True)
    assert [item["name"] for item in snapshot["skills"]] == ["alpha", "beta"]
    assert snapshot["disabled"] == ["beta"]

    # 禁用后：清单里仍在，但 usable 返回 None，提示词里也不出现
    assert registry.is_disabled("beta") is True
    assert registry.usable("beta") is None
    assert registry.usable("alpha") is not None
    prompt = registry.build_prompt()
    assert "alpha" in prompt
    assert "beta" not in prompt

    # 总开关关闭：任何技能都不可用，提示词为空
    settings["skill.enabled"] = False
    registry.reload(force=True)
    assert registry.usable("alpha") is None
    assert registry.build_prompt() == ""


def test_slash_parse_boundaries() -> None:
    """只有「/合法技能名」才算指令；Unix 路径不能被误判。"""
    assert slash.parse("/my-skill") == slash.SlashCommand(name="my-skill", args="")
    assert slash.parse("/my-skill  参数 带空格 ") == slash.SlashCommand(name="my-skill", args="参数 带空格")
    assert slash.parse("/usr/bin/env") is None
    assert slash.parse("普通提问 /my-skill") is None
    assert slash.parse("/技能名") is None


def test_slash_expand_contains_body_and_args() -> None:
    """展开后的消息要同时包含技能正文与用户参数，模型才知道两者。"""
    spec = loader.SkillSpec(
        name="demo", description="演示", tools=(), body="步骤 A",
        path=Path("D:/x/SKILL.md"), mtime=0.0,
    )
    text = slash.expand(spec, "处理 D:/a.xlsx")
    assert "步骤 A" in text
    assert "处理 D:/a.xlsx" in text
    assert "技能说明开始" in text


def test_tools_list_and_read(skill_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """模型侧的两个工具：能列清单、能读正文；禁用后读取失败。"""
    settings = {"skill.enabled": True, "skill.disabled": [], "skill.dirs": []}
    monkeypatch.setattr(registry, "default_skills_dir", lambda: skill_root)
    monkeypatch.setattr(registry, "_read_json_setting", lambda key, default: settings.get(key, default))
    registry.reload(force=True)

    listing = skill_tool.list_skills.invoke({})
    assert listing.startswith("OK:")
    assert "alpha" in listing

    body = skill_tool.read_skill.invoke({"name": "alpha"})
    assert body.startswith("OK:")
    assert "第一步" in body

    settings["skill.disabled"] = ["alpha"]
    registry.reload(force=True)
    denied = skill_tool.read_skill.invoke({"name": "alpha"})
    assert denied.startswith("FAIL:")
