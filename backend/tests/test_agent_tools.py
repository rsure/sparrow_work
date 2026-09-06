"""Agent 原子工具自测：list_dir / read_file / grep_files / write_file / edit_file / rag 范围解析。

全部在 pytest 的临时目录里造文件，不调用大模型，也不写真实的知识库数据库。
工具是 LangChain 的 StructuredTool，统一用 .invoke({参数字典}) 调用，与 Agent 实际调用方式一致。
"""

# 让类型注解延迟求值（PEP 563），便于使用 X | None 这类新语法
from __future__ import annotations

# 构造测试目录与文件的路径对象
from pathlib import Path

# 测试框架：tmp_path（临时目录）与 monkeypatch（替换函数）两个内置 fixture 来自它
import pytest

# 被测对象：只读类工具 + 模块本身（用于 monkeypatch 替换"列出全部已导入文档"）
from app.tools import file_read_tool
from app.tools.file_read_tool import grep_files, list_dir, read_file
# 被测对象：公共底座模块（用于把临时目录伪装成系统目录、直接测系统路径判断）
from app.tools import tool_utils
# 被测对象：写文件类工具 + 模块本身（用于把临时目录加进受保护目录）
from app.tools import file_write_tool
from app.tools.file_write_tool import edit_file, write_file


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """造一个小目录树：两层目录、UTF-8/GBK 文本、二进制文件、会被跳过的 node_modules。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "需求.md").write_text("# 登录需求\n密码至少 8 位\n", encoding="utf-8")
    (tmp_path / "docs" / "gbk.txt").write_bytes("中文编码测试：退款流程".encode("gbk"))
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("退款流程", encoding="utf-8")
    return tmp_path


def test_list_dir_counts(sample_dir: Path) -> None:
    """当前层只数直接子项；递归时统计全部文件并跳过 node_modules。"""
    flat = list_dir.invoke({"path": str(sample_dir)})
    assert flat.startswith("OK:")
    assert "子目录 2 个，文件 1 个" in flat

    deep = list_dir.invoke({"path": str(sample_dir), "recursive": True})
    assert "文件 3 个" in deep
    assert "已跳过 1 个依赖/缓存目录" in deep


def test_relative_path_rejected() -> None:
    """相对路径有歧义，必须拒绝并提示模型向用户要完整路径。"""
    out = list_dir.invoke({"path": "docs"})
    assert out.startswith("FAIL:") and "绝对路径" in out


def test_read_file_encodings_and_binary(sample_dir: Path) -> None:
    """GBK 文本能正确解码；二进制只返回元信息；offset 分段读取。"""
    gbk = read_file.invoke({"path": str(sample_dir / "docs" / "gbk.txt")})
    assert "退款流程" in gbk and "gb18030" in gbk

    png = read_file.invoke({"path": str(sample_dir / "logo.png")})
    assert png.startswith("FAIL:") and "二进制" in png

    part = read_file.invoke({"path": str(sample_dir / "docs" / "需求.md"), "max_chars": 3})
    assert "还剩" in part and "offset=3" in part


def test_grep_files_name_and_content(sample_dir: Path) -> None:
    """内容命中给出行号；文件名命中也算；node_modules 里的同名内容不出现。"""
    out = grep_files.invoke({"root": str(sample_dir), "keyword": "退款"})
    assert "gbk.txt" in out and "第 1 行" in out
    assert "node_modules" not in out.split("\n", 1)[1]

    by_name = grep_files.invoke({"root": str(sample_dir), "keyword": "需求"})
    assert "[文件名+内容命中]" in by_name and "需求.md" in by_name


def _answer_confirm(monkeypatch: pytest.MonkeyPatch, approved: bool) -> list[dict]:
    """把 LangGraph 的 interrupt() 换成"立即返回用户决定"，让写工具能脱离 Agent 单独测试。

    :param monkeypatch: pytest 的替换工具
    :param approved: 模拟用户点了同意（True）还是拒绝（False）
    :return: 记录每次确认请求 payload 的列表，用来断言弹窗内容
    """
    asked: list[dict] = []

    def fake_interrupt(payload: dict) -> dict:
        """记录确认请求并直接给出用户决定。"""
        asked.append(payload)
        return {"approved": approved}

    monkeypatch.setattr(tool_utils, "interrupt", fake_interrupt)
    return asked


def test_write_file_new_exists_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """新建也要确认（见 policy 的 require_confirm）；已存在默认拒绝；overwrite=True 确认后覆盖并留备份。

    注：早期版本"新建文件不弹确认"，后来按"所有落盘都要让用户看见"统一改为必确认
    （见 app/tools/policy.py 的 write_file 策略与 SYSTEM_PROMPT 的【安全规则】）。
    本用例断言的是**当前**策略：新建同样会弹一次确认。
    """
    asked = _answer_confirm(monkeypatch, approved=True)
    target = tmp_path / "out" / "note.md"
    assert write_file.invoke({"path": str(target), "content": "v1"}).startswith("OK:")
    assert target.read_text(encoding="utf-8") == "v1"
    # 新建同样需要用户确认：落盘位置必须让人看见
    assert len(asked) == 1 and asked[0]["tool"] == "write_file"

    asked.clear()
    refused = write_file.invoke({"path": str(target), "content": "v2"})
    assert refused.startswith("FAIL:") and "已存在" in refused
    # 同上：确认先于函数体，"文件已存在"的判断在确认之后才做
    assert len(asked) == 1

    done = write_file.invoke({"path": str(target), "content": "v2", "overwrite": True})
    assert done.startswith("OK:") and "备份" in done
    assert target.read_text(encoding="utf-8") == "v2"
    assert len(list(target.parent.glob("note.md.*.bak"))) == 1
    assert asked[0]["tool"] == "write_file" and asked[0]["args"]["path"] == str(target.resolve())


def test_write_file_overwrite_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用户拒绝覆盖：返回 FAIL，原文件不变，也不产生备份。"""
    _answer_confirm(monkeypatch, approved=False)
    target = tmp_path / "note.md"
    target.write_text("v1", encoding="utf-8")

    out = write_file.invoke({"path": str(target), "content": "v2", "overwrite": True})
    assert out.startswith("FAIL:") and "拒绝" in out
    assert target.read_text(encoding="utf-8") == "v1"
    assert not list(tmp_path.glob("*.bak"))


