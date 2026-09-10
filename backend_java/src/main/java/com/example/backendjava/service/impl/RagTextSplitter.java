// 模块说明：RAG 文本切分器（对应 Python 侧 rag_store_service.py 的 default_splitter）。
// 先按「段落 → 换行 → 中文标点 → 空格 → 单字符」递归切开，再把小片段合并到接近 chunk_size。
package com.example.backendjava.service.impl;

// 标准库：ArrayList 收集切片
import java.util.ArrayList;
// 标准库：List 分隔符表与返回结果
import java.util.List;

/**
 * 递归文本切分器。
 *
 * <p>为什么不用固定长度硬切：一句话被切成两半后，两边的语义都不完整，
 * 检索命中时给出的片段会读不懂。先按最像语义边界的位置切，再合并，效果更稳。</p>
 */
final class RagTextSplitter {

    /**
     * 分隔符优先级：从「最像语义边界」到「最不像」，最后一项空串表示按字符兜底硬切。
     *
     * <p>中文标点放在空格之前，是因为中文通常没有空格分词。</p>
     */
    private static final List<String> SEPARATORS = List.of(
            "\n\n", "\n", "。", "！", "？", "；", "，", " ", ""
    );

    /**
     * 把全文切成若干片段。
     *
     * @param text      全文
     * @param chunkSize 每个片段的最大字符数
     * @param overlap   相邻片段的重叠字符数，避免一句话被切断后上下文丢失
     * @return 片段列表；空文本返回空列表
     */
    List<String> split(String text, int chunkSize, int overlap) {
        int size = Math.max(1, chunkSize);
        int overlapSize = Math.max(0, Math.min(overlap, size - 1));
        String stripped = text == null ? "" : text.strip();
        if (stripped.isEmpty()) {
            return List.of();
        }
        // 第一步：递归切到每个片段都不超过 size
        List<String> pieces = recursiveSplit(stripped, 0, size);
        // 第二步：把小片段合并成接近 size 的块，并在块之间保留 overlap
        return merge(pieces, size, overlapSize);
    }

    /**
     * 用第 index 个分隔符切分；某个片段仍超长时换下一个分隔符继续切。
     *
     * @param text  待切分文本
     * @param index 当前使用的分隔符下标
     * @param size  片段最大字符数
     * @return 每个都不超过 size 的片段列表
     */
    private List<String> recursiveSplit(String text, int index, int size) {
        if (text.length() <= size) {
            return List.of(text);
        }
        if (index >= SEPARATORS.size()) {
            // 理论上不会走到这里：最后一项是空串，已经由 hardSplit 兜底
            return hardSplit(text, size);
        }
        String separator = SEPARATORS.get(index);
        List<String> parts = separator.isEmpty()
                ? hardSplit(text, size)
                : splitKeepingEnd(text, separator);
        List<String> result = new ArrayList<>();
        for (String part : parts) {
            if (part.isEmpty()) {
                continue;
            }
            if (part.length() <= size) {
                result.add(part);
            } else {
                result.addAll(recursiveSplit(part, index + 1, size));
            }
        }
        return result;
    }

    /**
     * 按分隔符切分，并把分隔符留在前一段末尾（对应 Python 的 keep_separator="end"）。
     *
     * <p>标点留在句尾而不是跑到下一段开头，片段读起来更自然。</p>
     *
     * @param text      待切分文本
     * @param separator 分隔符
     * @return 片段列表
     */
    private List<String> splitKeepingEnd(String text, String separator) {
        List<String> parts = new ArrayList<>();
        int start = 0;
        int index;
        while ((index = text.indexOf(separator, start)) >= 0) {
            int end = index + separator.length();
            parts.add(text.substring(start, end));
            start = end;
        }
        if (start < text.length()) {
            parts.add(text.substring(start));
        }
        return parts;
    }

    /**
     * 按固定长度硬切（所有分隔符都切不动时的最后兜底）。
     *
     * @param text 待切分文本
     * @param size 片段最大字符数
     * @return 片段列表
     */
    private List<String> hardSplit(String text, int size) {
        List<String> parts = new ArrayList<>();
        for (int start = 0; start < text.length(); start += size) {
            parts.add(text.substring(start, Math.min(text.length(), start + size)));
        }
        return parts;
    }

    /**
     * 贪心合并相邻片段，并在上一片段末尾保留 overlap 个字符作为下一片段的开头。
     *
     * @param pieces   已经不超过 size 的片段
     * @param size     每个片段的最大字符数
     * @param overlap  需要保留的重叠字符数
     * @return 合并后的切片列表
     */
    private List<String> merge(List<String> pieces, int size, int overlap) {
        List<String> merged = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        for (String piece : pieces) {
            if (current.length() == 0) {
                current.append(piece);
                continue;
            }
            if (current.length() + piece.length() <= size) {
                current.append(piece);
                continue;
            }
            // 当前块装不下了：先落盘，再用它的末尾 overlap 个字符开始下一块
            String finished = current.toString();
            merged.add(finished);
            // 保证 overlap + 新片段不会超过 size（片段本身可能刚好等于 size）
            int keep = Math.min(overlap, Math.max(0, size - piece.length()));
            String tail = keep == 0 ? "" : finished.substring(finished.length() - keep);
            current.setLength(0);
            current.append(tail).append(piece);
        }
        if (current.length() > 0) {
            merged.add(current.toString());
        }
        return merged;
    }
}
