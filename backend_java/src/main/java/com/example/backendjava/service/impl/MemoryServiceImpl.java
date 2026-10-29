// 模块说明：工作区记忆业务实现（对应 Python 侧 app/services/memory_service.py）。
//
// 数据流：一轮对话结束 ──► 裸模型抽「值得记住的一句话」──► 去重（哈希 + 余弦）──► 落 memories 表（含向量）
//         新对话开场  ──► 本地向量检索本工作区记忆 ──► 拼成提示注入给模型
//
// 三条刻意的设计选择（与 Python 侧保持一致）：
//   1. 向量存表、不建 FAISS 索引：记忆量级是「单工作区几十到几百条」，每次全取出来做一次内积就是毫秒级；
//   2. 抽取失败绝不影响对话：任何异常只写日志；
//   3. 近似重复时「合并」而不是丢弃（MEM 增强）。
package com.example.backendjava.service.impl;

// Jackson 树模型：解析模型返回的 JSON 数组（记忆抽取结果）
import com.fasterxml.jackson.databind.JsonNode;

// LangChain4j 同步聊天模型：抽取用（一次拿完整回答）
import dev.langchain4j.model.chat.ChatModel;
// LangChain4j 流式聊天模型：检索问答用（逐 token 推给 SSE）
import dev.langchain4j.model.chat.StreamingChatModel;
// LangChain4j 流式响应处理器：onPartialResponse / onCompleteResponse / onError
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.chat.response.StreamingChatResponseHandler;

// 日志
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为服务组件
import org.springframework.stereotype.Service;
// Spring MVC 的 SSE 发射器：检索问答是流式返回
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
// Jakarta 依赖注入：按类型注入字段，与项目现有写法保持一致
import jakarta.annotation.Resource;

// 标准库：IO 异常（SSE 发送失败）
import java.io.IOException;
// 标准库：时间戳（落库显式写入、过期淘汰的天数计算）
import java.time.LocalDateTime;
// 标准库：集合与流式处理
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.stream.Collectors;

// 项目内：业务异常（缺密钥 / 未知供应商时给可读提示）
import com.example.backendjava.common.ApiException;
// 项目内：limit 的默认值与上限契约表（与 Python 侧 app/core/limits.py 一一对应）
import com.example.backendjava.common.PageLimits;
// 项目内：模型供应商/模型 DTO（装配模型参数）
import com.example.backendjava.dto.LlmDtos;
// 项目内：装配模型实例所需的参数
import com.example.backendjava.dto.LlmModelSpec;
// 项目内：记忆接口的请求/响应 DTO
import com.example.backendjava.dto.MemoryDtos;
// 项目内：对话消息实体（抽取时读历史）
import com.example.backendjava.entity.ChatMessage;
// 项目内：记忆实体
import com.example.backendjava.entity.MemoryItem;
// 项目内：模型工厂路由（按供应商创建同步/流式模型）
import com.example.backendjava.llm.LlmModelFactoryRouter;
// 项目内：内置供应商清单（默认地址、密钥名、是否需要密钥）
import com.example.backendjava.llm.LlmProviderRegistry;
// 项目内：消息仓库（抽取时按会话取历史）
import com.example.backendjava.repository.ChatMessageRepository;
// 项目内：记忆仓库
import com.example.backendjava.repository.MemoryItemRepository;
// 项目内：记忆业务接口（本类实现它）
import com.example.backendjava.service.MemoryService;
// 项目内：设置服务（取当前 active 工作区 id）
import com.example.backendjava.service.SettingsService;
// 项目内：密钥仓库（取当前供应商的 API Key）
import com.example.backendjava.settings.SecretStore;
// 项目内：设置注册表（记忆相关设置的唯一读取入口）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：JSON 工具（SSE 帧序列化、抽取结果解析）
import com.example.backendjava.util.JsonUtils;

/**
 * 记忆服务实现。
 */
@Service
public class MemoryServiceImpl implements MemoryService {

    /** 日志：记录抽取失败、合并、整理等写侧动作。 */
    private static final Logger log = LoggerFactory.getLogger(MemoryServiceImpl.class);

    // ------------------------------------------------------------------ //
    // 常量（与 Python 侧 memory_service.py 对齐）
    // ------------------------------------------------------------------ //

    /** 记忆正文长度上限。 */
    private static final int MAX_CONTENT_CHARS = 500;

    /** 抽取时喂给模型的对话长度上限（user / assistant 各自）。 */
    private static final int MAX_INPUT_CHARS = 4000;

    /** 检索的最低相似度：低于它的命中不注入。 */
    private static final float MIN_SIMILARITY = 0.1f;

    /** 一次抽取最多接受多少条。 */
    private static final int MAX_EXTRACT_PER_TURN = 5;

    /** 记忆分类的合法取值。 */
    private static final Set<String> MEMORY_CATEGORIES = Set.of("preference", "decision", "fact", "todo");