def test_write_file_protected_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """受保护目录内一律拒绝写入。

    注：早期版本靠 file_write_tool._PROTECTED_DIRS 这份模块内名单，
    后来统一收敛到 tool_utils.PATH_RULES（见该文件「路径策略：声明式规则表」章节），
    由 path_decision() 一处裁决。本用例改为往规则表里追加一条临时规则。
    """
    # 造一条规则：临时目录只允许读，禁止写
    rule = tool_utils.PathRule(
        root=tmp_path,
        allow=frozenset({tool_utils.OP_READ}),
        reason="测试用受保护目录",
    )
    # 整体替换规则表：既要追加新规则，也要保留原有的 backend 只读规则
    monkeypatch.setattr(tool_utils, "PATH_RULES", (rule,) + tool_utils.PATH_RULES)

    out = write_file.invoke({"path": str(tmp_path / "a.txt"), "content": "x"})
    assert out.startswith("FAIL:") and "受保护" in out
    # 只读操作仍然放行——规则表区分的是操作类型，不是一刀切
    assert tool_utils.path_decision(tmp_path / "a.txt", tool_utils.OP_READ) is None


def test_system_paths_blocked_everywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """系统目录：直接点名时读、搜、写全部拒绝；遍历父目录时自动跳过并报告。"""
    sys_dir = tmp_path / "FakeWindows"
    sys_dir.mkdir()
    (sys_dir / "kernel.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "user.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(tool_utils, "SYSTEM_DIRS", [sys_dir])

    for out in (
        read_file.invoke({"path": str(sys_dir / "kernel.txt")}),
        list_dir.invoke({"path": str(sys_dir)}),
        grep_files.invoke({"root": str(sys_dir), "keyword": "secret"}),
        write_file.invoke({"path": str(sys_dir / "new.txt"), "content": "x"}),
    ):
        assert out.startswith("FAIL:") and "系统" in out

    flat = list_dir.invoke({"path": str(tmp_path)})
    assert "FakeWindows" not in flat and "已隐藏 1 个系统文件/目录" in flat

    found = grep_files.invoke({"root": str(tmp_path), "keyword": "secret"})
    assert "user.txt" in found and "kernel.txt" not in found and "跳过 1 个系统文件/目录" in found


def test_drive_root_system_names() -> None:
    """盘根目录下的回收站、pagefile.sys 等按名字识别为系统项，普通目录不受影响。"""
    assert tool_utils.system_path_reason(Path(r"D:\$Recycle.Bin\S-1-5\a.txt"))
    assert tool_utils.system_path_reason(Path(r"C:\pagefile.sys"))
    assert tool_utils.system_path_reason(Path(r"D:\docs\boot\readme.md")) is None


def test_edit_file_unique_multi_crlf_gbk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """唯一匹配才替换；多处匹配要 replace_all；保留 CRLF 换行与 GBK 编码。

    注：确认发生在**工具函数体执行之前**（见 policy.make_tool：先裁决、ASK 时先问用户，
    再执行函数体）。因此即便后续校验会失败，也已经弹过确认了——
    这是"先问后做"的固有代价，换来的是"任何落盘都必经用户点头"。
    """
    asked = _answer_confirm(monkeypatch, approved=True)
    f = tmp_path / "conf.ini"
    f.write_bytes("端口=8000\r\n端口备注=旧\r\n".encode("gbk"))

    multi = edit_file.invoke({"path": str(f), "old_text": "端口", "new_text": "port"})
    assert multi.startswith("FAIL:") and "2 次" in multi
    assert len(asked) == 1                              # 多处匹配：确认过了，但拒绝执行

    asked.clear()
    missing = edit_file.invoke({"path": str(f), "old_text": "不存在", "new_text": "x"})
    assert missing.startswith("FAIL:")
    assert len(asked) == 1                              # 同样先确认、再校验失败

    asked.clear()
    ok = edit_file.invoke({"path": str(f), "old_text": "端口=8000\n", "new_text": "端口=9000\n"})
    assert ok.startswith("OK:")
    assert f.read_bytes().decode("gbk") == "端口=9000\r\n端口备注=旧\r\n"
    assert asked[0]["tool"] == "edit_file" and asked[0]["args"]["new_text"] == "端口=9000\n"


def test_rag_scope_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """检索范围既能写文件夹绝对路径（匹配其下所有文档），也能只写文件名。"""
    a = str((tmp_path / "proj" / "a.md").resolve())
    b = str((tmp_path / "proj" / "sub" / "b.pdf").resolve())
    c = str((tmp_path / "other" / "c.md").resolve())
    monkeypatch.setattr(
        file_read_tool, "all_indexed_docs",
        lambda: [{"id": i, "source": s} for i, s in enumerate([a, b, c])],
    )

    by_dir, missing = file_read_tool.resolve_scope([str(tmp_path / "proj")])
    assert set(by_dir) == {a, b} and not missing

    by_name, missing = file_read_tool.resolve_scope(["C.MD", "nope.txt"])
    assert by_name == [c] and missing == ["nope.txt"]
