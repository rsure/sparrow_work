# app/services/memory_embedding.py
"""记忆向量化的两条通道（MEM 增强）：本地哈希（默认）与远端 embedding（可选）。

为什么要两套：
    本地哈希（`rag_store_service.vectorize`，字符 2-gram + L2 归一化）零依赖、零网络、
    零成本，对"一句话陈述"之间的字面重合已经够用；但它**不懂语义**——
    「用户偏好中文注释」与「注释一律写成中文」在它眼里几乎是两段无关文本。
    远端 embedding 能补上这一块，代价是要用户自己配一个 OpenAI 兼容的 `/embeddings` 端点。

三条刻意的设计选择（改动前请先读）：

1. **默认仍是本地**。远端需要密钥与网络，失败率天然更高；记忆是锦上添花，
   不能因为向量化服务挂了就让"保存记忆"整体失败。所以远端任何异常都**静默降级**回本地，
   只写一条 warning 日志。

2. **远端向量不做缓存持久化**。进程内一个几百条的小字典缓存（文本 → 向量）就够了：
   它只是省掉"同一句话反复请求"的浪费，进程重启后重算一次也很便宜。

3. **维度由响应决定，不写死**。`text-embedding-3-small` 是 1536 维、其它模型可能不同；
   写死一个常量只会在换模型时变成难查的 bug。维度记在 `memories.dim` 上，
   检索时"维度不符的旧向量"自然被跳过（见 `memory_service._cosine_matrix`），
   换后端后跑一次 `/api/memory/reindex` 即可全部重算。

换后端的操作顺序（写进 doc/25 §14）：改设置 → `POST /api/memory/reindex` → 观察检索效果。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：日志（降级时留痕）、线程锁（缓存字典在线程池里也会被写）
import logging
import threading
from typing import Any

# numpy：向量归一化（远端返回的向量不保证是单位向量）
import numpy as np

# 项目内：本地哈希向量化（默认后端，同时也是远端失败时的兜底）
from app.services.rag_store_service import VECTOR_DIM, vectorize

# 本模块专用 logger
log = logging.getLogger("memory.embedding")

# 本地后端标识（默认值）
BACKEND_LOCAL = "local"
# 远端后端标识：向 OpenAI 兼容的 /embeddings 端点发请求
BACKEND_REMOTE = "remote"

# 进程内向量缓存的条目上限。超过就整体清空——缓存只是省请求，不值得做 LRU 淘汰
_CACHE_LIMIT = 256
# 文本 → 单位向量 的进程内缓存
_CACHE: dict[str, np.ndarray] = {}
# 保护 _CACHE 的线程锁（抽取任务与检索都可能在不同线程触发向量化）
_LOCK = threading.Lock()

# 远端请求超时（秒）。记忆检索在对话主链路上，不能等太久
_TIMEOUT_SECONDS = 10.0


# --------------------------------------------------------------------------- #
# 1. 设置读取（与 memory_service 相同的兜底风格：读不到就走保守默认）
# --------------------------------------------------------------------------- #
def _setting(key: str, default: Any) -> Any:
    """读一个设置项，失败时返回默认值。

    :param key: 设置键
    :param default: 读不到时的兜底值
    :return: 设置值
    """
    try:
        # 项目内：延迟导入，避免本模块在导入期依赖设置库
        from app.services.settings_registry import get_setting

        value = get_setting(key)
        return default if value is None else value
    except Exception:
        return default


def backend() -> str:
    """当前配置的向量化后端：`local` 或 `remote`（非法值一律按 local）。"""
    value = str(_setting("memory.embedding_backend", BACKEND_LOCAL) or "").strip().lower()
    return BACKEND_REMOTE if value == BACKEND_REMOTE else BACKEND_LOCAL


def remote_model() -> str:
    """远端 embedding 的模型名（默认 `text-embedding-3-small`）。"""
    value = str(_setting("memory.embedding_model", "text-embedding-3-small") or "").strip()
    return value or "text-embedding-3-small"


def remote_provider() -> str:
    """用哪个模型供应商的地址与密钥调 embedding；空串表示"当前对话供应商"。"""
    return str(_setting("memory.embedding_provider", "") or "").strip()


def _resolve_remote_endpoint() -> tuple[str, str, str] | None:
    """解析出（供应商 id、接口基地址、API 密钥）；任何一项缺失都返回 None。

    密钥解析复用 `llm.factory._resolve_api_key` 的优先级（钥匙串 > .env），
    这样"用户在设置页填过一次密钥"就能同时用于对话与 embedding，不必填两遍。

    :return: (provider_id, base_url, api_key) 或 None（表示远端不可用）
    """
    provider_id = remote_provider()
    try:
        # 项目内：延迟导入，避免导入期就拉起整个模型层
        from app.llm import factory, registry

        if not provider_id:
            provider_id, _model = registry.current_provider_and_model()
        spec = registry.get_provider(provider_id)
        base_url = spec.base_url or ""
        api_key = factory._resolve_api_key(provider_id, None) or ""
    except Exception:
        log.debug("解析 embedding 供应商失败，回退本地向量化", exc_info=True)
        return None
    if not base_url or not api_key:
        return None
    # 用户也可能把地址配成 "…/v1/chat/completions" 这种完整路径，这里统一剥到基地址
    base = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return provider_id, base, api_key


def is_remote_available() -> bool:
    """远端后端是否真的可用（开关是 remote 且地址与密钥都齐了）。"""
    return backend() == BACKEND_REMOTE and _resolve_remote_endpoint() is not None


def describe() -> str:
    """给人看的一行描述（统计接口与设置页摘要用）。

    :return: `local` 或 `remote:<模型名>`；远端没配齐时返回 `local（远端未配置）`
    """
    if backend() == BACKEND_REMOTE:
        return f"remote:{remote_model()}" if is_remote_available() else "local（远端未配置，已降级）"
    return BACKEND_LOCAL


# --------------------------------------------------------------------------- #
# 2. 向量化主入口
# --------------------------------------------------------------------------- #
def _normalize(vec: Any) -> np.ndarray:
    """把任意向量整理成 float32、一维、L2 归一化的数组。

    归一化是必须的：远端返回的向量没有"单位长度"保证，而检索侧用的是内积当余弦。

    :param vec: 模型返回的 list[float] 或 ndarray
    :return: shape=(dim,) 的 float32 单位向量
    """
    arr = np.asarray(vec, dtype=np.float32).ravel()
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr


def _cache_key(text: str) -> str:
    """缓存键：后端标识 + 文本。

    带后端前缀是为了换后端后**不会**读到上一条通道的向量（维度不同会直接算错）。
    """
    return f"{describe()}::{text}"


def _cache_get(key: str) -> np.ndarray | None:
    """读缓存（命中时返回同一个数组对象，调用方不要原地改它）。"""
    with _LOCK:
        return _CACHE.get(key)


def _cache_put(key: str, vec: np.ndarray) -> None:
    """写缓存；超过上限时整体清空（见 `_CACHE_LIMIT` 的说明）。"""
    with _LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = vec


def embed_many(texts: list[str]) -> list[np.ndarray]:
    """把多段文本转成单位向量列表（远端优先，失败整体降级本地）。

    为什么整批降级而不是"能拿几条算几条"：向量来自不同通道时**不可比较**
    （维度与语义空间都不同），混用会让检索结果变得毫无意义。

    :param texts: 文本列表（顺序与返回一一对应）
    :return: 与 texts 等长的向量列表
    """
    if not texts:
        return []
    if is_remote_available():
        try:
            vectors = _embed_remote(texts)
        except Exception:
            log.warning("远端 embedding 调用失败，本次降级为本地向量化", exc_info=True)
            vectors = None
        if vectors and len(vectors) == len(texts):
            return [_normalize(vec) for vec in vectors]
    # 本地兜底：逐条算，保持"同一段文字向量唯一"的性质
    return [vectorize(text.strip(), VECTOR_DIM) for text in texts]


def embed_one(text: str) -> np.ndarray:
    """单段文本的单位向量（带进程内缓存，检索时高频调用）。

    :param text: 文本
    :return: shape=(dim,) 的 float32 单位向量；dim 由所选后端决定
    """
    cleaned = (text or "").strip()
    if not cleaned:
        # 空文本给一个固定的零向量：调用方（检索）已经在更外层挡掉了空查询，
        # 这里兜底是为了避免远端端点对空输入返回 400 而把整次检索拖成异常。
        return np.zeros(VECTOR_DIM, dtype=np.float32)
    key = _cache_key(cleaned)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    vec = embed_many([cleaned])[0]
    _cache_put(key, vec)
    return vec


def clear_cache() -> None:
    """清空向量缓存（测试用：换后端或改设置后需要让新配置立即生效）。"""
    with _LOCK:
        _CACHE.clear()


# --------------------------------------------------------------------------- #
# 3. 远端实现（OpenAI 兼容 /embeddings）
# --------------------------------------------------------------------------- #
def _embed_remote(texts: list[str]) -> list[np.ndarray]:
    """真正发一次 HTTP 请求。

    请求体与 OpenAI `/embeddings` 完全一致：`{"model": ..., "input": [...]}`，
    响应里 `data[i]["embedding"]` 按 `index` 对应输入顺序。

    :param texts: 文本列表
    :return: 向量列表（保持输入顺序）
    :raises RuntimeError: 端点返回非 200、响应结构不认识、或条数对不上
    """
    resolved = _resolve_remote_endpoint()
    if resolved is None:
        raise RuntimeError("远端 embedding 未配置（缺地址或缺密钥）")
    _provider_id, base, api_key = resolved
    # 第三方库：HTTP 客户端（项目已依赖；这里只用同步接口，便于在线程池里跑）
    import httpx

    response = httpx.post(
        f"{base}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": remote_model(), "input": texts},
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RuntimeError(f"embedding 端点返回 HTTP {response.status_code}: {response.text[:200]}")
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError("embedding 响应结构不认识（data 缺失或条数不符）")
    # 按 index 排序，避免某些兼容实现乱序返回
    ordered = sorted(
        (item for item in data if isinstance(item, dict)),
        key=lambda item: int(item.get("index", 0)),
    )
    vectors: list[np.ndarray] = []
    for item in ordered:
        embedding = item.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError("embedding 响应里缺少向量")
        vectors.append(np.asarray(embedding, dtype=np.float32))
    return vectors