    /** 记忆来源的合法取值。 */
    private static final Set<String> MEMORY_SOURCES = Set.of("auto", "manual");

    // ------------------------------------------------------------------ //
    // 依赖
    // ------------------------------------------------------------------ //

    /** 记忆仓库。 */
    @Resource
    private MemoryItemRepository memoryItemRepository;

    /** 消息仓库：抽取时按会话取历史。 */
    @Resource
    private ChatMessageRepository chatMessageRepository;

    /** 设置注册表：记忆相关设置的唯一读取入口。 */
    @Resource
    private SettingsRegistry settingsRegistry;

    /** 设置服务：取当前 active 工作区 id。 */
    @Resource
    private SettingsService settingsService;

    /** 模型工厂路由：按供应商创建同步/流式模型。 */
    @Resource
    private LlmModelFactoryRouter llmModelFactoryRouter;

    /** 内置供应商清单。 */
    @Resource
    private LlmProviderRegistry llmProviderRegistry;

    /** 密钥仓库。 */
    @Resource
    private SecretStore secretStore;

    /** 对话轮次线程池：把阻塞的模型调用挪出 Tomcat 线程。 */
    @Resource
    private ExecutorService chatTurnExecutor;

    /** 本地哈希向量化器：入库与检索共用同一套清洗 + 向量化逻辑。 */
    private final LocalHashEmbedder embedder = new LocalHashEmbedder();

    /** 抽取提示词模板。 */
    private static final String EXTRACT_PROMPT = """
            从下面这段对话里抽取「对未来对话有帮助、值得记住」的信息。

            要求：
            - 只抽**长期有效**的内容：用户的偏好、已确定的方案决策、关于项目或环境的事实、尚未完成的待办。
            - 不要抽：一次性的操作细节、寒暄、模型的自我描述、可以从代码里直接看出来的东西。
            - 每条写成一句陈述，不要"用户说""助手说"这种前缀，也不要 markdown。
            - category 只能是 preference（偏好）/ decision（决策）/ fact（事实）/ todo（待办）之一。
            - importance 是 1~5 的整数，5 表示"以后每次都要遵守"。
            - 最多 {max_items} 条；没有值得记的就输出空数组。

            只输出 JSON 数组，不要任何解释。格式：
            [{"content": "…", "category": "decision", "importance": 4}]

            【对话】
            用户：{user}

            助手：{assistant}
            """;

    /** 检索问答提示词模板。 */
    private static final String QUERY_PROMPT = """
            请只根据下面这些「工作区记忆」回答用户的问题。

            要求：
            - 只能使用记忆里的信息；记忆里没有的就说"记忆里没有相关信息"，不要编造。
            - 回答简洁，必要时用列表。
            - 不要复述记忆原文，直接回答问题。

            【工作区记忆】
            {memories}

            【问题】
            {question}
            """;

    // ------------------------------------------------------------------ //
    // 1. 设置读取（全部带兜底：读不到就走保守默认）
    // ------------------------------------------------------------------ //

    /** 读一个设置项，失败时返回默认值。 */
    private Object setting(String key, Object defaultValue) {
        try {
            Object value = settingsRegistry.getSetting(key);
            return value == null ? defaultValue : value;
        } catch (RuntimeException e) {
            return defaultValue;
        }
    }

    private boolean boolSetting(String key, boolean defaultValue) {
        Object value = setting(key, defaultValue);
        if (value instanceof Boolean b) {
            return b;
        }
        if (value instanceof Number n) {
            return n.intValue() != 0;
        }
        return Boolean.parseBoolean(String.valueOf(value));
    }

    private int intSetting(String key, int defaultValue) {
        Object value = setting(key, defaultValue);
        if (value instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            return defaultValue;
        }
    }

    private double doubleSetting(String key, double defaultValue) {
        Object value = setting(key, defaultValue);
        if (value instanceof Number n) {
            return n.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            return defaultValue;
        }
    }

    private boolean isEnabled() {
        return boolSetting("memory.enabled", true);
    }

    private boolean extractEnabled() {
        return isEnabled() && boolSetting("memory.extract_enabled", true);
    }

    private boolean injectEnabled() {
        return isEnabled() && boolSetting("memory.inject_enabled", true);
    }

    private int topKSetting() {
        return clamp(intSetting("memory.top_k", 5), 1, 20);
    }

    private int minImportance() {
        return clamp(intSetting("memory.min_importance", 1), 1, 5);
    }

    private double dedupThreshold() {
        return clamp(doubleSetting("memory.dedup_threshold", 0.85), 0.5, 1.0);
    }

    private boolean mergeEnabled() {
        return boolSetting("memory.merge_enabled", true);
    }

    private int ttlDays() {
        return clamp(intSetting("memory.ttl_days", 180), 0, 3650);
    }

