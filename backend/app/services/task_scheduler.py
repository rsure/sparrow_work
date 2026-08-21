# app/services/task_scheduler.py
"""子任务调度：冲突检测、冲突处置、分道、拓扑排序（TASK §5.3 L1/L3）。

为什么这些逻辑不能交给模型：
    模型给的 `files` 是"它觉得会改哪些文件"，两两交集检测是纯机械判断，
    交给代码做才可复现、可测试。让模型自己"合并冲突子任务"则完全不可控。

本模块全是纯函数（不碰数据库、不调模型），因此可以钉大量边界用例：
    - 无文件声明的子任务不参与冲突（它们不写文件）
    - 路径 `a.py` 与 `./a.py`、大小写差异要视为同一文件
    - 依赖成环时必须退化而不是死循环
    - 分道要取**传递闭包**：a↔b、b↔c 之后 a、b、c 必须同道
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：路径规范化（不同写法指向同一文件时要能识别）
import os

# 项目内：子任务模型
from app.schemas.task_plan import SubTask


# 冲突处置策略：与 doc/26 §5.3 的三策略一致
CONFLICT_POLICIES: tuple[str, ...] = ("merge", "serialize", "block")


def _key(path: str) -> str:
    """把文件路径规范成"可比较"的键。

    `D:/W/a.py`、`D:\\W\\a.py`、`./a.py` 在 Windows 上可能指向同一文件，
    比较前必须统一，否则冲突检测会漏判（漏判的后果是两个子任务互相覆盖）。

    :param path: 原始路径
    :return: 规范化后的键（小写、统一分隔符）
    """
    return os.path.normcase(os.path.normpath(str(path).strip()))


def find_conflict_groups(subtasks: list[SubTask]) -> list[list[int]]:
    """找出"写同一批文件"的子任务分组（并查集）。

    :param subtasks: 子任务列表
    :return: 分组列表，每组是子任务下标（长度 >= 2）；无冲突时返回空列表
    """
    # 文件 → 第一个声明它的子任务下标
    owner: dict[str, int] = {}
    # 并查集：parent[i] = i 表示自成一派
    parent = list(range(len(subtasks)))

    def find(x: int) -> int:
        """找根（带路径压缩）。"""
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        """合并两棵树。"""
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for index, task in enumerate(subtasks):
        for raw in task.files:
            key = _key(raw)
            if key in owner:
                union(owner[key], index)
            else:
                owner[key] = index

    groups: dict[int, list[int]] = {}
    for index in range(len(subtasks)):
        groups.setdefault(find(index), []).append(index)
    # 只保留"真的有两个以上子任务"的组
    return [sorted(members) for members in groups.values() if len(members) > 1]


def merge_group(subtasks: list[SubTask], members: list[int]) -> SubTask:
    """把一个冲突组合并成一个子任务。

    为什么默认策略是合并而不是串行：同一个文件被两个子任务先后整文件回写，
    极易丢掉前一个的修改；"一次改完"在语义上最安全，也少一轮往返。

    :param subtasks: 原列表
    :param members: 组内下标（升序）
    :return: 合并后的子任务（沿用组内第一个的 id）
    """
    head = subtasks[members[0]]
    parts: list[str] = []
    files: list[str] = []
    deps: set[int] = set()
    verify = head.verify

    for index in members:
        task = subtasks[index]
        if task.description:
            parts.append(f"{len(parts) + 1}. {task.title}：{task.description}")
        else:
            parts.append(f"{len(parts) + 1}. {task.title}")
        files.extend(task.files)
        deps.update(task.depends_on)
        # 合并后取第一个非空校验命令：多段改动一起校验才有意义，取一个够用
        verify = verify or task.verify

    return SubTask(
        id=head.id,
        title=f"{head.title}（合并 {len(members)} 项）",
        description="\n".join(parts),
        files=files,
        # 组内的互相依赖在合并后不再有意义，必须剔除，否则会自依赖
        depends_on=sorted(dep for dep in deps if dep not in {subtasks[i].id for i in members}),
        verify=verify,
    )


def apply_conflict_policy(
    subtasks: list[SubTask],
    policy: str,
) -> tuple[list[SubTask], list[list[int]], bool]:
    """按策略处置冲突。

    :param subtasks: 原计划
    :param policy: merge / serialize / block
    :return: (处置后的子任务, 冲突分组（原始下标）, 是否需要人工介入)
             第三项为 True 时调用方应**放弃自动执行**（block 策略），交回单 agent 链路。
    """
    groups = find_conflict_groups(subtasks)
    if not groups:
        return subtasks, [], False

    normalized = policy if policy in CONFLICT_POLICIES else "merge"

    if normalized == "block":
        # 不自动执行：调用方会退回单 agent，并在思考提示里说明原因
        return subtasks, groups, True

    if normalized == "serialize":
        # 保留拆分，但让组内后者依赖前者：串行执行 + 每步校验，能定位到是哪一步改坏的
        result = [task.model_copy(deep=True) for task in subtasks]
        for members in groups:
            for previous, current in zip(members, members[1:]):
                deps = set(result[current].depends_on)
                deps.add(result[previous].id)
                result[current].depends_on = sorted(deps)
        return result, groups, False

    # merge（默认）：从后往前合并，避免下标错位
    result = [task.model_copy(deep=True) for task in subtasks]
    for members in sorted(groups, key=lambda group: group[0], reverse=True):
        merged = merge_group(result, members)
        # 用合并结果替换组内第一个，删掉其余
        result[members[0]] = merged
        for index in reversed(members[1:]):
            result.pop(index)
    return result, groups, False


def build_lanes(subtasks: list[SubTask]) -> list[list[SubTask]]:
    """把子任务按"会不会互相踩脚"分成若干条车道（TASK Phase 2 §5.3 L3）。

    为什么需要车道：并行执行的前提是"两条道上的子任务绝不碰同一个文件"。
    这里用并查集做闭包——A 与 B 都写 `a.py` 就同道，B 与 C 都写 `b.py` 则 A、B、C 同道
    （**传递闭包**：只两两比较是不够的，`a.py`↔`b.py`↔`c.py` 会连成一条链）。

    依赖关系也会把两个子任务拉进同一条道：跨道的依赖在并行下无法表达
    （车道之间没有先后约束），所以 doc/26 §5.3 明确"跨 lane 的 depends_on 退化为同 lane"。

    车道之间**没有顺序约束**（可以并行）；车道内部靠 `order_subtasks` 保证依赖顺序。

    :param subtasks: 已按冲突策略处置过的子任务列表
    :return: 车道列表，每道是排好序的子任务；所有子任务恰好出现一次。
             顺序确定（按各道里最小原始下标排序），因此结果可复现、可测试。
    """
    if not subtasks:
        return []

    by_id = {task.id: index for index, task in enumerate(subtasks)}
    parent = list(range(len(subtasks)))

    def find(x: int) -> int:
        """找根（带路径压缩）。"""
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        """合并两棵树（小的挂到大的下面，保持根尽量小，便于稳定排序）。"""
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra > rb:
            ra, rb = rb, ra
        parent[rb] = ra

    # ① 写同一文件 → 同道
    owner: dict[str, int] = {}
    for index, task in enumerate(subtasks):
        for raw in task.files:
            key = _key(raw)
            if key in owner:
                union(owner[key], index)
            else:
                owner[key] = index

    # ② 有依赖 → 同道（跨道依赖无法表达先后）
    for index, task in enumerate(subtasks):
        for dep in task.depends_on:
            other = by_id.get(dep)
            if other is not None and other != index:
                union(index, other)

    groups: dict[int, list[int]] = {}
    for index in range(len(subtasks)):
        groups.setdefault(find(index), []).append(index)

    # 根天然是组内最小下标（union 时总是保留较小根），所以按 dict 插入顺序即可稳定
    lanes: list[list[SubTask]] = []
    for members in groups.values():
        lanes.append(order_subtasks([subtasks[i] for i in members]))
    return lanes


def flatten_lanes(lanes: list[list[SubTask]]) -> list[SubTask]:
    """把车道按"道序 + 道内序"摊平成一维执行顺序。

    并发度为 1（默认）时用它：这时候车道只用来决定**谁挨着谁跑**——
    同一道里的子任务连着执行，上下文最连贯；等价于把提交顺序换成"按文件亲和度聚类"。

    :param lanes: `build_lanes` 的结果
    :return: 摊平后的子任务列表
    """
    return [task for lane in lanes for task in lane]


def lane_index(lanes: list[list[SubTask]]) -> dict[int, int]:
    """建立「子任务 id → 车道号」的索引，供执行期查锁与统计。

    键用 int 而不是 str：`SubTask.id` 本来就是整数，转成字符串会让调用方
    每次查表都得记得 `str(id)`，这类转换漏一次就是 KeyError。

    :param lanes: `build_lanes` 的结果
    :return: {子任务 id: 车道下标}
    """
    result: dict[int, int] = {}
    for index, lane in enumerate(lanes):
        for task in lane:
            result[task.id] = index
    return result


def order_subtasks(subtasks: list[SubTask]) -> list[SubTask]:
    """按 depends_on 做拓扑排序；有环时退化为原顺序。

    为什么有环也必须能跑：模型给出的依赖偶尔会成环（A 依赖 B、B 又依赖 A）。
    死循环或报错都会让整个任务失败，而"按列表顺序跑"至少能完成大部分工作。

    :param subtasks: 子任务列表
    :return: 排序后的列表（同一层级保持原顺序，结果可复现）
    """
    by_id = {task.id: task for task in subtasks}
    # 只保留指向本计划内子任务的依赖（外部 id 会让入度永远清不掉）
    indegree = {task.id: len([d for d in task.depends_on if d in by_id and d != task.id]) for task in subtasks}
    ready = [task.id for task in subtasks if indegree[task.id] == 0]
    ordered: list[SubTask] = []

    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for task in subtasks:
            if current in task.depends_on and task.id != current:
                indegree[task.id] -= 1
                if indegree[task.id] == 0:
                    ready.append(task.id)

    if len(ordered) != len(subtasks):
        # 有环：保留已完成的部分 + 剩余按原顺序补齐（不重复）
        done = {task.id for task in ordered}
        ordered.extend(task for task in subtasks if task.id not in done)
    return ordered
