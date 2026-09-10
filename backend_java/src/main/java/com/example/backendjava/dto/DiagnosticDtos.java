// 模块说明：诊断域的 DTO。
package com.example.backendjava.dto;

/**
 * 诊断域 DTO 集合。
 */
public final class DiagnosticDtos {

    /** 工具类禁止实例化。 */
    private DiagnosticDtos() {
    }

    /**
     * 诊断包。
     *
     * @param content  zip 文件字节
     * @param filename 后端建议的文件名（含 .zip）
     */
    public record DiagnosticPackage(
            // zip 字节
            byte[] content,
            // 文件名
            String filename
    ) {
    }
}
