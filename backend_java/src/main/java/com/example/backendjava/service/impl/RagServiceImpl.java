// 模块说明：RAG 文档库业务实现（对应 Python 侧 app/services/rag_store_service.py）。
//
// 整体数据流：
//   文件/文本 → 文档级 hash 判断是否跳过 → 切分为 chunks
//   → 切片级 hash 判断能否复用旧向量 → 只对新增/变化切片向量化
//   → 写 SQLite（提交）→ 同步内存向量索引
//
// SQLite 是唯一真相源；内存里的 InMemoryEmbeddingStore 只是检索加速层，
// 进程重启后会从 SQLite 的向量 BLOB 全量重建。
package com.example.backendjava.service.impl;

// LangChain4j 向量对象：把 float[] 包装成向量索引能接收的形态
import dev.langchain4j.data.embedding.Embedding;
// LangChain4j 文本片段：作为内存索引里的「被检索对象」，同时携带 doc_id / source 元信息
import dev.langchain4j.data.segment.TextSegment;
// LangChain4j 元信息：让检索结果能按文档 id / 来源过滤
import dev.langchain4j.data.document.Metadata;
// LangChain4j 检索命中：包含向量 id、相似度与原文片段
import dev.langchain4j.store.embedding.EmbeddingMatch;
// LangChain4j 检索请求：查询向量、返回条数、相似度下限
import dev.langchain4j.store.embedding.EmbeddingSearchRequest;
// LangChain4j 内存向量库：本工程的教学用检索层（对应 Python 的 FAISS）
import dev.langchain4j.store.embedding.inmemory.InMemoryEmbeddingStore;

// 第三方（Spring）：声明为本服务的 Bean 实现
import org.springframework.stereotype.Service;
// 第三方（Spring）：声明事务边界（写文档与切片必须一起成功）
import org.springframework.transaction.annotation.Transactional;

// 标准库：IOException 表示文件读取失败
import java.io.IOException;
// 标准库：InputStream 分块读文件计算 SHA-256
import java.io.InputStream;
// 标准库：StandardCharsets 明确 UTF-8
import java.nio.charset.StandardCharsets;
// 标准库：Files 判断文件并读取大小
import java.nio.file.Files;
// 标准库：Path 路径对象
import java.nio.file.Path;
// 标准库：Paths 字符串转 Path
import java.nio.file.Paths;
// 标准库：MessageDigest 计算 SHA-256
import java.security.MessageDigest;
// 标准库：NoSuchAlgorithmException 表示 JVM 缺少 SHA-256（正常不会发生）
import java.security.NoSuchAlgorithmException;
// 标准库：LocalDateTime 生成 ISO-8601 时间字符串
import java.time.LocalDateTime;
// 标准库：ArrayList 保存切片行
import java.util.ArrayList;
// 标准库：Collection 批量 id 参数
import java.util.Collection;
// 标准库：HashMap 构建 id → 实体映射
import java.util.HashMap;
// 标准库：HashSet 过滤时做 O(1) 判断
import java.util.HashSet;
// 标准库：HexFormat 把 SHA-256 字节转十六进制
import java.util.HexFormat;
// 标准库：List 切片与检索结果
import java.util.List;
// 标准库：Map 删除/重建结果
import java.util.Map;
// 标准库：Objects 比较 hash 时避免 null
import java.util.Objects;
// 标准库：Optional 表达「可能不存在」
import java.util.Optional;
// 标准库：Set 检索范围去重
import java.util.Set;