    private int maxPerWorkspace() {
        return clamp(intSetting("memory.max_per_workspace", 500), 0, 5000);
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(value, max));
    }

    private static double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(value, max));
    }

    /** 当前向量化后端描述（Java 侧只实现本地哈希）。 */
    private String embeddingDescribe() {
        return "local";
    }

    // ------------------------------------------------------------------ //
    // 2. 工作区解析 / 时间 / 向量
    // ------------------------------------------------------------------ //

    /** 解析工作区：入参为空时取当前 active 工作区。 */
    private String resolveWorkspace(String workspaceId) {
        if (workspaceId != null && !workspaceId.isBlank()) {
            return workspaceId;
        }
        try {
            return settingsService.listWorkspaces().activeId();
        } catch (RuntimeException e) {
            return "";
        }
    }

    /** 当前时间戳（ISO-8601 字符串，与项目其它实体保持一致）。 */
    private String now() {
        return LocalDateTime.now().toString();
    }

    /** 正文的 SHA-256（完全相同的内容直接判定为重复）。 */
    private String contentHash(String text) {
        return embedder.sha256Hex(text == null ? "" : text.strip());
    }

    /** 文本 → 单位向量（本地哈希）。 */
    private float[] vectorize(String text) {
        return embedder.vectorize(text == null ? " " : text.strip());
    }

    /** 实体 → 向量；没有向量或解析失败返回 null。 */
    private float[] vectorOf(MemoryItem row) {
        if (row.getEmbedding() == null) {
            return null;
        }
        try {
            return embedder.fromBytes(row.getEmbedding());
        } catch (RuntimeException e) {
            return null;
        }
    }

    /** 写入向量并同步维度。 */
    private void applyEmbedding(MemoryItem row, float[] vector) {
        row.setEmbedding(embedder.toBytes(vector));
        row.setDim(vector.length);
    }

    /** 计算查询向量与若干记忆的余弦相似度；维度不符或没有向量记为 -1。 */
    private float[] cosineMatrix(float[] query, List<MemoryItem> rows) {
        float[] scores = new float[rows.size()];
        Arrays.fill(scores, -1.0f);
        for (int i = 0; i < rows.size(); i++) {
            float[] vector = vectorOf(rows.get(i));
            if (vector == null || vector.length != query.length) {
                continue;
            }
            double dot = 0.0;
            for (int j = 0; j < query.length; j++) {
                dot += (double) query[j] * vector[j];
            }
            scores[i] = (float) dot;
        }
        return scores;
    }

    /** 相似度与重要度合成排序分数。 */
    private static double scoring(double similarity, Integer importance) {
        int imp = importance == null ? 3 : Math.max(1, Math.min(importance, 5));
        return similarity * (0.5 + imp / 5.0);
    }

    // ------------------------------------------------------------------ //
    // 3. 读：列表 / 统计 / 检索
    // ------------------------------------------------------------------ //

    /** 实体 → 接口字典（不暴露向量本身）。 */
    private Map<String, Object> toDict(MemoryItem row, Double score) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", row.getId());
        data.put("workspace_id", row.getWorkspaceId());
        data.put("session_id", row.getSessionId());
        data.put("content", row.getContent());
        data.put("category", row.getCategory());
        data.put("importance", row.getImportance() == null ? 0 : row.getImportance());
        data.put("source", row.getSource());
        data.put("created_at", row.getCreatedAt());
        data.put("updated_at", row.getUpdatedAt());
        data.put("last_used_at", row.getLastUsedAt());
        data.put("use_count", row.getUseCount() == null ? 0 : row.getUseCount());
        data.put("merged_count", row.getMergedCount() == null ? 0 : row.getMergedCount());
        if (score != null) {
            data.put("score", Math.round(score * 10000.0) / 10000.0);
        }
        return data;
    }

    /** 按重要度、时间倒序排序。 */
    private static final Comparator<MemoryItem> BY_IMPORTANCE_TIME_DESC = (a, b) -> {
        int c = Integer.compare(importanceOf(b), importanceOf(a));
        if (c != 0) {
            return c;
        }
        c = descCompare(a.getCreatedAt(), b.getCreatedAt());
        if (c != 0) {
            return c;
        }
        return descCompare(a.getId(), b.getId());
    };

    private static int importanceOf(MemoryItem row) {
        return row.getImportance() == null ? 0 : row.getImportance();
    }

    private static int descCompare(String a, String b) {
        if (a == null && b == null) {
            return 0;
        }
        if (a == null) {
            return 1;
        }
        if (b == null) {
            return -1;
        }
        return b.compareTo(a);
    }

    @Override
    public Map<String, Object> list(String workspaceId, String category, int limit) {
        String wid = resolveWorkspace(workspaceId);
        List<MemoryItem> rows = new ArrayList<>(memoryItemRepository.findByWorkspaceId(wid));
        if (category != null && !category.isBlank()) {
            rows.removeIf(row -> !category.equals(row.getCategory()));
        }
        rows.sort(BY_IMPORTANCE_TIME_DESC);

        // 上限同样走契约表：以前这里的 500 是就地写死的，与 Python 侧没有共同来源
        int cap = PageLimits.clamp(limit, PageLimits.MAX_MEMORY);
        List<Map<String, Object>> memories = new ArrayList<>();
        for (MemoryItem row : rows) {
            if (memories.size() >= cap) {
                break;
            }
            memories.add(toDict(row, null));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workspace_id", wid);
        result.put("enabled", isEnabled());
        result.put("memories", memories);
        return result;
    }

    @Override
    public Map<String, Object> stats(String workspaceId) {
        String wid = resolveWorkspace(workspaceId);
        List<MemoryItem> rows = memoryItemRepository.findByWorkspaceId(wid);
        Map<String, Integer> byCategory = new LinkedHashMap<>();
        for (MemoryItem row : rows) {
            String cat = row.getCategory() == null ? "fact" : row.getCategory();
            byCategory.merge(cat, 1, Integer::sum);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workspace_id", wid);
        result.put("total", rows.size());
        result.put("by_category", byCategory);
        result.put("embedding", embeddingDescribe());
        return result;
    }

    @Override
    public Map<String, Object> search(MemoryDtos.MemorySearchRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        List<Map<String, Object>> hits = doSearch(wid, request.query(), request.topK());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workspace_id", wid);
        result.put("query", request.query() == null ? "" : request.query());
        result.put("hits", hits);
        return result;
    }

    /** 本地相似度检索的核心（不调 LLM、不花 token）。 */
    private List<Map<String, Object>> doSearch(String wid, String query, Integer topK) {
        String text = query == null ? "" : query.strip();
        if (text.isEmpty() || wid == null || wid.isEmpty()) {
            return List.of();
        }
        int k = topK == null || topK <= 0 ? topKSetting() : clamp(topK, 1, 50);
        int floor = minImportance();

        List<MemoryItem> candidates = new ArrayList<>();
        for (MemoryItem row : memoryItemRepository.findByWorkspaceId(wid)) {
            if (importanceOf(row) >= floor) {
                candidates.add(row);
            }
        }
        if (candidates.isEmpty()) {
            return List.of();
        }

        float[] queryVector = vectorize(text);
        float[] sims = cosineMatrix(queryVector, candidates);

        List<Hit> hits = new ArrayList<>();
        for (int i = 0; i < candidates.size(); i++) {
            double sim = sims[i];
            if (sim < MIN_SIMILARITY) {
                continue;
            }
            hits.add(new Hit(scoring(sim, candidates.get(i).getImportance()), candidates.get(i)));
        }
        hits.sort(Comparator.comparingDouble((Hit h) -> h.score).reversed());
        int top = Math.min(k, hits.size());

        // 记一次「被用到」：过期淘汰时据此判断哪条记忆还有价值（失败不影响返回结果）
        String usedAt = now();
        List<MemoryItem> touched = new ArrayList<>();
        for (int i = 0; i < top; i++) {
            MemoryItem row = hits.get(i).row;
            row.setUseCount((row.getUseCount() == null ? 0 : row.getUseCount()) + 1);
            row.setLastUsedAt(usedAt);
            touched.add(row);
        }
        if (!touched.isEmpty()) {
            try {
                memoryItemRepository.saveAll(touched);
            } catch (RuntimeException e) {
                log.debug("更新记忆使用记录失败", e);
            }
        }

        List<Map<String, Object>> results = new ArrayList<>();
        for (int i = 0; i < top; i++) {
            Hit hit = hits.get(i);
            // 实体已在上面把 use_count +1、last_used_at 置为本次时间，直接序列化即可
            results.add(toDict(hit.row, hit.score));
        }
        return results;
    }

    // ------------------------------------------------------------------ //
    // 4. 写：新增 / 删除 / 清空
    // ------------------------------------------------------------------ //

    @Override
    public Map<String, Object> create(MemoryDtos.MemoryCreateRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        Map<String, Object> memory = addMemory(
                wid, request.content(), request.category(), request.importance(), "manual", null);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("saved", memory != null);
        result.put("memory", memory);
        return result;
    }

    /** 保存一条记忆；与已有记忆几乎重复时合并进那一条。 */
    private Map<String, Object> addMemory(String workspaceId, String content,
                                          String category, int importance,
                                          String source, String sessionId) {
        String text = normalizeWhitespace(content);
        if (text.isEmpty()) {
            return null;
        }
        text = truncate(text, MAX_CONTENT_CHARS);
        String cat = MEMORY_CATEGORIES.contains(category) ? category : "fact";
        int imp = clamp(importance <= 0 ? 3 : importance, 1, 5);
        String src = MEMORY_SOURCES.contains(source) ? source : "auto";
        String digest = contentHash(text);

        List<MemoryItem> rows = memoryItemRepository.findByWorkspaceId(workspaceId);

        // 1) 完全相同的正文：直接判重
        for (MemoryItem row : rows) {
            if (digest.equals(row.getContentHash())) {
                return null;
            }
        }

        // 2) 近似重复：找出最像的一条，交给合并逻辑
        if (!rows.isEmpty()) {
            float[] vector = vectorize(text);
            float[] sims = cosineMatrix(vector, rows);
            int best = argmax(sims);
            if (best >= 0 && sims[best] >= dedupThreshold()) {
                if (!mergeEnabled()) {
                    log.debug("记忆近似重复，跳过（合并已关闭）：{}", preview(text));
                    return null;
                }
                Map<String, Object> merged = mergeInto(rows.get(best), text, cat, imp);
                memoryItemRepository.save(rows.get(best));
                merged.put("merged", true);
                log.info("记忆已合并进 #{}：{}", rows.get(best).getId(), preview(text));
                return merged;
            }
        }

        // 3) 新建一行
        String now = now();
        MemoryItem row = new MemoryItem();
        row.setId(UUID.randomUUID().toString());
        row.setWorkspaceId(workspaceId);
        row.setSessionId(sessionId);
        row.setContent(text);
        row.setCategory(cat);
        row.setImportance(imp);
        row.setSource(src);
        row.setContentHash(digest);
        row.setCreatedAt(now);
        row.setUpdatedAt(now);
        row.setUseCount(0);
        row.setMergedCount(0);
        applyEmbedding(row, vectorize(text));
        memoryItemRepository.save(row);

        Map<String, Object> data = toDict(row, null);
        data.put("merged", false);
        log.info("记忆已保存 [{}] {}", cat, preview(text));
        return data;
    }

    /** 把一条「几乎重复」的新内容合并进已有记忆（就地修改，返回合并后的字典）。 */
    private Map<String, Object> mergeInto(MemoryItem row, String text, String category, int importance) {
        String existing = row.getContent() == null ? "" : row.getContent();
        String newContent = text.length() > existing.length() ? text : (existing.isEmpty() ? text : existing);
        row.setContent(newContent);
        String existingCat = row.getCategory() == null ? "fact" : row.getCategory();
        if ("fact".equals(existingCat) && !"fact".equals(category)) {
            row.setCategory(category);
        }
        row.setImportance(Math.max(row.getImportance() == null ? 1 : row.getImportance(), importance));
        row.setMergedCount((row.getMergedCount() == null ? 0 : row.getMergedCount()) + 1);
        row.setUpdatedAt(now());
        row.setContentHash(contentHash(newContent));
        applyEmbedding(row, vectorize(newContent));
        return toDict(row, null);
    }

    @Override
    public Map<String, Object> delete(String memoryId) {
        boolean deleted = memoryItemRepository.existsById(memoryId);
        if (deleted) {
            memoryItemRepository.deleteById(memoryId);
        }
        return Map.of("deleted", deleted);
    }

    @Override
    public Map<String, Object> clear(String workspaceId) {
        String wid = resolveWorkspace(workspaceId);
        List<MemoryItem> rows = memoryItemRepository.findByWorkspaceId(wid);
        if (!rows.isEmpty()) {
            memoryItemRepository.deleteAll(rows);
        }
        return Map.of("removed", rows.size());
    }

    // ------------------------------------------------------------------ //
    // 5. 生命周期维护：过期淘汰 / 条数上限 / 向量重建
    // ------------------------------------------------------------------ //

    @Override
    public Map<String, Object> prune(MemoryDtos.MemoryMaintenanceRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        int days = ttlDays();
        int cap = maxPerWorkspace();
        int removedExpired = 0;
        int removedOverflow = 0;

        List<MemoryItem> rows = new ArrayList<>(memoryItemRepository.findByWorkspaceId(wid));
        rows.sort(Comparator.comparing(MemoryItem::getId));

        // 1) 时间淘汰（ttl_days=0 表示关闭）
        if (days > 0) {
            LocalDateTime cutoff = LocalDateTime.now().minusDays(days);
            List<MemoryItem> expired = new ArrayList<>();
            for (MemoryItem row : rows) {
                if ((row.getImportance() == null ? 3 : row.getImportance()) <= 2) {
                    String ts = row.getLastUsedAt() != null ? row.getLastUsedAt() : row.getCreatedAt();
                    if (isOlderThan(ts, cutoff)) {
                        expired.add(row);
                    }
                }
            }
            if (!expired.isEmpty()) {
                memoryItemRepository.deleteAll(expired);
                removedExpired = expired.size();
                Set<String> ids = expired.stream().map(MemoryItem::getId).collect(Collectors.toSet());
                rows.removeIf(row -> ids.contains(row.getId()));
            }
        }

        // 2) 数量上限（cap=0 表示不限制）
        if (cap > 0 && rows.size() > cap) {
            rows.sort(PRUNE_RANK);
            List<MemoryItem> overflow = new ArrayList<>(rows.subList(0, rows.size() - cap));
            if (!overflow.isEmpty()) {
                memoryItemRepository.deleteAll(overflow);
                removedOverflow = overflow.size();
                Set<String> ids = overflow.stream().map(MemoryItem::getId).collect(Collectors.toSet());
                rows.removeIf(row -> ids.contains(row.getId()));
            }
        }

        int total = rows.size();
        if (removedExpired > 0 || removedOverflow > 0) {
            log.info("记忆整理：过期 {} 条、超限 {} 条（工作区 {}，剩余 {} 条）",
                    removedExpired, removedOverflow, wid, total);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workspace_id", wid);
        result.put("removed", removedExpired + removedOverflow);
        result.put("removed_expired", removedExpired);
        result.put("removed_overflow", removedOverflow);
        result.put("total", total);
        return result;
    }

    /** 数量上限的排序键：重要度低、从没用过、最早创建的排前面（先被删）。 */
    private static final Comparator<MemoryItem> PRUNE_RANK = Comparator
            .comparingInt((MemoryItem row) -> row.getImportance() == null ? 1 : row.getImportance())
            .thenComparingInt((MemoryItem row) -> row.getLastUsedAt() == null ? 0 : 1)
            .thenComparing(row -> row.getCreatedAt() == null ? "" : row.getCreatedAt())
            .thenComparing(row -> row.getId() == null ? "" : row.getId());

    private static boolean isOlderThan(String ts, LocalDateTime cutoff) {
        if (ts == null) {
            return false;
        }
        try {
            return LocalDateTime.parse(ts).isBefore(cutoff);
        } catch (RuntimeException e) {
            return false;
        }
    }

    @Override
    public Map<String, Object> reindex(MemoryDtos.MemoryMaintenanceRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        boolean force = request.force();
        int probeDim = vectorize("dimension-probe").length;

        List<MemoryItem> rows = memoryItemRepository.findByWorkspaceId(wid);
        List<MemoryItem> pending = new ArrayList<>();
        for (MemoryItem row : rows) {
            int dim = row.getDim() == null ? -1 : row.getDim();
            if (force || row.getEmbedding() == null || dim != probeDim) {
                pending.add(row);
            }
        }
        for (MemoryItem row : pending) {
            applyEmbedding(row, vectorize(row.getContent() == null ? " " : row.getContent()));
        }
        if (!pending.isEmpty()) {
            memoryItemRepository.saveAll(pending);
        }

        int updated = pending.size();
        log.info("记忆向量重建：{} 条（工作区 {}，维度 {}）", updated, wid, probeDim);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workspace_id", wid);
        result.put("total", rows.size());
        result.put("updated", updated);
        result.put("skipped", rows.size() - updated);
        result.put("dim", probeDim);
        result.put("embedding", embeddingDescribe());
        return result;
    }

    // ------------------------------------------------------------------ //
    // 6. 抽取（一次裸模型调用）
    // ------------------------------------------------------------------ //

    @Override
    public Map<String, Object> extract(MemoryDtos.MemoryExtractRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        List<Map<String, Object>> stored = extractFromSession(request.sessionId(), wid);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("stored", stored);
        return result;
    }

    /** 对一个已有会话的最后 1~2 轮做抽取。 */
    private List<Map<String, Object>> extractFromSession(String sessionId, String wid) {
        if (!extractEnabled() || wid == null || wid.isEmpty()) {
            return List.of();
        }
        List<ChatMessage> messages = chatMessageRepository.findBySessionIdOrderByIdAsc(sessionId);
        if (messages.size() < 2) {
            return List.of();
        }

        String userText = "";
        String answerText = "";
        for (int i = messages.size() - 1; i >= 0; i--) {
            ChatMessage msg = messages.get(i);
            String role = msg.getRole();
            String content = msg.getContent() == null ? "" : msg.getContent();
            if (answerText.isEmpty() && "assistant".equals(role) && !content.isBlank()) {
                answerText = content;
                continue;
            }
            if (!answerText.isEmpty() && "user".equals(role) && !content.isBlank()) {
                userText = content;
                break;
            }
        }
        if (userText.isEmpty() || answerText.isEmpty()) {
            return List.of();
        }
        return extractAndStore(wid, sessionId, userText, answerText);
    }

    /** 用裸模型抽一轮对话里的记忆并落库（写侧主入口）。 */
    private List<Map<String, Object>> extractAndStore(String wid, String sessionId,
                                                      String userMessage, String answer) {
        if (normalizeWhitespace(userMessage).isEmpty() || normalizeWhitespace(answer).isEmpty()) {
            return List.of();
        }

        String prompt = buildExtractPrompt(userMessage, answer, MAX_EXTRACT_PER_TURN);
        String text;
        try {
            ChatModel model = llmModelFactoryRouter.createChatModel(buildModelSpec());
            text = model.chat(prompt);
        } catch (Exception e) {
            // 抽取失败是纯损耗，不能影响任何用户可见的行为
            log.warn("记忆抽取调用失败，本轮不记", e);
            return List.of();
        }

        List<Map<String, Object>> stored = new ArrayList<>();
        for (Map<String, Object> item : parseMemories(text, MAX_EXTRACT_PER_TURN)) {
            String content = (String) item.get("content");
            String category = (String) item.get("category");
            int importance = ((Number) item.get("importance")).intValue();
            try {
                Map<String, Object> saved = addMemory(wid, content, category, importance, "auto", sessionId);
                if (saved != null) {
                    stored.add(saved);
                }
            } catch (Exception e) {
                log.warn("写入记忆失败：{}", preview(content), e);
            }
        }
        if (!stored.isEmpty()) {
            log.info("本轮新增 {} 条记忆（会话 {}）", stored.size(), sessionId);
            try {
                prune(new MemoryDtos.MemoryMaintenanceRequest(wid, false));
            } catch (Exception e) {
                log.warn("记忆整理失败，本轮跳过（不影响已保存的记忆）", e);
            }
        }
        return stored;
    }

    private String buildExtractPrompt(String userMessage, String answer, int maxItems) {
        return EXTRACT_PROMPT
                .replace("{max_items}", String.valueOf(maxItems))
                .replace("{user}", truncate((userMessage == null ? "" : userMessage).strip(), MAX_INPUT_CHARS))
                .replace("{assistant}", truncate((answer == null ? "" : answer).strip(), MAX_INPUT_CHARS));
    }

    /** 去掉 ```json … ``` 围栏并截出最外层的 JSON 数组。 */
    private static String stripFence(String text) {
        String cleaned = (text == null ? "" : text).replace("```json", "").replace("```", "");
        int start = cleaned.indexOf('[');
        int end = cleaned.lastIndexOf(']');
        if (start < 0 || end <= start) {
            return "[]";
        }
        return cleaned.substring(start, end + 1);
    }

    /** 解析模型返回的 JSON 数组，逐条校验并清洗。 */
    private List<Map<String, Object>> parseMemories(String text, int maxItems) {
        String raw = stripFence(text);
        JsonNode node;
        try {
            node = JsonUtils.readTree(raw);
        } catch (RuntimeException e) {
            log.info("记忆抽取结果不是合法 JSON，本轮不记");
            return List.of();
        }
        if (node != null && node.isObject()) {
            node = node.has("memories") ? node.get("memories") : node.get("items");
        }
        if (node == null || !node.isArray()) {
            return List.of();
        }

        List<Map<String, Object>> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (JsonNode item : node) {
            if (!item.isObject()) {
                continue;
            }
            String content = normalizeWhitespace(textOf(item.get("content")));
            if (content.isEmpty()) {
                continue;
            }
            content = truncate(content, MAX_CONTENT_CHARS);
            String digest = contentHash(content);
            if (!seen.add(digest)) {
                continue;
            }
            String category = textOf(item.get("category")).toLowerCase();
            category = category.isEmpty() ? "fact" : category;
            int importance = 3;
            JsonNode impNode = item.get("importance");
            if (impNode != null && impNode.isNumber()) {
                importance = impNode.asInt();
            } else if (impNode != null && impNode.isTextual()) {
                try {
                    importance = Integer.parseInt(impNode.asText().trim());
                } catch (NumberFormatException e) {
                    importance = 3;
                }
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("content", content);
            entry.put("category", MEMORY_CATEGORIES.contains(category) ? category : "fact");
            entry.put("importance", clamp(importance, 1, 5));
            out.add(entry);
            if (out.size() >= maxItems) {
                break;
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ //
    // 7. 检索问答（SSE 流式）
    // ------------------------------------------------------------------ //

    @Override
    public SseEmitter query(MemoryDtos.MemorySearchRequest request) {
        SseEmitter emitter = new SseEmitter(300_000L);
        String traceId = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        chatTurnExecutor.submit(() -> streamQuery(emitter, traceId, request));
        return emitter;
    }

    /** 真正的检索问答流：先本地取证据，再让模型基于证据逐 token 作答。 */
    private void streamQuery(SseEmitter emitter, String traceId, MemoryDtos.MemorySearchRequest request) {
        String wid = resolveWorkspace(request.workspaceId());
        try {
            List<Map<String, Object>> hits = doSearch(wid, request.query(), request.topK());
            emit(emitter, "thinking", traceId, Map.of(
                    "stage", "searching",
                    "text", "在 " + hits.size() + " 条相关记忆里查找…",
                    "hits", hits.size()));
            if (hits.isEmpty()) {
                String answer = "记忆里没有相关信息。";
                emit(emitter, "token", traceId, Map.of("text", answer));
                emit(emitter, "done", traceId, Map.of("answer", answer, "hits", List.of()));
                completeQuietly(emitter);
                return;
            }

            String block = hits.stream()
                    .map(h -> "- [" + h.get("category") + "] " + h.get("content"))
                    .collect(Collectors.joining("\n"));
            String prompt = QUERY_PROMPT
                    .replace("{memories}", block)
                    .replace("{question}", request.query());

            StreamingChatModel model = llmModelFactoryRouter.createStreamingModel(buildModelSpec());
            StringBuilder collected = new StringBuilder();
            model.chat(prompt, new StreamingChatResponseHandler() {
                @Override
                public void onPartialResponse(String partial) {
                    if (partial != null) {
                        collected.append(partial);
                        emit(emitter, "token", traceId, Map.of("text", partial));
                    }
                }

                @Override
                public void onCompleteResponse(ChatResponse completeResponse) {
                    emit(emitter, "done", traceId, Map.of("answer", collected.toString(), "hits", hits));
                    completeQuietly(emitter);
                }

                @Override
                public void onError(Throwable error) {
                    emit(emitter, "error", traceId, Map.of("message",
                            "记忆问答失败：" + (error == null ? "未知错误" : error.getMessage())));
                    completeQuietly(emitter);
                }
            });
        } catch (Exception e) {
            emit(emitter, "error", traceId, Map.of("message", "记忆问答失败：" + e.getMessage()));
            completeQuietly(emitter);
        }
    }

    /** 把一条事件编码成 SSE 帧（与 Python 侧 memory_controller._frame 对齐）。 */
    private void emit(SseEmitter emitter, String event, String traceId, Map<String, Object> data) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("trace_id", traceId);
        payload.put("ts", System.currentTimeMillis() / 1000.0);
        payload.putAll(data);
        try {
            emitter.send(SseEmitter.event().name(event).data(JsonUtils.toJson(payload)));
        } catch (IOException | IllegalStateException e) {
            log.debug("SSE 发送失败（客户端可能已断开）：{}", e.getMessage());
        }
    }

    private void completeQuietly(SseEmitter emitter) {
        try {
            emitter.complete();
        } catch (IllegalStateException e) {
            // 已经完成或关闭：忽略
        }
    }

    // ------------------------------------------------------------------ //
    // 8. 模型参数装配（与 ChatServiceImpl.buildModelSpec 一致）
    // ------------------------------------------------------------------ //

    /** 按当前设置装配一个模型所需的参数。 */
    private LlmModelSpec buildModelSpec() {
        String providerId = String.valueOf(settingsRegistry.getSetting("llm.provider"));
        String modelName = String.valueOf(settingsRegistry.getSetting("llm.model")).trim();

        LlmDtos.ProviderInfo provider = llmProviderRegistry.findProvider(providerId)
                .orElseThrow(() -> new ApiException(404, "未知的模型供应商：" + providerId));

        if (modelName.isEmpty()) {
            if (provider.models().isEmpty()) {
                throw new ApiException(404, "供应商 " + providerId + " 还没有配置任何模型");
            }
            modelName = provider.models().get(0).model();
        }

        String apiKey = null;
        if (provider.secretKey() != null && !provider.secretKey().isBlank()) {
            apiKey = secretStore.getSecret(provider.secretKey()).orElse(null);
        }
        if (provider.requiresKey() && (apiKey == null || apiKey.isBlank())) {
            throw new ApiException(400, "尚未配置 " + provider.label() + " 的 API 密钥，"
                    + "请到设置页的「模型」分区填写（对应设置项：" + provider.secretKey() + "）");
        }

        // 接口地址：自定义端点用自己的地址，内置供应商保持「全局配置优先」
        String configuredBaseUrl = String.valueOf(settingsRegistry.getSetting("llm.base_url"));
        String baseUrl = provider.isCustom()
                ? provider.baseUrl()
                : (configuredBaseUrl.isBlank() ? provider.baseUrl() : configuredBaseUrl.trim());

        double temperature = ((Number) settingsRegistry.getSetting("llm.temperature")).doubleValue();
        int configuredMaxTokens = ((Number) settingsRegistry.getSetting("llm.max_tokens")).intValue();
        Integer maxTokens = configuredMaxTokens > 0 ? configuredMaxTokens : null;

        return new LlmModelSpec(providerId, modelName, apiKey, baseUrl, temperature, maxTokens);
    }

    // ------------------------------------------------------------------ //
    // 9. 文本工具
    // ------------------------------------------------------------------ //

    private static String normalizeWhitespace(String text) {
        if (text == null) {
            return "";
        }
        return text.trim().replaceAll("\\s+", " ");
    }

    private static String truncate(String text, int max) {
        return text.length() <= max ? text : text.substring(0, max);
    }

    private static String preview(String text) {
        String one = normalizeWhitespace(text);
        return one.length() <= 40 ? one : one.substring(0, 40);
    }

    private static String textOf(JsonNode node) {
        if (node == null || node.isNull()) {
            return "";
        }
        return node.asText();
    }

    private static int argmax(float[] arr) {
        int best = -1;
        float bestValue = -2.0f;
        for (int i = 0; i < arr.length; i++) {
            if (arr[i] > bestValue) {
                bestValue = arr[i];
                best = i;
            }
        }
        return best;
    }

    /** 一条检索候选项：合成排序分数 + 命中行。 */
    private record Hit(double score, MemoryItem row) {
    }
}
