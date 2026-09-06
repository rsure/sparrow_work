"""pytest 全局夹具：本目录下所有用例共用。

目前只做一件事——测试结束后清掉用例期间新写入的对话记录。
原因：对话记录落在真实的 ./app.db（见 app/db/db_config.py 的 DATABASE_URL），
如果不管，跑完测试再去用桌面端，「最近会话」里会多出一堆 test 产生的会话。

注意这里是"删掉本次新增的"，而不是"清空整张表"：
开发者本地 app.db 里积攒的真实对话记录不该被测试顺手抹掉。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 测试框架：autouse fixture 不用每个用例显式声明
import pytest
# SQLAlchemy 查询构件：select 组查询
from sqlalchemy import select

# 项目内：会话上下文管理器与两个对话记录实体
from app.db.db_config import get_session
from app.entity.chat_record import ChatSession


def _all_session_ids() -> set[str]:
    """读出当前数据库里所有会话 id。

    :return: 会话 id 集合（空库时为空集合）
    """
    with get_session() as s:
        return set(s.scalars(select(ChatSession.session_id)).all())


@pytest.fixture(autouse=True)
def _purge_new_chat_records():
    """用例开始前记下已有会话，结束后把新出现的那些删掉（autouse：所有用例自动生效）。"""
    before = _all_session_ids()
    yield
    # 延迟导入服务层：避免在收集阶段就去连数据库
    from app.services.chat_history_service import delete_session

    for sid in _all_session_ids() - before:
        delete_session(sid)
