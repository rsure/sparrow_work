"""EXT-4 的本地 Office 引擎适配层（office_cli）与解析降级链的回归测试。

本文件**不依赖真实引擎**：`httpx.post` 被替换成一个"按工具名分发"的假实现，
这样能在任何机器上（包括没有装 editor_sdk 的 CI）验证四件事：
    1. JSON-RPC 调用形状正确（方法名、参数名、请求 id）；
    2. 只读白名单真的拦住写工具；
    3. 实例归属正确：自己开的才关，用户开着的绝不关；
    4. 引擎不可用时解析链路降级而不报错（文本兜底带 `[降级读取]` 前缀）。

真实的 `.xlsx` 解析仍由 `tests/test_document_parser.py` 用 openpyxl 造样本覆盖，
两个文件分工明确：这里测"调用与选路"，那里测"内容对不对"。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：临时目录里放"文件"（内容无所谓，适配层不读文件本体，只看是否有后缀）
from pathlib import Path

# 测试框架：monkeypatch / 参数化
import pytest

# 第三方：伪造 httpx 抛出的连接异常（走 office_cli 的 except 分支）
import httpx

# 项目内：被测适配层
from app.services import office_cli
# 项目内：解析入口（测降级链）
from app.services import document_parser as dp
# 项目内：设置注册（office.* 五个键）
from app.services.office_settings_defs import register_office_defs
from app.services.settings_registry import get_def, put_settings


class _FakeResponse:
    """伪造 httpx 的响应对象：只需要 status_code 与 json()。"""

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        """保存条目。

        :param payload: JSON-RPC 响应体
        :param status_code: HTTP 状态码
        """
        # HTTP 状态码：非 200 会走"引擎返回 HTTP xxx"分支
        self.status_code = status_code
        # 响应体
        self._payload = payload

    def json(self) -> dict:
        """返回预置的 JSON 体。"""
        return self._payload


def _rpc_result(payload: dict) -> _FakeResponse:
    """把业务字典包成一次成功的 JSON-RPC 响应（与 MCP 的 content 形状一致）。"""
    # MCP 把业务结果序列化在 content[0].text 里
    text = __import__("json").dumps(payload, ensure_ascii=False)
    return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}})


class _FakeEngine:
    """一个按工具名分发的假引擎，同时记录被调用的工具顺序。"""

    def __init__(self, handlers: dict[str, dict]) -> None:
        """准备分发表。

        :param handlers: 工具名 → 该工具要返回的业务字典
        """
        # 工具名 → 返回体
        self.handlers = handlers
        # 调用过的方法（tools/list 与 tools/call 都记，便于断言探测行为）
        self.methods: list[str] = []
        # 调用过的工具名顺序（断言"关了几个实例""请求了几页"用）
        self.calls: list[str] = []
        # 收到的 JSON 请求体（断言参数形状用）
        self.payloads: list[dict] = []

    def post(self, url: str, *, json: dict | None = None, headers=None, timeout=None) -> _FakeResponse:
        """模拟 httpx.post。

        :param url: 目标地址（断言端口时用）
        :param json: JSON-RPC 请求体
        :param headers: 请求头（断言鉴权）
        :param timeout: 超时（忽略）
        :return: 伪造响应
        """
        body = json or {}
        self.methods.append(str(body.get("method")))
        self.payloads.append(body)
        if body.get("method") == "tools/list":
            return _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})
        params = body.get("params") or {}
        name = str(params.get("name"))
        self.calls.append(name)
        if name not in self.handlers:
            # 未登记的工具：明确报错，避免测试用例"以为调了其实没调"
            raise AssertionError(f"假引擎没登记工具 {name}")
        return _rpc_result(self.handlers[name])


@pytest.fixture(autouse=True)
def _office_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前后：注册 office.* 设置、把设置与适配层缓存都复位。"""
    register_office_defs()
    office_cli.reset_for_test()

    def _reset() -> None:
        """把五个 office.* 键写回默认值：设置是持久化的，不清会把状态漏给下一个用例。"""
        put_settings({
            "office.enabled": True,
            "office.port": 0,
            "office.timeout_ms": 15000,
            "office.max_rows": 5000,
            "office.max_cols": 40,
        })

    _reset()
    # 引擎状态是模块级缓存，用例之间必须清干净，否则前一个用例探到的端点会漏给下一个
    yield
    _reset()
    office_cli.reset_for_test()


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch):
    """装一个假引擎，并让端口探测直接"命中"第一个端口。"""

    def _install(handlers: dict[str, dict]) -> _FakeEngine:
        """装好假引擎并返回它，方便用例断言。"""
        fake = _FakeEngine(handlers)
        monkeypatch.setattr(office_cli.httpx, "post", fake.post)
        return fake

    return _install


