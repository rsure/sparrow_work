"""文档库（RAG）接口：文件/文本入库、向量检索、文档增删查、索引重建。

路由统一挂在 /rag 前缀下；具体切块、向量化、FAISS 检索与 SQLite 存储都在
app.services.rag_store_service 里实现，本文件只做参数校验与响应包装。
"""

# Web 框架：APIRouter 声明本模块的 /rag 路由；Query 用于声明必填的查询参数
from fastapi import APIRouter, Query
# 数据校验：BaseModel 定义请求体；Field 给字段声明默认值、取值范围与说明（会出现在 /docs）
from pydantic import BaseModel, Field
# 项目内：统一响应外壳，保证所有接口返回同一种 JSON 形状
from app.schemas.common import ApiResponse
# 项目内：文档库业务逻辑（切块、调用向量模型、检索、读写 SQLite 与 FAISS）
from app.services.rag_store_service import RagStoreService


# 本模块路由：统一前缀 /rag，在 /docs 文档里归到 rag 分组
router = APIRouter(prefix="/rag", tags=["rag"])

# 全局唯一的文档库服务实例（内存里的 FAISS 索引只加载一次，避免每次请求重建）
# 切块 500 字符、相邻块重叠 80 字符，防止句子被切断后丢失语义
svc = RagStoreService(chunk_size=500, overlap=80)



class IndexFileReq(BaseModel):
    """按本地文件路径入库的请求体。"""

    # 待入库文件的本地路径（支持 PDF/DOCX/TXT 等，由服务端解析成纯文本）
    path: str = Field(description="待入库文件的本地路径，服务端据此读取并解析内容")
    # 文档来源标识（如目录名/应用名），用于归类以及「按来源检索、按来源删除」；不传由服务端推断
    source: str | None = Field(default=None, description="文档来源标识，用于归类与按来源检索/删除；空则自动推断")
    # 文档标题，仅用于列表展示；为空时取文件名
    title: str | None = Field(default=None, description="文档标题（展示用）；为空时取文件名")
    # 是否强制执行：同一来源已入库时默认跳过，置 True 则重新解析并重新向量化
    force: bool = Field(default=False, description="True 表示忽略已有记录，强制重新解析并入库")


class IndexTextReq(BaseModel):
    """直接提交文本内容入库的请求体（前端粘贴或程序生成的内容，不走文件解析）。"""

    # 文本来源标识，用于归类与按来源删除
    source: str = Field(description="文本来源标识，用于归类与按来源检索/删除")
    # 待入库的正文，服务端会按 chunk_size 切块后逐块向量化
    text: str = Field(description="待入库的正文文本，服务端会切块并逐块向量化")
    # 展示用标题，为空时由服务端自动生成
    title: str | None = Field(default=None, description="文档标题（展示用）；为空时自动生成")
    # 同一来源已有记录时是否强制重新入库
    force: bool = Field(default=False, description="True 表示忽略已有记录，强制重新入库")


class SearchReq(BaseModel):
    """向量检索请求体：在已入库文档里按语义相似度找相关片段。"""

    # 检索问题原文，会被向量化后与库中分块逐一比较相似度
    query: str = Field(description="检索问题原文，会被向量化后与库中分块比较相似度")
    # 返回条数上限：1~100，默认 10；越大召回越多但响应越慢
    top_k: int = Field(10, ge=1, le=100, description="返回条数上限（1~100，默认 10）")
    # 相似度下限：低于该分值的命中会被丢弃；None 表示不设阈值、全部返回
    score_threshold: float | None = Field(default=None, description="相似度下限，低于该分值的命中会被过滤；None 表示不设阈值")
    # 只在指定的几篇文档里检索（对应前端「勾选文档」后限定范围的场景）
    doc_ids: list[int] | None = Field(default=None, description="限定检索的文档 id 列表；None 表示不限文档")
    # 只在指定的几个来源里检索
    sources: list[str] | None = Field(default=None, description="限定检索的来源标识列表；None 表示不限来源")


class BatchDeleteReq(BaseModel):
    """批量删除文档的请求体。"""

    # 待删除的文档 id 列表，服务端会同时清掉 SQLite 记录与 FAISS 中对应的向量
    ids: list[int] = Field(description="待删除的文档 id 列表")


