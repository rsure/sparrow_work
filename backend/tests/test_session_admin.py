"""UX-4 会话管理（搜索 / 重命名）与 UX-5 用量聚合的回归测试。

这些能力看起来"只是界面功能"，但错法都很隐蔽：
    - 搜索若在应用层过滤，分页与排序会乱；这里断言过滤下推到 SQL 后仍只返回命中的会话；
    - 重命名若顺手刷新 updated_at，会话列表顺序会被改名打乱；
    - 用量聚合若不按"当轮模型"算单价，一换模型成本就全错。

用例自己创建会话，跑完由 conftest 的 autouse fixture 删掉（不会污染开发者的真实记录）。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：生成不会撞车的会话 id
import uuid

# 项目内：被测试的三个服务
from app.services import chat_history_service as history
from app.services import usage_service


def _make_session(*, title_hint: str = "会话管理测试") -> str:
    """建一个会话并写一轮带用量的回答。

    :param title_hint: 第一条用户提问（会变成会话标题）
    :return: 会话 id
    """
    session_id = f"t{uuid.uuid4().hex[:12]}"
    history.append_user_message(session_id, title_hint, mode="agent")
    history.append_user_message(session_id, "再问一句：用量统计准吗", mode="agent")
    history.append_assistant_turn(
        session_id, "回答正文", mode="agent", finish_reason="done", elapsed=1.2,
        usage={"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
        model="deepseek/deepseek-chat",
    )
    return session_id


def test_search_by_title_and_content() -> None:
    """搜索要同时命中标题与消息正文，且不命中时返回空。"""
    marker = uuid.uuid4().hex[:8]
    session_id = _make_session(title_hint=f"标题含关键字-{marker}")

    by_title = history.list_sessions(limit=50, query=marker)
    assert [s["session_id"] for s in by_title] == [session_id]

    # 按"正文里出现过的词"也能搜到（标题里没有这个词）
    by_content = history.list_sessions(limit=50, query="用量统计准吗")
    assert session_id in [s["session_id"] for s in by_content]

    assert history.list_sessions(limit=50, query=f"绝对不存在的词{uuid.uuid4().hex}") == []


def test_search_escapes_like_wildcards() -> None:
    """用户输入 % 时不能被当成通配符（否则会把整库都搜出来）。"""
    session_id = _make_session(title_hint=f"通配符测试-{uuid.uuid4().hex[:6]}")

    # 单个 % 只有在真的有 % 的标题里才应命中；这里断言"没有把所有会话都返回"
    rows = history.list_sessions(limit=50, query="%")
    assert session_id not in [s["session_id"] for s in rows]


def test_rename_session_keeps_list_order() -> None:
    """重命名只改标题，不刷新 updated_at（否则改名会把会话顶到最前面）。"""
    session_id = _make_session()
    before = next(s for s in history.list_sessions(limit=50) if s["session_id"] == session_id)

    assert history.rename_session(session_id, "  改过的   标题  ") is True
    after = next(s for s in history.list_sessions(limit=50) if s["session_id"] == session_id)

    # 多空格被压成单空格
    assert after["title"] == "改过的 标题"
    assert after["updated_at"] == before["updated_at"], "改名不应影响列表排序依据"

    # 不存在的会话返回 False（不是抛异常）
    assert history.rename_session("not-exists-id", "x") is False


def test_usage_summary_sums_real_tokens() -> None:
    """会话累计 = 各轮 usage 之和；未知模型单价按 0，不猜数字。"""
    session_id = _make_session()

    summary = usage_service.session_summary(session_id)
    assert summary["turns"] == 1
    assert summary["input_tokens"] == 1000
    assert summary["output_tokens"] == 500
    assert summary["total_tokens"] == 1500
    # deepseek-chat 在注册表里是有单价的，所以成本应大于 0
    assert summary["cost"] > 0
    assert summary["currency"] == "CNY"
    assert summary["by_model"][0]["model"] == "deepseek/deepseek-chat"


def test_usage_summary_ignores_turns_without_usage() -> None:
    """没有用量记录的轮次不计入统计（老数据不估算）。"""
    session_id = f"t{uuid.uuid4().hex[:12]}"
    history.append_user_message(session_id, "没有用量的会话")
    history.append_assistant_turn(session_id, "旧数据回答", finish_reason="done")

    summary = usage_service.session_summary(session_id)
    assert summary["turns"] == 0
    assert summary["total_tokens"] == 0
    assert summary["cost"] == 0
