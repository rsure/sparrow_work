// 模块说明：本地哈希向量化（对应 Python 侧 rag_store_service.py 的 vectorize / _clean / _hash_index）。
// 不依赖任何外部模型或网络：把字符 2-gram 计数到固定维度的哈希桶，再做 L2 归一化。
package com.example.backendjava.service.impl;

// LangChain4j 向量对象：把 float[] 包装成 EmbeddingStore 能接收的形态
import dev.langchain4j.data.embedding.Embedding;

// 标准库：ByteBuffer 负责 float[] 与 BLOB 字节的互相转换
import java.nio.ByteBuffer;
// 标准库：ByteOrder 固定小端序，保证跨平台写入的 BLOB 可读回
import java.nio.ByteOrder;
// 标准库：StandardCharsets 明确按 UTF-8 编码文本
import java.nio.charset.StandardCharsets;
// 标准库：MD5 只用于「稳定地映射到哈希桶」，不承担任何安全职责
import java.security.MessageDigest;
// 标准库：NoSuchAlgorithmException 表示 JVM 缺少 MD5（正常不会发生）
import java.security.NoSuchAlgorithmException;
// 标准库：HexFormat 把 SHA-256 字节转成 64 位十六进制字符串
import java.util.HexFormat;
// 标准库：ArrayList 收集 n-gram
import java.util.ArrayList;
// 标准库：List 返回 n-gram 列表
import java.util.List;
// 标准库：Locale 统一小写转换规则，避免土耳其语等地区的特殊行为
import java.util.Locale;

/**
 * 本地哈希向量化器。
 *
 * <p>优点：零依赖、纯 CPU、结果稳定；缺点：只做「字面近似」匹配，没有真正 embedding
 * 模型的语义理解能力。教学阶段先用它把整条链路跑通，后续换成真模型时只需替换本类，
 * 并同步修改 {@link #MODEL_NAME} 与 {@link #VECTOR_DIM}（换维度必须重建索引）。</p>
 */
final class LocalHashEmbedder {

    /** 向量维度（哈希桶个数）：越大区分度越高，内存与计算成本也越大。 */
    static final int VECTOR_DIM = 512;

    /** 向量化「模型」标识：写入 rag_chunk.model 与 rag_index_meta，用于识别不兼容向量。 */
    static final String MODEL_NAME = "local-hash-v1";

    /** 单个切片参与向量化的最大字符数，超出部分截断（避免哈希一个巨大字符串）。 */
    static final int CHAR_LIMIT = 20_000;

    /**
     * 向量化前清洗文本：去首尾空白；空串换成单个空格；超长截断。
     *
     * @param text  原始文本
     * @param limit 截断上限（字符数）
     * @return 清洗后的文本；保证非空
     */
    String clean(String text, int limit) {
        String stripped = text == null ? "" : text.strip();
        if (stripped.isEmpty()) {
            // 下游向量化逻辑遇到空文本会得到全零向量，明确换成空格更符合 Python 侧行为
            return " ";
        }
        return stripped.length() > limit ? stripped.substring(0, limit) : stripped;
    }

    /**
     * 把文本转成 L2 归一化后的向量。
     *
     * @param text 待向量化文本（调用方应先 {@link #clean(String, int)}）
     * @return 长度固定为 {@link #VECTOR_DIM} 的 float 数组；文本没有 n-gram 时返回全零向量
     */
    float[] vectorize(String text) {
        float[] vector = new float[VECTOR_DIM];
        for (String gram : charNgrams(text, 2)) {
            vector[hashIndex(gram, VECTOR_DIM)] += 1.0f;
        }
        // 归一化后两个向量的点积就等于余弦相似度，内存索引用点积即可做余弦检索
        double norm = 0.0;
        for (float value : vector) {
            norm += value * value;
        }
        if (norm > 0.0) {
            float scale = (float) (1.0 / Math.sqrt(norm));
            for (int i = 0; i < vector.length; i++) {
                vector[i] *= scale;
            }
        }
        return vector;
    }

