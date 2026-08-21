# app/services/task_planner.py
"""复杂任务拆分：强度判定、拆分、汇总、校验（TASK）。

三个模型调用都走**裸模型**（不挂工具）：
    规划与汇总只需要"会写字"，挂上工具反而会让它跑去执行、把计划带偏
    （与 `\\doc` 检索后做一次性回答用的是同一个理由，见 llm/state.get_model 的说明）。

成本控制（重要）：
    拆分本身要多花一次 LLM 调用。为了不让"你好"这种请求也付这份钱，
    `looks_complex()` 先用启发式筛一遍——明显简单的请求直接走原链路，
    一次模型调用都不多花。只有"看起来可能复杂"的才去问模型。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：正则（剥 JSON 代码围栏）、日志、子进程（跑校验命令）
import json
import logging
import re
import subprocess
from pathlib import Path
# 标准库：Any 标注
from typing import Any

# 项目内：子任务模型
from app.schemas.task_plan import PlanDecision, SubTask, TaskPlan

# 本模块专用 logger
log = logging.getLogger("task")

# 简单请求的启发式阈值：短消息 + 无复杂信号 → 直接判定 simple
_SHORT_MESSAGE = 40

# 复杂信号词：出现任一就进入"问模型"的候选集合。
# 这些词覆盖了中文里"要多步/要批量/要产出"的典型表达，宁多勿少——
# 误判成 complex 只是多花一次调用，误判成 simple 则等于功能没生效。
_COMPLEX_MARKERS: tuple[str, ...] = (
    "然后", "接着", "再", "并且", "同时", "分别", "依次", "逐个", "批量",
    "所有", "全部", "整个", "每个", "各个", "全套",
    "报告", "文档", "总结", "整理", "重构", "迁移", "排查", "修复",
    "实现", "开发", "设计", "搭建", "接入", "验证", "测试",
    "第一步", "第二步", "第一", "第二", "其次", "最后", "1.", "2.", "①", "②",
)

# 校验命令最长跑多久（秒）：卡死的命令不能把整轮对话拖住
VERIFY_TIMEOUT = 180

# 校验输出最多保留多少字符（会作为"报错反馈"塞回模型）
_VERIFY_OUTPUT_CHARS = 2000


def looks_complex(message: str) -> bool:
    """启发式判断"这个请求值不值得问模型要不要拆"。

    判定为 True **不代表**一定拆——只是允许进入 LLM 判定；
    模型仍可能回答 simple（例如"总结一下这段话"虽然命中"总结"，但只有一个动作）。

    :param message: 用户原始输入
    :return: True=值得进一步判定
    """
    text = (message or "").strip()
    if not text:
        return False
    # 多行/带编号的输入几乎一定是多步需求
    if "\n" in text:
        return True
    if len(text) >= _SHORT_MESSAGE:
        return True
    return any(marker in text for marker in _COMPLEX_MARKERS)


def build_plan_prompt(message: str, max_subtasks: int) -> str:
    """拼"强度判定 + 拆分"的提示词。

    :param message: 用户需求
    :param max_subtasks: 子任务数量上限
    :return: 完整提示词
    """
    return f"""你是任务规划器。判断下面这个需求能不能一步做完，如果能，就标记为 simple；
如果不能，就把它拆成有序子任务。

用户需求：
\"\"\"
{message}
\"\"\"

判定标准：
- simple：一次回答/一次工具调用就能完成（问答、解释、读一个文件、查一条命令）。
- complex：需要多步、要改多个文件、要产出报告/文档、要批量处理。
  例："扫描整个项目统计 TODO 并写报告"、"把 A 改成 B 然后跑测试"。

拆分要求：
1. 子任务 2~{max_subtasks} 个，每个都能独立执行、有明确完成标准；
2. 按执行顺序排列，id 从 1 开始；
3. `files` 只列**预计要写入**的文件（工作区相对路径；只读文件不要列）；
4. `depends_on` 写依赖的子任务 id，没有就留空数组；
5. `verify` 可留空（留空表示用全局校验命令）。