// 项目内：业务异常（404/422 等业务码）
import com.example.backendjava.common.ApiException;
// 项目内：limit 的默认值与上限契约表（与 Python 侧 app/core/limits.py 一一对应）
import com.example.backendjava.common.PageLimits;
// 项目内：RAG 请求/响应 DTO
import com.example.backendjava.dto.RagDtos;
// 项目内：RAG 文档实体
import com.example.backendjava.entity.RagDocument;
// 项目内：RAG 切片实体
import com.example.backendjava.entity.RagChunk;
// 项目内：RAG 索引元信息实体
import com.example.backendjava.entity.RagIndexMeta;
// 项目内：文档仓库
import com.example.backendjava.repository.RagDocumentRepository;
// 项目内：切片仓库
import com.example.backendjava.repository.RagChunkRepository;
// 项目内：索引元信息仓库
import com.example.backendjava.repository.RagIndexMetaRepository;
// 项目内：RAG 业务接口（本类实现它）
import com.example.backendjava.service.RagService;
// 项目内：文本读取结果（text 为 null 表示读不出正文）
import com.example.backendjava.tools.TextReadResult;
// 项目内：文件读取与后缀工具
import com.example.backendjava.tools.ToolUtils;

/**
 * RAG 文档库服务实现。
 */
@Service
public class RagServiceImpl implements RagService {

    /** 默认切片大小（字符数）：与 Python 侧 RagStoreService 的 chunk_size=500 对齐。 */
    private static final int CHUNK_SIZE = 500;

    /** 相邻切片的重叠字符数：与 Python 侧 overlap=80 对齐。 */
    private static final int CHUNK_OVERLAP = 80;

    /** 文档仓库：文档级元数据与 source 唯一标识。 */
    private final RagDocumentRepository documentRepository;

    /** 切片仓库：切片原文、内容指纹与向量 BLOB。 */
    private final RagChunkRepository chunkRepository;

    /** 索引元信息仓库：校验模型名与向量维度。 */
    private final RagIndexMetaRepository metaRepository;

    /** 本地哈希向量化器：入库与检索共用同一套清洗 + 向量化逻辑。 */
    private final LocalHashEmbedder embedder = new LocalHashEmbedder();

    /** 递归文本切分器。 */
    private final RagTextSplitter splitter = new RagTextSplitter();

    /** 内存向量索引：按向量 id（即 rag_chunk.id）保存，便于删除与增量同步。 */
    private final InMemoryEmbeddingStore<TextSegment> store = new InMemoryEmbeddingStore<>();

    /** 保护内存索引的加载与增删；检索时短暂持锁，避免读写并发破坏集合。 */
    private final Object indexLock = new Object();

    /** 内存索引是否已经从 SQLite 加载过；false 时下一次检索会触发重建。 */
    private boolean indexLoaded = false;

    /**
     * 构造器注入三个仓库。
     *
     * @param documentRepository 文档仓库
     * @param chunkRepository    切片仓库
     * @param metaRepository     索引元信息仓库
     */
    public RagServiceImpl(RagDocumentRepository documentRepository,
                          RagChunkRepository chunkRepository,
                          RagIndexMetaRepository metaRepository) {
        this.documentRepository = documentRepository;
        this.chunkRepository = chunkRepository;
        this.metaRepository = metaRepository;
    }

    // ------------------------------------------------------------------ //
    // 一、入库
    // ------------------------------------------------------------------ //

