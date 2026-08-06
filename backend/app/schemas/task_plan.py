# app/schemas/task_plan.py
"""复杂任务拆分的请求/响应模型（TASK）。

为什么单独一个 schema 文件：
    规划结果会被三个地方共用——LLM 输出解析、SSE `plan` 事件、`done.subtasks` 回放。
    三处各写一份 dict 结构，字段迟早会漂；用模型钉住字段名，改动会被类型检查与测试拦住。

字段命名与 doc/26 §7 冻结的协议一致（`id/title/description/files/depends_on/verify`），
运行期状态（`status/summary`）**不进 plan 事件**，只在 task_end 与 done 里出现。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：Any 标注清理后的原始 dict
from typing import Any

# 数据校验：BaseModel 基类 + field_validator 做字段清洗
from pydantic import BaseModel, Field, field_validator


# 子任务允许的状态：与前端 Todo 的样式一一对应
SUB_TASK_STATUSES: tuple[str, ...] = (
    "pending",       # 还没开始
    "running",       # 正在执行
    "success",       # 执行且（若配置了）校验通过
    "failed",        # 执行失败（模型报错 / 步数耗尽）
    "verify_failed", # 执行完成但校验命令失败
)


class SubTask(BaseModel):
    """一个子任务。"""

    # 序号：从 1 开始，前端 Todo 与 depends_on 都用它
    id: int = Field(..., ge=1)
    # 一句话标题（Todo 列表展示）
    title: str
    # 给执行用的明确目标 + 完成标准
    description: str = ""
    # 预计**写入**的文件（工作区相对路径或绝对路径）；冲突检测的依据
    files: list[str] = Field(default_factory=list)
    # 依赖的子任务 id（首版按拓扑排序后串行执行）
    depends_on: list[int] = Field(default_factory=list)
    # 该子任务自己的校验命令；为空则回落到全局 `task.verify_command`
    verify: str = ""
    # 运行期状态（默认 pending）
    status: str = "pending"
    # 执行结果摘要（task_end 与汇总用）
    summary: str = ""

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        """标题压成一行并限长：Todo 一行放不下长标题，也避免模型把整段描述塞进标题。"""
        text = " ".join(str(value or "").split())
        return text[:80] or "未命名子任务"

    @field_validator("files")
    @classmethod
    def _clean_files(cls, value: list[str]) -> list[str]:
        """文件列表去空、去重（保留顺序）：重复项会让冲突检测产生假冲突。"""
        seen: set[str] = set()
        result: list[str] = []
        for item in value or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @field_validator("depends_on")
    @classmethod
    def _clean_deps(cls, value: list[int]) -> list[int]:
        """依赖去重并排序（稳定排序让拓扑排序结果可预测）。"""
        return sorted({int(v) for v in value or [] if str(v).isdigit() or isinstance(v, int)})

    def to_event(self) -> dict[str, Any]:
        """转成 `plan` / `task_end` 事件里的形状（不含运行期状态以外的私有字段）。"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "files": list(self.files),
            "depends_on": list(self.depends_on),
        }

    def to_result(self) -> dict[str, Any]:
        """转成 `done.subtasks` 里的形状（含状态与摘要，供历史回放）。"""
        return {
            **self.to_event(),
            "status": self.status,
            "summary": self.summary,
        }


class TaskPlan(BaseModel):
    """一次拆分的完整结果。"""

    # simple / complex：simple 表示"不该拆"，直接走原链路
    complexity: str = "simple"
    # 判定理由（写进日志与轨迹，排查"为什么没拆"时有用）
    reason: str = ""
    # 子任务列表（complex 时至少 2 个）
    subtasks: list[SubTask] = Field(default_factory=list)

    @property
    def is_complex(self) -> bool:
        """是否值得按计划执行（complex 且真的拆出了多个子任务）。"""
        return self.complexity == "complex" and len(self.subtasks) >= 2

    def to_event(self) -> dict[str, Any]:
        """`plan` 事件的负载。"""
        return {
            "reason": self.reason,
            "subtasks": [task.to_event() for task in self.subtasks],
        }


class PlanDecision(BaseModel):
    """强度分析 + 拆分的 LLM 原始输出（宽松校验，解析失败时降级为 simple）。"""

    complexity: str = "simple"
    reason: str = ""
    subtasks: list[SubTask] = Field(default_factory=list)