def _touch(tmp_path: Path, name: str) -> Path:
    """造一个只有名字和后缀的"文件"（适配层不看内容）。"""
    path = tmp_path / name
    path.write_bytes(b"placeholder")
    return path


# --------------------------------------------------------------------------- #
# 端点探测与冷却
# --------------------------------------------------------------------------- #
def test_endpoint_probe_fails_then_cools_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """10 个端口都探不到时返回 None，并在冷却期内不再重复探测。"""
    attempts: list[str] = []

    def fake_post(url: str, **_kwargs) -> _FakeResponse:
        """模拟"端口没人监听"。"""
        attempts.append(url)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(office_cli.httpx, "post", fake_post)

    assert office_cli.endpoint() is None
    # 第一轮把 10 个端口都探了一遍
    assert len(attempts) == len(office_cli._PORT_RANGE)
    # 冷却期内再问一次：不应该再有任何请求
    before = len(attempts)
    assert office_cli.endpoint() is None
    assert len(attempts) == before


def test_endpoint_probe_respects_fixed_port(
    monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """office.port 固定时只探那一个端口（与桌面壳拉起引擎用的端口保持一致）。"""
    put_settings({"office.port": 39100})
    fake = engine({})
    assert office_cli.endpoint() == "http://127.0.0.1:39100"
    # 只探了一次 tools/list
    assert fake.methods == ["tools/list"]


def test_endpoint_refresh_ignores_cache(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    """refresh=True 会强制重探（用户刚启动引擎时的重试路径）。"""
    engine({})
    assert office_cli.endpoint() is not None
    # 再探一次仍然拿到地址（缓存命中也会返回同一个）
    assert office_cli.endpoint(refresh=True) is not None


# --------------------------------------------------------------------------- #
# 只读白名单
# --------------------------------------------------------------------------- #
def test_call_rejects_write_tool() -> None:
    """解析链路试图调用写工具时必须直接炸掉（而不是被引擎执行）。"""
    with pytest.raises(ValueError, match="不允许调用工具"):
        office_cli.call("doc_replace_text", {"file_id": 1}, 1000)


def test_call_rejects_unknown_tool() -> None:
    """未登记的工具同样拒绝：白名单是"列举法"，不是"排除法"。"""
    with pytest.raises(ValueError):
        office_cli.call("save_file", {}, 1000)


def test_call_raises_unavailable_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """端点不可用时抛 OfficeCliUnavailable（调用方据此降级，而不是当致命错误）。"""
    monkeypatch.setattr(office_cli, "endpoint", lambda **_kwargs: None)
    with pytest.raises(office_cli.OfficeCliUnavailable):
        office_cli.call("sheet_get_sheet_info", {"file_id": 1}, 1000)


# --------------------------------------------------------------------------- #
# 实例归属
# --------------------------------------------------------------------------- #
def test_instance_is_closed_only_when_we_opened_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """pool 里没有 → 自己打开、结束时关掉。"""
    path = _touch(tmp_path, "a.docx")
    fake = engine({
        "get_pool_status": {},                      # 用户没开过
        "open_file": {"file_id": 7},                # 我们打开，拿到 7
        "close_file": {},                           # 该被调用一次
    })
    monkeypatch.setattr(office_cli, "_try_call", lambda *a, **k: None)

    with office_cli._instance(path) as file_id:
        assert file_id == 7
    # 打开一次、关闭一次
    assert fake.calls.count("open_file") == 1
    assert fake.calls.count("close_file") == 1


def test_instance_never_closes_user_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """用户在 pool 里开着这个文件 → 复用、**不关**（关掉等于关掉用户的编辑器）。"""
    path = _touch(tmp_path, "b.docx")
    fake = engine({
        "get_pool_status": {"file_id": 99},
        "close_file": {},                           # 不该被调用
    })
    monkeypatch.setattr(office_cli, "_try_call", lambda *a, **k: None)

    with office_cli._instance(path) as file_id:
        assert file_id == 99
    assert "open_file" not in fake.calls
    assert "close_file" not in fake.calls


# --------------------------------------------------------------------------- #
# 三种品类的文本组装
# --------------------------------------------------------------------------- #
def test_read_doc_labels_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """doc 品类：正文 / 大纲 / 文本框与批注 三段都要拼上并各自带标记。"""
    path = _touch(tmp_path, "c.docx")
    engine({
        "get_pool_status": {"file_id": 1},
        "doc_resolve_document_structure": {"blocks": [{"text": "第一段"}, {"text": "第二段"}]},
        "doc_get_outline": {"text": "标题一"},
        "doc_list_textbox_and_comment": {"text": "批注：这里要改"},
    })

    text = office_cli.read_doc(path)
    assert "[正文]" in text
    assert "第一段\n第二段" in text
    assert "[大纲]\n标题一" in text
    assert "[文本框与批注]\n批注：这里要改" in text


def test_read_doc_raises_when_body_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """引擎返回空正文时抛 OfficeCliUnavailable，让上层回落到旧解析器。"""
    path = _touch(tmp_path, "d.docx")
    engine({
        "get_pool_status": {"file_id": 1},
        "doc_resolve_document_structure": {"blocks": []},
        # 两个可选取材工具返回空：单测里必须登记，否则假引擎会抛 AssertionError，
        # 那是"测试写漏了工具"而不是"引擎没读出正文"
        "doc_get_outline": {},
        "doc_list_textbox_and_comment": {},
    })

    with pytest.raises(office_cli.OfficeCliUnavailable):
        office_cli.read_doc(path)


def test_read_sheet_renders_rows_and_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """sheet 品类：`[Sheet 名称]` + `a | b` 行；超出行数上限要标注截断。"""
    path = _touch(tmp_path, "e.xlsx")
    # office.max_rows 下限 100、max_cols 下限 5（设置项有范围校验，这里必须给合法值）
    put_settings({"office.max_rows": 100, "office.max_cols": 5})
    engine({
        "get_pool_status": {"file_id": 2},
        "sheet_get_sheet_info": {"sheets": [{"name": "预算"}, {"name": "备注"}]},
        "sheet_get_used_range": {"row_count": 500, "column_count": 2},
        "sheet_get_cell_data": {"rows": [["项目", "金额"], ["服务器", 1200]]},
    })

    text = office_cli.read_sheet(path)
    assert "[Sheet 预算]" in text
    assert "项目 | 金额" in text
    # 子表名是逐个调的，两个都要出现
    assert "[Sheet 备注]" in text
    # 实际 500 行、上限 100 行 → 必须有截断提示
    assert "超过 100 行，已截断" in text


def test_read_slide_marks_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """slide 品类：逐页取文本并打 `[Slide N]` 标记。"""
    path = _touch(tmp_path, "f.pptx")
    engine({
        "get_pool_status": {"file_id": 3},
        "slide_get_info": {"page_count": 2},
        "slide_get_page_info": {"title": "封面"},
        "slide_get_text": {"text": "第一页正文"},
    })

    text = office_cli.read_slide(path)
    assert "[Slide 1]" in text
    assert "[Slide 2]" in text
    assert "第一页正文" in text


def test_read_slide_caps_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """页数超过上限（200）时截断并标注，不能把 3000 页读进上下文。"""
    path = _touch(tmp_path, "g.pptx")
    engine({
        "get_pool_status": {"file_id": 4},
        "slide_get_info": {"page_count": 500},
        "slide_get_page_info": {"title": "t"},
        "slide_get_text": {"text": "x"},
    })

    text = office_cli.read_slide(path)
    assert "超过 200 页，已截断" in text


def test_read_result_is_cached_by_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine
) -> None:
    """同一文件读两次只调一次引擎（批量索引时这一步决定快慢）。"""
    path = _touch(tmp_path, "h.xlsx")
    fake = engine({
        "get_pool_status": {"file_id": 5},
        "sheet_get_sheet_info": {"sheets": [{"name": "S"}]},
        "sheet_get_used_range": {"row_count": 1, "column_count": 1},
        "sheet_get_cell_data": {"rows": [["x"]]},
    })

    first = office_cli.read_sheet(path)
    sheet_calls = fake.calls.count("sheet_get_sheet_info")
    second = office_cli.read_sheet(path)
    assert first == second
    # 第二次命中缓存，没有再问引擎
    assert fake.calls.count("sheet_get_sheet_info") == sheet_calls


# --------------------------------------------------------------------------- #
# 解析链路的降级
# --------------------------------------------------------------------------- #
def test_parser_falls_back_to_legacy_xlsx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引擎不可用时 `.xlsx` 回落到 openpyxl 版解析器（行为与改造前一致）。"""
    path = _touch(tmp_path, "i.xlsx")
    monkeypatch.setattr(dp, "_parse_xlsx", lambda p: "旧版解析结果")

    def unavailable(_path: Path) -> str:
        """模拟探测不到引擎。"""
        raise office_cli.OfficeCliUnavailable("no engine")

    monkeypatch.setattr(office_cli, "read_sheet", unavailable)

    assert dp.parse_document(path) == "旧版解析结果"


def test_parser_prefixes_degraded_for_pptx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.pptx` 没有旧解析器：文本兜底结果必须带 `[降级读取]` 前缀（RAG 侧据此跳过）。"""
    path = tmp_path / "j.pptx"
    path.write_bytes("幻灯片纯文本".encode("utf-8"))

    def unavailable(_path: Path) -> str:
        """模拟探测不到引擎。"""
        raise office_cli.OfficeCliUnavailable("no engine")

    monkeypatch.setattr(office_cli, "read_slide", unavailable)

    text = dp.parse_document(path)
    assert text.startswith("[降级读取]")
    assert "幻灯片纯文本" in text


def test_parser_skips_engine_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """office.enabled=off 时连探测都不做，直接走旧解析器。"""
    path = _touch(tmp_path, "k.xlsx")
    put_settings({"office.enabled": False})
    monkeypatch.setattr(dp, "_parse_xlsx", lambda p: "旧版解析结果")

    def boom(_path: Path) -> str:
        """被调用就说明开关没生效。"""
        raise AssertionError("关掉 office.enabled 后不该调用引擎")

    monkeypatch.setattr(office_cli, "read_sheet", boom)

    assert dp.parse_document(path) == "旧版解析结果"


def test_office_settings_registered() -> None:
    """office.* 五个键必须注册（前端设置页靠 meta 自动出现分区的）。"""
    keys = (
        "office.enabled",
        "office.port",
        "office.timeout_ms",
        "office.max_rows",
        "office.max_cols",
    )
    for key in keys:
        # get_def 找不到会抛 KeyError，这里顺便就是"已注册"的断言
        assert get_def(key).category == "office"


def test_suffixes_point_to_office_families() -> None:
    """三个品类的新后缀都要进注册表，且都算结构化（写文件时要拒绝直接写）。"""
    for suffix in (".docx", ".doc", ".wps", ".xlsx", ".xls", ".pptx", ".ppt"):
        assert suffix in dp.supported_suffixes()
        # 注意必须传"文件名"而不是裸后缀：Path(".docx").suffix 是空串（被当成隐藏文件）
        assert dp.is_structured(f"sample{suffix}")


def test_unsupported_office_suffix_gets_save_as_hint(tmp_path: Path) -> None:
    """`.rtf` / `.odt` / `.et` / `.dps` 明确报"另存为"，不给乱码读出来的机会。"""
    for suffix, hint in ((".rtf", ".docx"), (".odt", ".docx"), (".et", ".xlsx"), (".dps", ".pptx")):
        path = tmp_path / f"note{suffix}"
        path.write_bytes(b"{\\rtf1 whatever}")
        with pytest.raises(dp.UnsupportedOfficeFormat) as excinfo:
            dp.parse_document(path)
        message = str(excinfo.value)
        assert suffix in message
        assert hint in message


def test_degraded_text_is_recognised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """降级结果要能被 is_degraded 认出来（RAG 入库侧据此拒绝入库）。"""
    path = tmp_path / "l.pptx"
    path.write_bytes("幻灯片纯文本".encode("utf-8"))

    def unavailable(_path: Path) -> str:
        """模拟探测不到引擎。"""
        raise office_cli.OfficeCliUnavailable("no engine")

    monkeypatch.setattr(office_cli, "read_slide", unavailable)

    text = dp.parse_document(path)
    assert dp.is_degraded(text)
    # 正常解析出来的文本不能被误判成降级
    assert not dp.is_degraded("普通正文")


def test_rag_index_refuses_degraded_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """降级结果绝不入库：index_file 必须抛错，而不是把乱码切成一堆切片存起来。"""
    # 项目内：RAG 入库服务（这里只验证"拒绝入库"这一步，不真跑向量化）
    from app.services import rag_store_service as rag

    path = tmp_path / "m.pptx"
    path.write_bytes(b"not really a pptx")
    monkeypatch.setattr(
        rag, "load_file_text", lambda _p, _enc="utf-8": f"{dp.DEGRADED_PREFIX}乱码正文"
    )

    service = rag.RagStoreService()
    with pytest.raises(ValueError, match="拒绝入库"):
        service.index_file(path)


def test_read_text_any_reports_save_as_hint(tmp_path: Path) -> None:
    """工具层读 `.rtf` 时把"另存为"提示带回给模型，而不是返回乱码。"""
    # 项目内：工具层的通用文本读取
    from app.tools import tool_utils

    path = tmp_path / "n.rtf"
    path.write_bytes(b"{\\rtf1 whatever}")
    text, reason = tool_utils.read_text_any(path)
    assert text is None
    assert "另存为" in reason