    /**
     * 按本地文件路径入库（幂等 + 增量）。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    @Override
    @Transactional
    public RagDtos.IndexResult indexFile(RagDtos.IndexFileRequest request) {
        Path path;
        try {
            // 与 Python 侧一致：允许相对路径，统一转成绝对路径后再取 source
            path = Paths.get(request.path()).toAbsolutePath().normalize();
        } catch (RuntimeException e) {
            throw new ApiException(422, "文档解析失败: 路径不合法 " + e.getMessage(), e);
        }
        if (!Files.isRegularFile(path)) {
            throw new ApiException(404, "文件不存在: " + path);
        }

        String fileHash;
        try {
            fileHash = sha256File(path);
        } catch (IOException e) {
            throw new ApiException(422, "文档解析失败: 无法读取文件 " + e.getMessage(), e);
        }
        // source 是文档唯一标识：没传就用绝对路径
        String source = (request.source() == null || request.source().isBlank())
                ? path.toString()
                : request.source();

        if (!request.force()) {
            RagDtos.IndexResult skipped = skipIfUnchanged(source, fileHash);
            if (skipped != null) {
                return skipped;
            }
        }

        // 只有没命中跳过才解析：解析较慢，没必要每次都做
        String text = parseFile(path);
        List<String> pieces = splitter.split(text, CHUNK_SIZE, CHUNK_OVERLAP);
        return index(source, pieces, fileHash, request.title(), path.toString(), request.force());
    }

    /**
     * 直接按纯文本入库（不经过文件系统）。
     *
     * @param request 入库请求
     * @return 入库结果
     */
    @Override
    @Transactional
    public RagDtos.IndexResult indexText(RagDtos.IndexTextRequest request) {
        // 文本内容 hash 充当文档级 hash，作用同 indexFile 的文件 hash
        String textHash = embedder.sha256Hex(request.text());
        if (!request.force()) {
            RagDtos.IndexResult skipped = skipIfUnchanged(request.source(), textHash);
            if (skipped != null) {
                return skipped;
            }
        }
        List<String> pieces = splitter.split(request.text(), CHUNK_SIZE, CHUNK_OVERLAP);
        return index(request.source(), pieces, textHash, request.title(), "", request.force());
    }

    /**
     * 文档内容未变化时返回 skipped 结果。
     *
     * @param source  来源标识
     * @param docHash 本次内容 hash
     * @return 可跳过时返回 skipped 结果；文档不存在或内容已变化时返回 null
     */
    private RagDtos.IndexResult skipIfUnchanged(String source, String docHash) {
        Optional<RagDocument> existing = documentRepository.findBySource(source);
        if (existing.isEmpty() || !Objects.equals(existing.get().getDocHash(), docHash)) {
            return null;
        }
        RagDocument doc = existing.get();
        long total = chunkRepository.countByDocumentId(doc.getId());
        return new RagDtos.IndexResult(doc.getId(), source, "skipped", (int) total, 0);
    }

    /**
     * 把解析后的文本读出来；读不出来时抛 422（对应 Python 的解析失败分支）。
     *
     * @param path 已存在的文件
     * @return 全文
     */
    private String parseFile(Path path) {
        TextReadResult result = ToolUtils.readTextAny(path);
        if (result.text() == null) {
            // Java 侧暂未接入 PDF/Office 解析器，这里会得到明确的「需要专用解析器」提示
            throw new ApiException(422, "文档解析失败: " + result.note());
        }
        return result.text();
    }

