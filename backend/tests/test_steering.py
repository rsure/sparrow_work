"""ARCH-6 执行中插话（steering）的回归测试。

覆盖四层，每层都能单独失败，方便定位：
    1. 队列本身：入队 / 取走 / 记账 / 轮次清理，以及各种拒绝条件；
    2. 取消标记：只命中指定工具、命中后消费掉；
    3. 工具包装层（`tools.policy.make_tool`）：真的会跳过执行、真的会把插话追加进结果文本；
    4. HTTP 端点：没有活跃流时拒绝、开关关闭时拒绝、工具已在执行时拒绝。

为什么第 3 层必须测：
    前端按钮、SSE 事件都只是"看得见的部分"。真正决定"模型有没有看到这句话"的，
    是 `make_tool` 的 wrapper 有没有把它拼进返回值。这一层断掉的话，
    界面上一切正常（气泡变成已送达），模型却完全不知道用户说过话。
"""

# 第三方：pytest 的 monkeypatch 用来临时替换开关与请求上下文
import pytest
# 第三方：控制器级测试用 TestClient 直接打 HTTP 端点
from fastapi.testclient import TestClient
# 项目内：被测的插话服务与工具包装层
from app.services import steering
from app.tools import policy as policy_mod
from app.tools.policy import Action, Kind, Level, Policy, make_tool
# 项目内：工具层的请求上下文（会话 id 决定插话队列挂在哪）
from app.tools import session as tool_session
# 项目内：控制器与会话状态（端点测试要伪造"有流在跑"）
from app.controllers import chat_controller as chat
# 项目内：真实应用实例（端点测试直接打路由，不绕过依赖注入与校验）
from app.main import app

# 模块级测试客户端：端点测试直接打真实路由
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """每个用例前后都清空插话队列，避免用例之间互相污染。"""
    steering.reset_for_test()
    yield
    steering.reset_for_test()


# --------------------------------------------------------------------------- #
# 1. 队列本身
# --------------------------------------------------------------------------- #
def test_enqueue_then_drain_is_fifo_and_marks_injected() -> None:
    """先入先出；取走后进入「已注入待上报」，由控制器取走。"""
    first = steering.enqueue("s1", "  第一条  ")
    second = steering.enqueue("s1", "第二条")

    # 首尾空白会被去掉：模型不该看到用户手滑打的前导空格
    assert first.content == "第一条"
    assert steering.pending_count("s1") == 2

    items = steering.drain("s1")
    assert [item.content for item in items] == ["第一条", "第二条"]
    assert steering.pending_count("s1") == 0

    injected = steering.take_injected("s1")
    assert [item.steer_id for item in injected] == [first.steer_id, second.steer_id]
    # 取走即清空：控制器在 on_tool_end 里只会取到一次，不会重复发事件
    assert steering.take_injected("s1") == []


def test_enqueue_rejects_empty_long_and_too_many() -> None:
    """空内容、超长、攒太多都要被拒绝，否则会把上下文撑爆。"""
    with pytest.raises(ValueError):
        steering.enqueue("s1", "   ")

    with pytest.raises(ValueError, match="2000"):
        steering.enqueue("s1", "字" * (steering.MAX_CONTENT_CHARS + 1))

    for index in range(steering.MAX_PENDING):
        steering.enqueue("s1", f"第 {index} 条")
    with pytest.raises(ValueError, match="排队"):
        steering.enqueue("s1", "再来一条")


def test_begin_turn_drops_leftovers_from_the_previous_turn() -> None:
    """上一轮没等到工具边界的插话必须丢掉，不能串到下一轮。"""
    steering.enqueue("s1", "上一轮的插话")
    steering.request_tool_cancel("s1", "write_file")

    steering.begin_turn("s1")

    assert steering.pending_count("s1") == 0
    assert steering.has_tool_cancel("s1") is False
    assert steering.take_injected("s1") == []


# --------------------------------------------------------------------------- #
# 2. 取消标记
# --------------------------------------------------------------------------- #
def test_cancel_marker_only_matches_the_requested_tool() -> None:
    """指定了工具名时，别的工具不受影响，标记也不会被误消费。"""
    steering.request_tool_cancel("s1", "write_file")

    assert steering.take_tool_cancel("s1", "read_file") is False
    # 上一步没命中，标记还在
    assert steering.has_tool_cancel("s1") is True
    assert steering.take_tool_cancel("s1", "write_file") is True
    # 命中即消费：取消只作用于一次调用
    assert steering.take_tool_cancel("s1", "write_file") is False


def test_cancel_marker_with_empty_tool_matches_anything() -> None:
    """空串表示「下一个工具，不管是什么」（前端工具卡片没拿到名字时用）。"""
    steering.request_tool_cancel("s1", "")

    assert steering.take_tool_cancel("s1", "run_command") is True


