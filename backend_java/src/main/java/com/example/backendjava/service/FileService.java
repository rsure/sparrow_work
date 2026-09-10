// 模块说明：文件预览业务接口。实现时必须复用工作区白名单校验，避免成为任意文件读取入口。
package com.example.backendjava.service;

// 标准库：List 用于批量路径与搜索结果
import java.util.List;
// 标准库：Map 用于动态预览结果
import java.util.Map;

// 文件接口的 DTO 容器
import com.example.backendjava.dto.FileDtos;

/**
 * 文件服务接口。
 */
public interface FileService {

    /**
     * 把一批路径转成文件清单（类型、大小、能否预览）。
     *
     * @param paths 文件绝对路径列表
     * @return 文件清单
     */
    List<Map<String, Object>> catalog(List<String> paths);

    /**
     * 读取文本预览内容。
     *
     * @param path     文件绝对路径
     * @param maxChars 最多返回多少字符
     * @return 形如 {"path","content","truncated",...} 的预览结果
     */
    Map<String, Object> preview(String path, int maxChars);

    /**
     * 在当前工作区内按文件名/相对路径搜索。
     *
     * @param query 搜索关键词；空表示随便列一些
     * @param limit 最多返回多少条
     * @return 形如 {"files":[...]} 的搜索结果
     */
    Map<String, Object> search(String query, int limit);

    /**
     * 原样读取文件内容（用于图片等）。
     *
     * @param path 文件绝对路径
     * @return 文件字节与 MIME 类型
     */
    FileDtos.RawFile raw(String path);
}