    /**
     * 真正的增量写入：先写 SQLite，再同步内存索引。
     *
     * @param source  来源标识
     * @param chunks  切片文本列表
     * @param docHash 文档级内容 hash
     * @param title   标题；null 表示更新时保持原标题
     * @param path    原始文件路径；纯文本入库时为空串
     * @param force   是否强制重新向量化
     * @return 入库结果
     */
    private RagDtos.IndexResult index(String source,
                                      List<String> chunks,
                                      String docHash,
                                      String title,
                                      String path,
                                      boolean force) {
        ensureMeta();

        String now = LocalDateTime.now().toString();
        RagDocument doc = documentRepository.findBySource(source).orElse(null);
        String action;
        if (doc == null) {
            action = "created";
            doc = new RagDocument();
            doc.setSource(source);
            doc.setTitle(resolveTitle(title, path, source));
            doc.setPath(path == null ? "" : path);
            doc.setDocHash(docHash);
            doc.setCreatedAt(now);
            doc.setUpdatedAt(now);
            // 立即 INSERT 以拿到自增 id：下面写切片要用
            doc = documentRepository.saveAndFlush(doc);
        } else {
            action = "updated";
            doc.setDocHash(docHash);
            // 与 Python 侧一致：只有「没传标题」才保持原标题，传空串也算明确覆盖
            if (title != null) {
                doc.setTitle(title);
            }
            if (path != null && !path.isBlank()) {
                doc.setPath(path);
            }
            doc.setUpdatedAt(now);
            doc = documentRepository.saveAndFlush(doc);
        }

        // 旧切片下面会全部删除重建，所以它们的 id 都要从内存索引移除
        List<RagChunk> oldChunks = chunkRepository.findByDocumentIdOrderByChunkIndexAsc(doc.getId());
        List<String> removedIds = new ArrayList<>(oldChunks.size());
        Map<String, RagChunk> existingByHash = new HashMap<>();
        for (RagChunk old : oldChunks) {
            removedIds.add(String.valueOf(old.getId()));
            // 同一文档内重复内容的切片向量相同，保留任意一条即可
            existingByHash.put(old.getContentHash(), old);
        }

        // 组装每行元信息（清洗后的文本决定向量，也决定内容指纹）
        List<ChunkRow> rows = new ArrayList<>(chunks.size());
        for (int i = 0; i < chunks.size(); i++) {
            String raw = chunks.get(i);
            String clean = embedder.clean(raw, LocalHashEmbedder.CHAR_LIMIT);
            rows.add(new ChunkRow(
                    i,
                    raw,
                    clean,
                    clean.length(),
                    clean.length() >= LocalHashEmbedder.CHAR_LIMIT,
                    embedder.sha256Hex(clean)
            ));
        }

        List<ChunkRow> toEmbed = new ArrayList<>();
        Map<String, byte[]> hashToVector = new HashMap<>();
        for (ChunkRow row : rows) {
            RagChunk old = existingByHash.get(row.contentHash());
            if (old != null && old.getEmbedding() != null && !force) {
                // 复用旧向量：增量索引的核心，内容没变的切片不重新计算
                hashToVector.put(row.contentHash(), old.getEmbedding());
            } else {
                toEmbed.add(row);
            }
        }
        for (ChunkRow row : toEmbed) {
            float[] vector = embedder.vectorize(row.textClean());
            hashToVector.put(row.contentHash(), embedder.toBytes(vector));
        }

        // 清掉旧行，再按新的切片顺序重新插入（chunk id 会变）
        chunkRepository.deleteByDocumentId(doc.getId());
        chunkRepository.flush();

        List<RagChunk> newChunks = new ArrayList<>(rows.size());
        for (ChunkRow row : rows) {
            byte[] blob = hashToVector.get(row.contentHash());
            RagChunk chunk = new RagChunk();
            chunk.setDocumentId(doc.getId());
            chunk.setChunkIndex(row.index());
            chunk.setText(row.text());
            chunk.setTextClean(row.textClean());
            chunk.setCharLen(row.charLen());
            chunk.setTruncated(row.truncated());
            chunk.setContentHash(row.contentHash());
            chunk.setEmbedding(blob);
            // 向量相关字段只在确实有向量时填写，保证「有 embedding ⇔ 有 dim/model」
            if (blob != null) {
                chunk.setDim(LocalHashEmbedder.VECTOR_DIM);
                chunk.setModel(LocalHashEmbedder.MODEL_NAME);
                chunk.setEmbeddedAt(now);
            }
            chunk.setCreatedAt(now);
            newChunks.add(chunk);
        }
        // 拿到新 chunk id，作为内存索引里的向量 id
        chunkRepository.saveAllAndFlush(newChunks);

        syncIndex(removedIds, newChunks, source);
        return new RagDtos.IndexResult(
                doc.getId(),
                source,
                action,
                rows.size(),
                toEmbed.size()
        );
    }

    /**
     * 把标题补成可用于展示的值：优先用户给的标题，其次文件名，最后 source。
     *
     * @param title 用户标题
     * @param path  文件路径（纯文本入库时为空串）
     * @param source 来源标识
     * @return 非空标题
     */
    private String resolveTitle(String title, String path, String source) {
        if (title != null && !title.isBlank()) {
            return title;
        }
        if (path != null && !path.isBlank()) {
            Path fileName = Paths.get(path).getFileName();
            if (fileName != null) {
                return fileName.toString();
            }
        }
        return source == null ? "" : source;
    }