    /**
     * 把文本转成 LangChain4j 的 Embedding 对象。
     *
     * @param text 待向量化文本
     * @return Embedding 实例
     */
    Embedding embed(String text) {
        return Embedding.from(vectorize(clean(text, CHAR_LIMIT)));
    }

    /**
     * float 数组 → 小端 float32 字节（写入 SQLite BLOB 的格式）。
     *
     * @param vector 向量
     * @return 长度为 vector.length × 4 的字节数组
     */
    byte[] toBytes(float[] vector) {
        ByteBuffer buffer = ByteBuffer.allocate(vector.length * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        for (float value : vector) {
            buffer.putFloat(value);
        }
        return buffer.array();
    }

    /**
     * 小端 float32 字节 → float 数组（从 SQLite BLOB 还原向量）。
     *
     * @param bytes 字节数组
     * @return 向量
     * @throws IllegalArgumentException 字节数不是 4 的整数倍
     */
    float[] fromBytes(byte[] bytes) {
        if (bytes == null || bytes.length % Float.BYTES != 0) {
            throw new IllegalArgumentException("向量 BLOB 长度不合法：" + (bytes == null ? "null" : bytes.length));
        }
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        float[] vector = new float[bytes.length / Float.BYTES];
        for (int i = 0; i < vector.length; i++) {
            vector[i] = buffer.getFloat();
        }
        return vector;
    }

    /**
     * 计算字节内容的 SHA-256（文档级 / 切片级内容指纹）。
     *
     * @param bytes 字节内容
     * @return 64 位十六进制摘要
     */
    String sha256Hex(byte[] bytes) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            // JVM 规范要求必须支持 SHA-256；走到这里说明运行环境异常
            throw new IllegalStateException("当前 JVM 不支持 SHA-256", e);
        }
    }

    /**
     * 计算文本内容的 SHA-256（按 UTF-8 编码）。
     *
     * @param text 文本
     * @return 64 位十六进制摘要
     */
    String sha256Hex(String text) {
        return sha256Hex((text == null ? "" : text).getBytes(StandardCharsets.UTF_8));
    }

    /**
     * 把文本切成字符级 n-gram（默认 2-gram，适合中文这类无空格分词的语言）。
     *
     * <p>用 codePoints 而不是 charAt，避免把 emoji 等代理对拆成两个半字符。</p>
     *
     * @param text 输入文本（内部统一转小写）
     * @param n    gram 长度
     * @return n-gram 列表；文本长度不足 n 时整体作为一个 gram，空文本返回空列表
     */
    private List<String> charNgrams(String text, int n) {
        if (text == null || text.isEmpty()) {
            return List.of();
        }
        String lower = text.toLowerCase(Locale.ROOT);
        int[] codePoints = lower.codePoints().toArray();
        if (codePoints.length < n) {
            return List.of(lower);
        }
        List<String> grams = new ArrayList<>(codePoints.length - n + 1);
        for (int i = 0; i + n <= codePoints.length; i++) {
            grams.add(new String(codePoints, i, n));
        }
        return grams;
    }

    /**
     * 把 token 稳定映射到 [0, dim) 的哈希桶（feature hashing）。
     *
     * <p>用 MD5 而不是 {@link String#hashCode()}：后者在不同 JVM 进程里不保证一致，
     * 持久化的向量会在下次启动后失效。取摘要前 4 字节按大端转无符号数再取模。</p>
     *
     * @param token 待映射的 n-gram
     * @param dim   桶数量
     * @return 桶下标
     */
    private int hashIndex(String token, int dim) {
        try {
            MessageDigest digest = MessageDigest.getInstance("MD5");
            byte[] bytes = digest.digest(token.getBytes(StandardCharsets.UTF_8));
            long value = ((long) (bytes[0] & 0xFF) << 24)
                    | ((long) (bytes[1] & 0xFF) << 16)
                    | ((long) (bytes[2] & 0xFF) << 8)
                    | (bytes[3] & 0xFFL);
            return (int) (value % dim);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("当前 JVM 不支持 MD5", e);
        }
    }

}
