// 模块说明：「任意文件尽量读成文本」的结果对象（对应 Python tool_utils.read_text_any 的返回元组）。
package com.example.backendjava.tools;

/**
 * 一次文本读取的结果。
 *
 * <p>文本为 {@code null} 表示"读不出正文"，此时说明里写清原因（二进制、文件过大、
 * 需要专用解析器等），调用方把说明与文件元信息一起回给模型。</p>
 *
 * @param text 读出的正文；无法读取时为 null
 * @param note 读取方式或失败原因的说明；用于回给模型，不应为 null
 */
public record TextReadResult(
        // 读出的正文；无法读取时为 null
        String text,
        // 读取方式或失败原因（例如「文本，编码 UTF-8」「二进制文件」）
        String note
) {
}