    /**
     * 校验/初始化索引元信息，防止新旧不兼容向量混用。
     *
     * @throws ApiException 当前模型或维度与已记录的不一致
     */
    private void ensureMeta() {
        ensureMetaValue("model", LocalHashEmbedder.MODEL_NAME);
        ensureMetaValue("dim", String.valueOf(LocalHashEmbedder.VECTOR_DIM));
    }

    /**
     * 校验一项元信息：不存在则写入，存在但不一致则报错。
     *
     * @param key      元信息键（model / dim）
     * @param expected 当前期望值
     */
    private void ensureMetaValue(String key, String expected) {
        RagIndexMeta row = metaRepository.findById(key).orElse(null);
        if (row == null) {
            row = new RagIndexMeta();
            row.setKey(key);
            row.setValue(expected);
            metaRepository.save(row);
            return;
        }
        if (!expected.equals(row.getValue())) {
            throw new ApiException(422,
                    "index_meta." + key + " 冲突：已有 " + row.getValue() + "，当前 " + expected
                            + "。换模型/维度必须重建整个索引。");
        }
    }

    // ------------------------------------------------------------------ //
    // 二、索引同步
    // ------------------------------------------------------------------ //

    /**
     * 把本次新增的切片写入内存索引，并移除旧切片。
     *
     * @param removedIds 需要移除的旧向量 id
     * @param newChunks  新插入的切片（只同步有向量的）
     * @param source     文档来源，写入元信息供检索过滤
     */
    private void syncIndex(List<String> removedIds, List<RagChunk> newChunks, String source) {
        synchronized (indexLock) {
            // 索引还没加载过就不必同步：下一次检索会从 SQLite 全量重建
            if (!indexLoaded) {
                return;
            }
            if (!removedIds.isEmpty()) {
                store.removeAll(removedIds);
            }
            for (RagChunk chunk : newChunks) {
                if (chunk.getEmbedding() != null) {
                    store.add(
                            String.valueOf(chunk.getId()),
                            Embedding.from(embedder.fromBytes(chunk.getEmbedding())),
                            segmentOf(chunk, source)
                    );
                }
            }
        }
    }

    /**
     * 保证内存索引已加载（惰性重建）。
     */
    private void ensureIndexLoaded() {
        synchronized (indexLock) {
            if (indexLoaded) {
                return;
            }
            loadIndexLocked();
        }
    }

    /**
     * 从 SQLite 全量加载向量到内存索引（调用方必须持有 {@link #indexLock}）。
     */
    private void loadIndexLocked() {
        store.removeAll();
        // 元信息只需要 source：先一次性把文档表读进内存，避免逐条查库
        Map<Long, String> sources = new HashMap<>();
        for (RagDocument doc : documentRepository.findAll()) {
            sources.put(doc.getId(), doc.getSource());
        }
        for (RagChunk chunk : chunkRepository.findByEmbeddingIsNotNull()) {
            if (chunk.getEmbedding() == null || chunk.getEmbedding().length == 0) {
                continue;
            }
            try {
                float[] vector = embedder.fromBytes(chunk.getEmbedding());
                String source = sources.getOrDefault(chunk.getDocumentId(), "");
                store.add(
                        String.valueOf(chunk.getId()),
                        Embedding.from(vector),
                        segmentOf(chunk, source)
                );
            } catch (RuntimeException e) {
                // 单条坏向量（例如历史版本写入格式不同）不应让整个索引加载失败
                // 这里跳过并在下次重建时自然修复
            }
        }
        indexLoaded = true;
    }