# --------------------------------------------------------------------------- #
# 3. 工具包装层
# --------------------------------------------------------------------------- #
@pytest.fixture()
def probe_tool() -> object:
    """登记一个可免确认的探针工具并返回它，用例结束后从注册表摘掉。

    用 READ 类型而不是 WRITE：本组测试关心的是"插话/取消有没有生效"，
    不该顺带触发确认弹窗（弹窗走 interrupt，测试里跑不通）。
    """
    probe_policy = Policy(tool="__steer_probe__", kind=Kind.READ, default_level=Level.ALLOW)
    policy_mod.register(probe_policy)
    calls: list[str] = []

    @make_tool(probe_policy, lambda path: Action(tool=probe_policy.tool, kind=Kind.READ, target=path))
    def __steer_probe__(path: str) -> str:
        """探针工具：记录被调用次数并返回固定文本。

        函数名必须与登记的 Policy.tool 完全一致：wrapper 内部用 `func.__name__`
        去 `POLICIES` 里查策略，名字对不上会直接被 guard 判成"未登记策略"。
        """
        calls.append(path)
        return f"OK: 读了 {path}"

    __steer_probe__.calls = calls  # type: ignore[attr-defined]
    try:
        yield __steer_probe__
    finally:
        policy_mod.POLICIES.pop(probe_policy.tool, None)
        tool_session.set_session_id("")


def test_wrapper_skips_execution_when_cancelled(probe_tool: object) -> None:
    """登记取消后，工具函数根本不该被调用，返回文案要明确"不要重试"。"""
    tool_session.set_session_id("s1")
    steering.request_tool_cancel("s1", "__steer_probe__")

    result = probe_tool("a.txt")  # type: ignore[operator]

    assert probe_tool.calls == []  # type: ignore[attr-defined]
    assert "取消" in result
    assert "不要重试" in result


def test_wrapper_appends_steer_notes_to_the_result(probe_tool: object) -> None:
    """插话必须出现在工具返回值里——这是模型唯一能看到它的地方。"""
    tool_session.set_session_id("s1")
    item = steering.enqueue("s1", "别动 test 目录")

    result = probe_tool("b.txt")  # type: ignore[operator]

    # 工具本身照常执行
    assert probe_tool.calls == ["b.txt"]  # type: ignore[attr-defined]
    assert result.startswith("OK: 读了 b.txt")
    # 插话块在末尾，带固定前缀与"不要当新任务"的说明
    assert f"{steering.INJECT_PREFIX} 别动 test 目录" in result
    assert steering.INJECT_HINT in result
    # 并且已经记账，控制器下一次 on_tool_end 就能上报给前端
    assert [it.steer_id for it in steering.take_injected("s1")] == [item.steer_id]


# --------------------------------------------------------------------------- #
# 4. HTTP 端点
# --------------------------------------------------------------------------- #
@pytest.fixture()
def active_run():
    """伪造"会话 s1 正有一条流在跑"的现场，用例结束后原样恢复全局表。"""
    sess = chat.SessionState(session_id="s1")
    stop_event = chat._register_run("s1")
    chat._SESSIONS["s1"] = sess
    try:
        yield sess
    finally:
        chat._SESSIONS.pop("s1", None)
        chat._unregister_run("s1", stop_event)


def test_steer_endpoint_accepts_while_a_run_is_active(active_run) -> None:
    """有活跃流时接收插话，并回 queued=True（让前端显示"排队中"）。"""
    resp = client.post("/api/chat/s1/steer", json={"content": "只改 src 目录"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] is True
    assert body["pending"] == 1
    assert body["steer_id"]
    assert [item.content for item in steering.drain("s1")] == ["只改 src 目录"]


def test_steer_endpoint_rejects_when_no_run_is_active() -> None:
    """没有活跃流时 409：这句话应该走 /chat/stream，不能默默进一个没人消费的队列。"""
    resp = client.post("/api/chat/s1/steer", json={"content": "你好"})

    assert resp.status_code == 409
    assert "没有正在执行" in resp.json()["detail"]


def test_steer_endpoint_respects_the_switch(active_run, monkeypatch: pytest.MonkeyPatch) -> None:
    """设置里关掉插话后返回 400，前端据此退化为"执行期间禁用输入框"。"""
    monkeypatch.setattr(steering, "enabled", lambda: False)

    resp = client.post("/api/chat/s1/steer", json={"content": "你好"})

    assert resp.status_code == 400
    assert "agent.steering_enabled" in resp.json()["detail"]
    assert steering.pending_count("s1") == 0


def test_tool_cancel_endpoint_registers_the_marker(active_run) -> None:
    """工具还没开始时可以取消：标记写进队列，等工具启动时命中。"""
    resp = client.post("/api/chat/s1/tool-cancel", json={"tool": "write_file"})

    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True
    assert steering.has_tool_cancel("s1") is True
    assert steering.take_tool_cancel("s1", "write_file") is True


def test_tool_cancel_endpoint_refuses_while_a_tool_is_running(active_run) -> None:
    """工具已经开始执行：如实返回 409 并建议改用「终止」，不假装取消成功。"""
    active_run.running_tool = "run_command"

    resp = client.post("/api/chat/s1/tool-cancel", json={"tool": "run_command"})

    assert resp.status_code == 409
    assert "无法中途取消" in resp.json()["detail"]
    assert steering.has_tool_cancel("s1") is False


def test_tool_cancel_endpoint_requires_an_active_run() -> None:
    """没有活跃流时 409：没有工具可取消。"""
    resp = client.post("/api/chat/s1/tool-cancel", json={})

    assert resp.status_code == 409