@router.post("/documents", response_model=ApiResponse[dict])
def index_file(req: IndexFileReq):
    """把本地文件解析、切块、向量化后写入文档库。

    场景：前端「添加文档」选择本地文件时调用。
    文件不存在返回 code=404；PDF/DOCX 损坏等解析失败返回 code=422。
    """
    try:
        r = svc.index_file(req.path, source=req.source,
                            title=req.title, force=req.force)
    except FileNotFoundError as e:
        return ApiResponse(code=404, message=str(e))
    except Exception as e:  # PDF/DOCX 损坏等解析失败
        return ApiResponse(code=422, message=f"文档解析失败: {e}")
    return ApiResponse(code=0, message="ok", data=r.__dict__)


@router.post("/documents/text", response_model=ApiResponse[dict])
def index_text(req: IndexTextReq):
    """把一段纯文本直接切块入库，跳过文件解析步骤。

    场景：前端粘贴文本、或其它模块把生成的内容直接存进知识库。
    """
    r = svc.index_text(req.source, req.text,
                        title=req.title, force=req.force)
    return ApiResponse(code=0, message="ok", data=r.__dict__)


# 必须注册在 /documents/{doc_id} 之前，否则 by-source 会被当成 doc_id 匹配
@router.delete("/documents/by-source", response_model=ApiResponse[dict])
def delete_by_source(source: str = Query(...)):
    """按来源标识删除该来源下的全部文档（记录与向量一起清理）。

    场景：整批导入的文档需要整体移除时，比逐个 id 删除方便。
    该来源不存在任何文档时返回 code=404。

    :param source: 查询参数 source，指定要删除的来源标识
    """
    if not svc.delete_by_source(source):
        return ApiResponse(code=404, message="document not found")
    return ApiResponse(code=0, message="ok", data={"deleted": source})


@router.delete("/documents/{doc_id}", response_model=ApiResponse[dict])
def delete_doc(doc_id: int):
    """按文档 id 删除单篇文档，同时清理它在向量索引中的分块。

    :param doc_id: 路径参数，要删除的文档 id；不存在时返回 code=404
    """
    if not svc.delete_by_id(doc_id):
        return ApiResponse(code=404, message="document not found")
    return ApiResponse(code=0, message="ok", data={"deleted": doc_id})


@router.post("/documents/batch-delete", response_model=ApiResponse[dict])
def batch_delete(req: BatchDeleteReq):
    """批量删除文档：一次提交多个 id，返回实际删除的条数。

    场景：列表页勾选多行后「批量删除」。
    :return: data={"deleted": 实际删除条数}，不存在的 id 会被静默忽略
    """
    deleted = svc.delete_by_ids(req.ids)
    return ApiResponse(code=0, message="ok", data={"deleted": deleted})


@router.get("/documents/{doc_id}", response_model=ApiResponse[dict])
def get_doc(doc_id: int):
    """查询单篇文档的详情（元信息、来源、分块数量等）。

    :param doc_id: 路径参数，要查询的文档 id；不存在时返回 code=404
    """
    d = svc.get_document(doc_id)
    if d is None:
        return ApiResponse(code=404, message="document not found")
    return ApiResponse(code=0, message="ok", data=d)


@router.get("/documents", response_model=ApiResponse[list[dict]])
def list_docs(limit: int = 50, offset: int = 0):
    """分页列出文档库中的文档，供前端文档列表页展示。

    :param limit: 本次最多返回多少条，默认 50
    :param offset: 跳过前面多少条，配合 limit 实现翻页
    """
    return ApiResponse(code=0, message="ok", data=svc.list_documents(limit=limit, offset=offset))


@router.post("/search", response_model=ApiResponse[list[dict]])
def search(req: SearchReq):
    """按语义相似度检索文档片段，返回命中的片段文本及其来源文档与分值。

    场景：前端搜索框提问、以及对话接口给「勾选文档」找引用依据。
    """
    hits = svc.search(
        req.query,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
        doc_ids=req.doc_ids,
        sources=req.sources,
    )
    return ApiResponse(code=0, message="ok", data=[h.__dict__ for h in hits])


@router.post("/index/rebuild", response_model=ApiResponse[dict])
def rebuild_index():
    """从 SQLite 全量重建 FAISS 索引（不重新向量化）。

    场景：索引文件损坏或丢失，但库里的向量数据还在时用它快速恢复。
    :return: data={"vectors": 写入索引的向量条数}
    """
    return ApiResponse(code=0, message="ok", data={"vectors": svc.rebuild_index()})