    /**
     * 构造内存索引里的文本片段与元信息。
     *
     * @param chunk  切片
     * @param source 所属文档来源
     * @return 带元信息的 TextSegment
     */
    private TextSegment segmentOf(RagChunk chunk, String source) {
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("doc_id", chunk.getDocumentId());
        metadata.put("source", source == null ? "" : source);
        metadata.put("chunk_index", chunk.getChunkIndex());
        return TextSegment.from(chunk.getText(), Metadata.from(metadata));
    }

    // ------------------------------------------------------------------ //
    // 三、删除
    // ------------------------------------------------------------------ //

    /**
     * 按来源删除该来源下的全部文档。
     *
     * @param source 来源标识
     * @return 形如 {"deleted": source} 的结果
     */
    @Override
    @Transactional
    public Map<String, Object> deleteBySource(String source) {
        RagDocument doc = documentRepository.findBySource(source)
                .orElseThrow(() -> new ApiException(404, "document not found"));
        removeDocuments(List.of(doc));
        return Map.of("deleted", source);
    }

    /**
     * 按文档 id 删除。
     *
     * @param docId 文档 id
     * @return 形如 {"deleted": docId} 的结果
     */
    @Override
    @Transactional
    public Map<String, Object> deleteById(long docId) {
        RagDocument doc = documentRepository.findById(docId)
                .orElseThrow(() -> new ApiException(404, "document not found"));
        removeDocuments(List.of(doc));
        return Map.of("deleted", docId);
    }

