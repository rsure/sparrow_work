// 模块说明：文件预览域的 DTO。
package com.example.backendjava.dto;

/**
 * 文件域 DTO 集合。
 */
public final class FileDtos {

    /** 工具类禁止实例化。 */
    private FileDtos() {
    }

    /**
     * 原样返回的文件内容。
     *
     * @param content     文件字节
     * @param contentType MIME 类型，如 image/png；未知时可为 application/octet-stream
     */
    public record RawFile(
            // 文件字节
            byte[] content,
            // MIME 类型
            String contentType
    ) {
    }
}
