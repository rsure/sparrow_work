# app/services/usage_service.py
"""会话级 token / 成本聚合（UX-5 的数据侧）。

口径（与 doc/23 UX-5 一致）：
    - token 用 provider 返回的**真实 usage**（存在 chat_message.usage_json 上），不做估算；
    - 成本 = Σ(该轮 input × 输入单价 + 该轮 output × 输出单价) / 1e6；
    - 单价按**该轮记录下来的模型**取（同一会话可能换过模型），未知单价按 0 计。

为什么不做成"整库统计"：
    首版只服务右栏的「本会话」累计。跨会话汇总（按天/按模型）属于后续统计面板的范畴，
    现在做会把接口与索引都提前复杂化。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 项目内：历史消息里的用量行
from app.services import chat_history_service as history
# 项目内：模型注册表——按模型名查单价与上下文窗口
from app.llm import registry as llm_registry


def _price_of(model_label: str | None) -> tuple[float, float]:
    """按 `provider/model` 标签查出输入/输出单价（元 / 百万 token）。

    :param model_label: 形如 "deepseek/deepseek-chat"；为空或解析失败时返回 (0, 0)
    :return: (price_in, price_out)
    """
    if not model_label or "/" not in model_label:
        return 0.0, 0.0
    provider, _, model = model_label.partition("/")
    try:
        spec = llm_registry.resolve_model_spec(provider, model or None)
        return float(spec.price_in), float(spec.price_out)
    except Exception:
        # 模型被删掉 / 自定义端点没登记单价：按 0 计，不阻断面板展示
        return 0.0, 0.0


def session_summary(session_id: str) -> dict:
    """汇总一个会话的 token 与成本，供右栏「本会话」区块展示。

    :param session_id: 会话 id
    :return: 含 total/input/output tokens、cost、turns 与按模型拆分的明细
    """
    rows = history.usage_rows(session_id)
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cost = 0.0
    by_model: dict[str, dict] = {}

    for row in rows:
        usage = row.get("usage") or {}
        if not usage:
            # 没有真实用量（老数据 / 模型没返回 usage）：不计入 turns，也不估一个数出来
            continue
        row_input = int(usage.get("input_tokens") or 0)
        row_output = int(usage.get("output_tokens") or 0)
        row_total = int(usage.get("total_tokens") or (row_input + row_output))
        price_in, price_out = _price_of(row.get("model"))
        row_cost = (row_input * price_in + row_output * price_out) / 1_000_000

        input_tokens += row_input
        output_tokens += row_output
        total_tokens += row_total
        cost += row_cost

        key = row.get("model") or "unknown"
        bucket = by_model.setdefault(key, {"model": key, "turns": 0, "tokens": 0, "cost": 0.0})
        bucket["turns"] += 1
        bucket["tokens"] += row_total
        bucket["cost"] = round(bucket["cost"] + row_cost, 6)

    counted_turns = sum(1 for row in rows if row.get("usage"))
    return {
        "session_id": session_id,
        # 有用量记录的助手轮次数（老数据没有 usage，不计入）
        "turns": counted_turns,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        # 金额保留 4 位：一次短对话可能只有 0.0003 元，截到 2 位会显示成 0.00
        "cost": round(cost, 4),
        "currency": "CNY",
        "by_model": sorted(by_model.values(), key=lambda item: item["tokens"], reverse=True),
    }
