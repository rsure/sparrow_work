# app/controllers/llm_controller.py
"""模型接入接口：列出可用供应商/模型、连通性测试。

对应 doc/21 ARCH-1 §1.5.B/C：
    - 自定义 OpenAI 兼容端点可以有多个并存，各端点密钥独立；
    - 设置页的「测试连接」按钮需要能区分「密钥错误 / 模型名不存在 / 网络不通」。

安全红线：本模块所有响应都**不含密钥明文**，probe 只拿钥匙串里的密钥去发请求，
不回传、不打日志（见 doc/21 ARCH-2 §2.4）。
"""

# 让类型注解延迟求值（PEP 563)
from __future__ import annotations

# Web 框架：APIRouter 建路由
from fastapi import APIRouter

# 数据校验：BaseModel 定义请求体，Field 声明默认值与说明（会出现在 /docs）
from pydantic import BaseModel, Field

# 项目内：统一响应外壳
from app.schemas.common import ApiResponse
# 项目内：模型注册表（列出供应商与模型）
from app.llm import registry
# 项目内：模型工厂（连通性测试）
from app.llm import factory


# 本模块路由：挂在 /api/llm 前缀下
router = APIRouter(prefix="/llm", tags=["llm"])


class LlmProbeRequest(BaseModel):
    """连通性测试的请求体（POST /api/llm/probe）。"""

    # 要测的供应商 id，如 "deepseek" 或 "custom-myapi"
    provider: str = Field(..., min_length=1, description="要测试的供应商 id，如 deepseek / openai / custom-myapi")
    # 要测的模型名；为空表示用该供应商的默认模型
    model: str | None = Field(None, description="要测试的模型名；留空则用该供应商的默认模型")
    # 要测的接口地址；为空则用设置里的 llm.base_url
    base_url: str | None = Field(None, description="要测试的接口地址；留空则用设置里配置的地址")


@router.get("/providers", summary="列出全部可用的模型供应商与模型清单")
async def list_providers() -> ApiResponse[dict]:
    """返回内置供应商 + 用户自定义端点，以及各自的模型清单与能力元数据。

    模型清单 = 内置 ∪ 自定义（同名时自定义覆盖内置），
    供设置页的下拉框直接渲染，并显示每个模型的上下文窗口与是否支持工具。

    :return: {"providers": [{id,label,base_url,requires_key,is_custom,models:[...]}]}
    """
    providers = []
    for provider in registry.list_providers():
        # 自定义端点的模型只可能来自用户自定义配置；查不到就返回空数组而不是报错
        try:
            models = [m.to_dict() for m in registry.list_models(provider.id)]
        except KeyError:
            models = []
        providers.append({
            "id": provider.id,
            "label": provider.label,
            "base_url": provider.base_url,
            "requires_key": provider.requires_key,
            "is_custom": provider.is_custom,
            "models": models,
        })
    return ApiResponse(code=0, message="ok", data={"providers": providers})


@router.post("/probe", summary="测试某个模型配置是否可用")
async def probe(req: LlmProbeRequest) -> ApiResponse[dict]:
    """发一次最小请求，验证密钥、模型名与网络连通性。

    返回里的 ``error_kind`` 是给设置页用来给不同提示的关键：
        - ``secret``：密钥没配或不对 —— 提示"请检查 API Key"
        - ``model``：该供应商下没有这个模型名 —— 提示"请选择下拉框里的模型"
        - ``network``：网络不通/ 服务不可达 —— 提示"检查网络或代理设置"

    :param req: 见 LlmProbeRequest
    :return: {"ok": 是否可用, "latency_ms": 耗时, "error": 失败原因, "error_kind": 失败分类}
    """
    result = factory.probe_model(req.provider, req.model, req.base_url)
    # 刻意只回错误文案，不回任何密钥内容；latency 与分类用于前端展示
    return ApiResponse(code=0, message="ok", data=result)