    /**
     * 批量删除；不存在的 id 会被静默忽略。
     *
     * @param ids 文档 id 列表
     * @return 形如 {"deleted": 实际删除条数} 的结果
     */
    @Override
    @Transactional
    public Map<String, Object> batchDelete(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return Map.of("deleted", 0);
        }
        List<RagDocument> docs = documentRepository.findAllById(ids);
        return Map.of("deleted", removeDocuments(docs));
    }

    /**
     * 删除文档及其切片，并同步内存索引。
     *
     * @param docs 要删除的文档
     * @return 实际删除的文档数
     */
    private int removeDocuments(Collection<RagDocument> docs) {
        if (docs.isEmpty()) {
            return 0;
        }
        List<Long> documentIds = new ArrayList<>(docs.size());
        for (RagDocument doc : docs) {
            documentIds.add(doc.getId());
        }
        // 删除前先记下切片 id：切片删掉后就查不到了，而内存索引需要按 id 移除
        List<String> chunkIds = new ArrayList<>();
        for (RagChunk chunk : chunkRepository.findByDocumentIdIn(documentIds)) {
            chunkIds.add(String.valueOf(chunk.getId()));
        }
        chunkRepository.deleteByDocumentIdIn(documentIds);
        documentRepository.deleteAll(docs);
        documentRepository.flush();

        synchronized (indexLock) {
            if (indexLoaded && !chunkIds.isEmpty()) {
                store.removeAll(chunkIds);
            }
        }
        return docs.size();
    }

    // ------------------------------------------------------------------ //
    // 四、查询与检索
    // ------------------------------------------------------------------ //

    /**
     * 查询单篇文档详情。
     *
     * @param docId 文档 id
     * @return 文档详情；不存在时返回 null，由 Controller 转成 404
     */
    @Override
    @Transactional(readOnly = true)
    public RagDtos.RagDocument getDocument(long docId) {
        RagDocument doc = documentRepository.findById(docId).orElse(null);
        if (doc == null) {
            return null;
        }
        long total = chunkRepository.countByDocumentId(docId);
        long embedded = chunkRepository.countByDocumentIdAndEmbeddingIsNotNull(docId);
        return new RagDtos.RagDocument(
                docId,
                null,
                doc.getSource(),
                doc.getTitle(),
                doc.getDocHash(),
                total,
                embedded,
                null,
                doc.getCreatedAt(),
                doc.getUpdatedAt()
        );
    }

    /**
     * 分页列出文档（按 id 倒序，最新导入的在前）。
     *
     * @param limit  每页条数
     * @param offset 偏移量
     * @return 文档列表
     */
    @Override
    @Transactional(readOnly = true)
    public List<RagDtos.RagDocument> listDocuments(int limit, int offset) {
        // 以前这里只有下限没有上限，`?limit=1000000` 能一次拉全库；现在统一到契约表
        int safeLimit = PageLimits.clamp(limit, PageLimits.MAX_RAG_DOCS);
        int start = Math.max(0, offset);
        List<RagDtos.RagDocument> result = new ArrayList<>();
        for (RagDocument doc : documentRepository.pageNewest(safeLimit, start)) {
            long total = chunkRepository.countByDocumentId(doc.getId());
            result.add(new RagDtos.RagDocument(
                    doc.getId(),
                    nameOf(doc.getSource()),
                    doc.getSource(),
                    doc.getTitle(),
                    doc.getDocHash(),
                    total,
                    null,
                    fileSizeOf(doc.getSource()),
                    doc.getCreatedAt(),
                    doc.getUpdatedAt()
            ));
        }
        return result;
    }

    /**
     * 向量检索：先取内存索引的相似度排序，再回 SQLite 取原文与标题。
     *
     * @param request 检索请求
     * @return 命中片段（按相似度降序）
     */
    @Override
    @Transactional(readOnly = true)
    public List<RagDtos.SearchHit> search(RagDtos.SearchRequest request) {
        String query = request.query() == null ? "" : request.query();
        if (query.isBlank()) {
            return List.of();
        }
        ensureIndexLoaded();

        int topK = request.topK() <= 0 ? 10 : request.topK();
        List<ScoredChunk> scored = new ArrayList<>();
        synchronized (indexLock) {
            if (store.size() == 0) {
                return List.of();
            }
            Set<Long> docFilter = request.docIds() == null ? null : new HashSet<>(request.docIds());
            Set<String> sourceFilter = request.sources() == null ? null : new HashSet<>(request.sources());
            boolean filtered = docFilter != null || sourceFilter != null;

            EmbeddingSearchRequest searchRequest = EmbeddingSearchRequest.builder()
                    .queryEmbedding(embedder.embed(query))
                    // 没有范围过滤时直接取 top_k；有过滤时先取回全部候选，过滤后再截到 top_k
                    .maxResults(filtered ? Math.max(1, store.size()) : Math.max(1, topK))
                    // 阈值未指定时用 -1：向量已归一化，余弦相似度最小就是 -1，
                    // 等价于 Python 侧 score_threshold=None 的「不设阈值」
                    .minScore(request.scoreThreshold() == null ? -1.0 : request.scoreThreshold())
                    .build();

            for (EmbeddingMatch<TextSegment> match : store.search(searchRequest).matches()) {
                TextSegment segment = match.embedded();
                Long docId = segment.metadata().containsKey("doc_id")
                        ? segment.metadata().getLong("doc_id")
                        : null;
                String source = segment.metadata().containsKey("source")
                        ? segment.metadata().getString("source")
                        : "";
                if (docFilter != null && (docId == null || !docFilter.contains(docId))) {
                    continue;
                }
                if (sourceFilter != null && !sourceFilter.contains(source)) {
                    continue;
                }
                try {
                    scored.add(new ScoredChunk(Long.parseLong(match.embeddingId()), match.score()));
                } catch (NumberFormatException e) {
                    // 索引里出现了非数字 id（不应发生）：跳过，不让整次检索失败
                    continue;
                }
                if (scored.size() >= topK) {
                    break;
                }
            }
        }
        if (scored.isEmpty()) {
            return List.of();
        }

        // 内存索引只给 id + 分数，正文/标题以 SQLite 为准
        List<Long> chunkIds = new ArrayList<>(scored.size());
        for (ScoredChunk item : scored) {
            chunkIds.add(item.chunkId());
        }
        Map<Long, RagChunk> chunkById = new HashMap<>();
        Set<Long> documentIds = new HashSet<>();
        for (RagChunk chunk : chunkRepository.findAllById(chunkIds)) {
            chunkById.put(chunk.getId(), chunk);
            documentIds.add(chunk.getDocumentId());
        }
        Map<Long, RagDocument> documentById = new HashMap<>();
        for (RagDocument doc : documentRepository.findAllById(documentIds)) {
            documentById.put(doc.getId(), doc);
        }

        List<RagDtos.SearchHit> hits = new ArrayList<>(scored.size());
        for (ScoredChunk item : scored) {
            RagChunk chunk = chunkById.get(item.chunkId());
            if (chunk == null) {
                // 索引里残留的已删除切片
                continue;
            }
            RagDocument doc = documentById.get(chunk.getDocumentId());
            hits.add(new RagDtos.SearchHit(
                    chunk.getId(),
                    chunk.getDocumentId(),
                    doc == null ? "" : doc.getSource(),
                    doc == null ? "" : doc.getTitle(),
                    chunk.getChunkIndex(),
                    chunk.getText(),
                    item.score()
            ));
        }
        return hits;
    }

    /**
     * 从 SQLite 全量重建内存索引（不重新向量化）。
     *
     * @return 形如 {"vectors": 条数} 的结果
     */
    @Override
    public Map<String, Object> rebuildIndex() {
        synchronized (indexLock) {
            store.removeAll();
            indexLoaded = false;
            loadIndexLocked();
            return Map.of("vectors", store.size());
        }
    }

    // ------------------------------------------------------------------ //
    // 五、文件与文件名辅助
    // ------------------------------------------------------------------ //

    /**
     * 计算文件的 SHA-256（分块读，避免大文件把内存打满）。
     *
     * @param path 文件路径
     * @return 64 位十六进制摘要
     * @throws IOException 文件读取失败
     */
    private String sha256File(Path path) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream in = Files.newInputStream(path)) {
                byte[] buffer = new byte[1 << 20];
                int read;
                while ((read = in.read(buffer)) >= 0) {
                    if (read > 0) {
                        digest.update(buffer, 0, read);
                    }
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("当前 JVM 不支持 SHA-256", e);
        }
    }

    /**
     * 从 source 里取文件名；source 不是合法路径时原样返回。
     *
     * @param source 来源标识
     * @return 展示用文件名
     */
    private String nameOf(String source) {
        try {
            Path fileName = Paths.get(source).getFileName();
            return fileName == null ? source : fileName.toString();
        } catch (RuntimeException e) {
            return source;
        }
    }

    /**
     * 实时读取源文件字节数；文件已删除或 source 不是本地路径时返回 0。
     *
     * @param source 来源标识
     * @return 字节数
     */
    private Long fileSizeOf(String source) {
        try {
            Path path = Paths.get(source);
            return Files.isRegularFile(path) ? Files.size(path) : 0L;
        } catch (IOException | RuntimeException e) {
            return 0L;
        }
    }

    /**
     * 一行切片在写入前的中间形态：原文、清洗文本与内容指纹。
     *
     * @param index       切片在文档内的序号
     * @param text        原文
     * @param textClean   清洗（去空白 + 截断）后的文本
     * @param charLen     清洗后字符数
     * @param truncated   是否因超过长度上限被截断
     * @param contentHash 清洗后文本的 SHA-256
     */
    private record ChunkRow(
            // 切片序号
            int index,
            // 原文
            String text,
            // 清洗后文本
            String textClean,
            // 字符数
            int charLen,
            // 是否截断
            boolean truncated,
            // 内容指纹
            String contentHash
    ) {
    }

    /**
     * 一条检索候选项：内存索引给出的切片 id 与相似度。
     *
     * @param chunkId 切片 id
     * @param score   余弦相似度
     */
    private record ScoredChunk(
            // 切片 id
            long chunkId,
            // 相似度
            double score
    ) {
    }
}