只输出 JSON，不要任何解释文字：
{{
  "complexity": "simple" 或 "complex",
  "reason": "一句话说明判断理由",
  "subtasks": [
    {{"id": 1, "title": "短标题", "description": "做什么、做完的标准", "files": ["a.py"], "depends_on": []}}
  ]
}}"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出第一个 JSON 对象。

    模型经常不听话：加 ```json 围栏、前面写一段"好的，我来分析"、结尾加解释。
    直接 `json.loads` 会失败，所以先剥围栏再取首尾花括号。

    :param text: 模型原始输出
    :return: 解析出的字典；失败返回 None
    """
    raw = (text or "").strip()
    if not raw:
        return None
    # 剥掉 ```json ... ``` 或 ``` ... ```
    fence = re.match(r"^```[a-zA-Z]*\s*(.+?)\s*```$", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_plan(text: str, max_subtasks: int) -> TaskPlan | None:
    """把模型输出解析成计划；不合法时返回 None（调用方退回单 agent）。

    为什么宁可返回 None 也不"尽力修补"：拆错的任务比不拆更糟——
    用户会看到一串跑偏的子任务，还得多等好几轮。解析不出来就当简单任务处理。

    :param text: 模型输出
    :param max_subtasks: 子任务上限（超出部分截断）
    :return: TaskPlan 或 None
    """
    payload = _extract_json(text)
    if payload is None:
        return None
    try:
        decision = PlanDecision.model_validate(payload)
    except Exception:
        log.warning("任务计划解析失败，退回单 agent", exc_info=True)
        return None

    if decision.complexity.strip().lower() != "complex":
        return TaskPlan(complexity="simple", reason=decision.reason or "模型判定为简单任务")

    # 只保留前 N 个，并重新编号保证 id 连续（模型偶尔会跳号）
    tasks: list[SubTask] = []
    for index, task in enumerate(decision.subtasks[:max_subtasks], start=1):
        tasks.append(task.model_copy(update={"id": index}))
    # 依赖里指向被截掉/不存在的 id 要去掉，否则拓扑排序会永远等不到
    valid = {task.id for task in tasks}
    for task in tasks:
        task.depends_on = [dep for dep in task.depends_on if dep in valid and dep != task.id]

    if len(tasks) < 2:
        # 只拆出一个子任务等于没拆，多花的调用与展示都不值得
        return TaskPlan(complexity="simple", reason="拆分结果不足 2 个子任务")

    return TaskPlan(complexity="complex", reason=decision.reason, subtasks=tasks)


async def make_plan(message: str, *, max_subtasks: int = 5) -> TaskPlan | None:
    """判定 + 拆分；任何异常都返回 None（退回单 agent）。

    :param message: 用户需求
    :param max_subtasks: 子任务上限
    :return: TaskPlan 或 None
    """
    if not looks_complex(message):
        return TaskPlan(complexity="simple", reason="启发式判定为简单请求")

    # 项目内：延迟导入，避免服务层导入期就把模型层拉起来
    from langchain_core.messages import HumanMessage

    from app.llm.state import get_model

    try:
        model = get_model()
        response = await model.ainvoke([HumanMessage(content=build_plan_prompt(message, max_subtasks))])
    except Exception:
        log.warning("任务拆分调用失败，退回单 agent", exc_info=True)
        return None

    content = getattr(response, "content", "")
    text = content if isinstance(content, str) else str(content)
    plan = parse_plan(text, max_subtasks)
    if plan is None:
        log.info("任务计划解析失败，本轮按单 agent 执行")
    elif plan.is_complex:
        log.info("拆分为 %d 个子任务：%s", len(plan.subtasks), plan.reason)
    return plan


def build_subtask_prompt(task: SubTask, index: int, total: int) -> str:
    """拼某个子任务的执行指令。

    为什么强调"只做这一个"：模型看到的是完整会话历史（同一 thread），
    不强调的话它会顺手把后面几步也做了，导致后续子任务重复劳动。

    :param task: 子任务
    :param index: 第几个（1 起）
    :param total: 总数
    :return: 提示词
    """
    files = "、".join(task.files) if task.files else "（无预计写入文件）"
    return f"""【子任务 {index}/{total}】{task.title}

目标：{task.description or task.title}
预计需要写入：{files}

要求：
1. 只完成这个子任务，不要提前做后面的子任务；
2. 需要写文件时按普通规则操作（会弹确认）；
3. 完成后用一两句话说明你做了什么、结果如何，不要复述计划。"""


def build_summary_prompt(original: str, plan: TaskPlan) -> str:
    """拼汇总提示词。

    :param original: 用户最初的需求
    :param plan: 已执行完的计划（子任务带 status/summary）
    :return: 提示词
    """
    lines: list[str] = []
    for task in plan.subtasks:
        status = {"success": "完成", "failed": "失败", "verify_failed": "校验未通过"}.get(task.status, task.status)
        lines.append(f"{task.id}. {task.title} —— {status}：{task.summary or '（无说明）'}")
    return f"""用户最初的需求：
\"\"\"
{original}
\"\"\"

我把它拆成了 {len(plan.subtasks)} 个子任务并逐个执行，结果如下：
{chr(10).join(lines)}

请把这些结果整合成给用户的**最终回答**：
1. 直接回答问题 / 说明做了什么，不要复述"我拆成了几个子任务"这种过程描述；
2. 失败或校验未通过的部分要如实说明，并给出建议；
3. 涉及改动的文件要写清路径；不要编造没做过的事。"""


async def summarize(original: str, plan: TaskPlan) -> str:
    """调用模型汇总；失败时用机械拼接兜底（绝不返回空回答）。

    :param original: 用户最初需求
    :param plan: 已执行完的计划
    :return: 汇总文本
    """
    # 项目内：延迟导入
    from langchain_core.messages import HumanMessage

    from app.llm.state import get_model

    try:
        model = get_model()
        response = await model.ainvoke([HumanMessage(content=build_summary_prompt(original, plan))])
        content = getattr(response, "content", "")
        text = content if isinstance(content, str) else str(content)
        if text.strip():
            return text.strip()
    except Exception:
        log.warning("汇总调用失败，使用机械拼接", exc_info=True)

    # 兜底：把各子任务结果拼起来。比"汇总失败，请重试"对用户有用得多
    lines = ["各子任务结果："]
    for task in plan.subtasks:
        lines.append(f"- {task.title}（{task.status}）：{task.summary or '无说明'}")
    return "\n".join(lines)


def build_replan_prompt(original: str, plan: TaskPlan, failed: SubTask, failure_note: str,
                        max_subtasks: int) -> str:
    """拼"重新规划"提示词（TASK Phase 2 §5.2）。

    为什么要重发**完整**计划而不是"补一个子任务"：
        失败往往意味着原来的切法是错的（例如"先改接口再改调用方"应该合成一步）。
        让模型看到全貌、重新给一份完整列表，才可能把已完成的步骤吸收进去；
        只让它补一步，等于逼它在错误的地基上继续盖。

    :param original: 用户最初的需求
    :param plan: 当前计划（子任务带 status/summary，成功的不再重跑）
    :param failed: 失败的那个子任务
    :param failure_note: 失败原因（校验输出或错误摘要）
    :param max_subtasks: 新计划的子任务上限
    :return: 提示词
    """
    lines: list[str] = []
    for task in plan.subtasks:
        mark = {"success": "已完成", "failed": "失败", "verify_failed": "校验未通过"}.get(task.status, "未开始")
        files = "、".join(task.files) if task.files else "（无）"
        lines.append(f"{task.id}. [{mark}] {task.title} —— 预计写入：{files}")

    return f"""用户最初的需求：
\"\"\"
{original}
\"\"\"

当前计划与执行情况：
{chr(10).join(lines)}

子任务 {failed.id}「{failed.title}」没有成功，原因：
\"\"\"
{failure_note or "（无输出）"}
\"\"\"

请重新给出一份**完整**的子任务列表（最多 {max_subtasks} 个），要求：
1. 已经成功的子任务不要再让它重复执行——把它们的工作视为已完成，新列表里只保留**还需要做**的部分；
2. 针对上面的失败原因调整切分方式（例如把耦合太紧的两步合成一步、把校验失败的那步补上前置修复）；
3. 每个子任务仍要给出 id（从 1 连续编号）、title、description、files（预计写入的绝对路径）、depends_on；
4. 只输出 JSON，不要解释。

输出格式：
{{"complexity": "complex", "reason": "重新规划的原因（一句话）", "subtasks": [
  {{"id": 1, "title": "...", "description": "...", "files": ["..."], "depends_on": []}}
]}}"""


async def make_replan(original: str, plan: TaskPlan, failed: SubTask, failure_note: str,
                      *, max_subtasks: int = 5) -> TaskPlan | None:
    """让模型针对失败重新规划；失败或解析不出来时返回 None（保持原计划）。

    :param original: 用户最初的需求
    :param plan: 当前计划
    :param failed: 失败的子任务
    :param failure_note: 失败原因
    :param max_subtasks: 新计划上限
    :return: 新计划（只含还需要做的子任务）或 None
    """
    # 项目内：延迟导入，避免服务层导入期就把模型层拉起来
    from langchain_core.messages import HumanMessage

    from app.llm.state import get_model

    try:
        model = get_model()
        prompt = build_replan_prompt(original, plan, failed, failure_note, max_subtasks)
        response = await model.ainvoke([HumanMessage(content=prompt)])
    except Exception:
        log.warning("重新规划调用失败，保持原计划", exc_info=True)
        return None

    content = getattr(response, "content", "")
    text = content if isinstance(content, str) else str(content)
    new_plan = parse_plan(text, max_subtasks)
    if new_plan is None or not new_plan.is_complex:
        # 模型认为"剩下的不值得再拆"时也返回 None：调用方保持原计划继续跑剩余子任务
        log.info("重新规划未给出新计划，保持原计划")
        return None
    log.info("重新规划得到 %d 个子任务：%s", len(new_plan.subtasks), new_plan.reason)
    return new_plan


def run_verify(command: str, cwd: Path | None, timeout: int = VERIFY_TIMEOUT) -> tuple[bool, str]:
    """执行一条校验命令。

    为什么不走 `run_command` 工具：那条链路会弹确认弹窗，而校验是**用户自己在设置里配的**
    命令（不是模型生成的），每个子任务都弹一次会把流程切碎。信任级别与
    `verify.commands` 一致，因此直接执行。

    :param command: 命令（交给 shell 执行）
    :param cwd: 工作目录（通常是当前工作区根目录）
    :param timeout: 超时秒数
    :return: (是否通过, 输出摘要)
    """
    text = (command or "").strip()
    if not text:
        return True, ""
    try:
        completed = subprocess.run(  # noqa: S602  用户配置的命令，需要 shell 语义（管道/&&）
            text,
            cwd=str(cwd) if cwd else None,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"校验命令超时（>{timeout}s）：{text}"
    except Exception as exc:  # noqa: BLE001  命令写错/工作目录不存在
        return False, f"校验命令无法执行：{exc}"

    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if len(output) > _VERIFY_OUTPUT_CHARS:
        output = output[-_VERIFY_OUTPUT_CHARS:]
    if completed.returncode == 0:
        return True, output
    return False, output or f"命令退出码 {completed.returncode}"
