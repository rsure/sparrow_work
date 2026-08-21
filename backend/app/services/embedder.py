"""embedding 调用封装：批量 + 限并发 + 指数退避重试 + 进度回调。"""
# 让类型注解延迟求值（PEP 563），便于用 `np.ndarray | None`、`list[...]` 这种新语法
from __future__ import annotations

# asyncio：并发闸门（Semaphore）、计数锁（Lock）、并发调度（gather）与退避 sleep
import asyncio
# random：给退避时间加抖动，避免多个并发请求同时重试形成"惊群"
import random
# 类型标注：Callable 描述进度回调签名，Sequence 描述只读的文本序列
from collections.abc import Callable, Sequence
# dataclass：把一堆配置项聚合成一个不可变对象
from dataclasses import dataclass

# httpx：异步 HTTP 客户端，调用 OpenAI 兼容的 /embeddings 接口
import httpx
# numpy：把接口返回的向量拼成 (n, dim) 矩阵，并做维度校验
import numpy as np


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """embedding 服务配置：地址、密钥、模型、批大小与重试策略；frozen 保证运行期不被篡改。"""

    base_url: str          # 例：https://api.siliconflow.cn/v1
    # API 密钥，用于请求头 Authorization: Bearer
    api_key: str
    model: str             # 例：BAAI/bge-m3
    # 向量维度（如 bge-m3 为 1024）：接口返回维度与它不符会直接抛 EmbeddingError
    dim: int = 1024
    batch_size: int = 32   # 单次请求带多少条文本
    concurrency: int = 4   # 同时在飞的请求数
    # 单次 HTTP 请求超时（秒），超过即视为可重试的传输错误
    timeout_s: float = 60.0
    # 最大尝试次数（含首次），耗尽后抛 EmbeddingError
    max_retries: int = 4
    # 查询侧前缀：只有 embed_query 会拼上（部分模型（如 bge）建议给问题加指令前缀）
    query_prefix: str = ""
    char_limit: int = 8000  # 模型输入上限的粗略护栏

    @property
    def endpoint(self) -> str:
        """拼出真正的请求地址：去掉 base_url 末尾多余的 /，再补 /embeddings。"""
        return f"{self.base_url.rstrip('/')}/embeddings"


class EmbeddingError(RuntimeError):
    """embedding 调用最终失败（已耗尽重试）。"""


def _clean(text: str, limit: int) -> str:
    """发出前必须清洗，否则整批 400：
    - 空字符串 → 换成空格（接口直接拒绝空串）
    - 超长 → 截断（★ 这是静默的语义损失，也是 chunk_size 不能太大的理由之一）
    """
    text = text.strip()
    return text[:limit] if text else " "


class Embedder:
    """embedding 客户端：持有异步连接池与调用计数，对外提供"单批 / 全量 / 查询"三种向量化入口。"""

    def __init__(self, cfg: EmbeddingConfig) -> None:
        """按配置建好异步 HTTP 客户端（超时 + 鉴权头），并清零调用计数。

        :param cfg: 服务地址、密钥、模型、批大小、重试策略等配置
        """
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.timeout_s),
            headers={"Authorization": f"Bearer {cfg.api_key}"},
        )
        self.calls = 0        # ★ 统计真实请求数，增量索引的验收就靠它
        # 累计发出的文本条数：可用 calls 与它推算平均批大小、评估成本
        self.texts_sent = 0

    async def aclose(self) -> None:
        """关闭底层 httpx 连接池；服务停止（FastAPI lifespan shutdown）时调用，避免连接泄漏。"""
        await self._client.aclose()

    async def _post_once(self, batch: Sequence[str]) -> list[list[float]]:
        """发一次 POST /embeddings（不做重试）。

        429（限流）与 5xx 抛可重试异常；其他 4xx 说明请求本身有问题，直接抛出。
        :param batch: 本批要向量化的文本
        :return: 与入参顺序一致（已按 index 排回）的向量列表
        """
        payload = {
            "model": self._cfg.model,
            "input": [_clean(t, self._cfg.char_limit) for t in batch],
            "encoding_format": "float",
        }
        resp = await self._client.post(self._cfg.endpoint, json=payload)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise httpx.HTTPStatusError(       # 可重试：限流、网关/服务端错误
                f"可重试状态码 {resp.status_code}: {resp.text[:200]}",
                request=resp.request, response=resp,
            )
        resp.raise_for_status()   # 4xx（除 429）= 请求有问题，重试没用，直接抛
        data = resp.json()["data"]
        data.sort(key=lambda d: d["index"])   # ★ 服务不保证顺序，不排回去会"文不对题"
        return [d["embedding"] for d in data]

    async def embed_batch(self, batch: Sequence[str]) -> np.ndarray:
        """一批文本 → (n, dim) float32。指数退避 + 抖动。"""
        delay, last_exc = 1.0, None
        for attempt in range(1, self._cfg.max_retries + 1):
            try:
                arr = np.asarray(await self._post_once(batch), dtype=np.float32)
                if arr.shape[1] != self._cfg.dim:
                    raise EmbeddingError(
                        f"维度不符：配置 {self._cfg.dim}，实际 {arr.shape[1]}。"
                        "换模型必须重建整个索引。")
                self.calls += 1
                self.texts_sent += len(batch)
                return arr
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == self._cfg.max_retries:
                    break
                # 抖动很重要：多个并发请求同时退避会形成"惊群"，同一时刻再次打过去
                await asyncio.sleep(min(delay * (0.5 + random.random()), 20.0))
                delay *= 2
        raise EmbeddingError(
            f"embedding 失败（已重试 {self._cfg.max_retries} 次）：{last_exc}") from last_exc

    async def embed_all(self, texts: Sequence[str],
                        on_progress: Callable[[int, int], None] | None = None) -> np.ndarray:
        """全量向量化。★ 限并发，否则 1 万条文本会瞬间打死对方接口。

        :param texts: 全部待向量化文本，内部按 batch_size 切批
        :param on_progress: 进度回调，签名 (已完成批数, 总批数)，用于给前端推进度
        :return: (len(texts), dim) 的矩阵；没有输入时返回 (0, dim) 空矩阵
        """
        cfg = self._cfg
        batches = [texts[i : i + cfg.batch_size] for i in range(0, len(texts), cfg.batch_size)]
        sem = asyncio.Semaphore(cfg.concurrency)
        results: list[np.ndarray | None] = [None] * len(batches)
        done, lock = 0, asyncio.Lock()

        async def run(idx: int, batch: Sequence[str]) -> None:
            """跑一批：先过并发闸门，结果按 idx 写回 results，再原子地累加完成数并回调进度。"""
            nonlocal done
            async with sem:
                results[idx] = await self.embed_batch(batch)
            async with lock:
                done += 1
                if on_progress:
                    on_progress(done, len(batches))

        await asyncio.gather(*(run(i, b) for i, b in enumerate(batches)))
        if not results:
            return np.zeros((0, cfg.dim), dtype=np.float32)
        return np.vstack([r for r in results if r is not None])

    async def embed_query(self, question: str) -> np.ndarray:
        """查询侧。★ 只有查询侧才拼 query_prefix。"""
        return (await self.embed_batch([self._cfg.query_prefix + question]))[0]
