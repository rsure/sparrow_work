// 模块说明：诊断接口，路径与 Python 侧 /api/diagnostic/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import jakarta.annotation.Resource;
import org.springframework.beans.factory.ObjectProvider;
// 响应实体：导出接口需要返回 zip 字节
import org.springframework.http.ResponseEntity;
// 媒体类型：zip 响应的 Content-Type
import org.springframework.http.MediaType;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /diagnostic
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 诊断业务接口：环境与依赖自检
import com.example.backendjava.service.DiagnosticService;
// 诊断接口的 DTO 容器
import com.example.backendjava.dto.DiagnosticDtos;

// 标准库：Map 用于诊断概要
import java.util.Map;

/**
 * 诊断接口。
 *
 * <p>Python 侧的 summary 返回裸 JSON，export 返回 zip 附件；这里保持兼容。</p>
 */
@RestController
@RequestMapping("/diagnostic")
public class DiagnosticController {

    /** 诊断服务；学习者实现后自动注入。 */
    @Resource
    private DiagnosticService diagnosticService;


    /**
     * 返回诊断概要。
     *
     * @return 诊断概要
     */
    @GetMapping("/summary")
    public Map<String, Object> summary() {
        return diagnosticService.summary();
    }

    /**
     * 导出诊断包。
     *
     * @return zip 响应
     */
    @GetMapping("/export")
    public ResponseEntity<byte[]> export() {
        DiagnosticDtos.DiagnosticPackage pkg =
                diagnosticService.export();
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType("application/zip"))
                // 同时给出 ASCII 与 UTF-8 文件名，兼容中文文件名
                .header("Content-Disposition",
                        "attachment; filename=" + pkg.filename()
                                + "; filename*=UTF-8''" + pkg.filename())
                // 跨域时默认只暴露少数响应头，前端需要读到文件名
                .header("Access-Control-Expose-Headers", "Content-Disposition")
                .body(pkg.content());
    }
}
