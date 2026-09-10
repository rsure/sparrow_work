// 模块说明：MCP 客户端管理接口（对应 Python 的 EXT-2）。
package com.example.backendjava.service;

// 标准库：Map 用于动态快照与单条配置
import java.util.Map;

/**
 * MCP 服务接口。
 *
 * <p>实现建议：用 LangChain4j 的 {@code DefaultMcpClient} 建立 stdio / sse / streamable_http
 * 三种传输的连接，再用 {@code McpToolProvider} 把外部工具转成 LangChain4j Tool。</p>
 */
public interface McpService {

    /**
     * 列出各 MCP server 的连接状态与工具清单。
     *
     * @return 形如 {"enabled":bool,"servers":[...],"errors":[...],"tool_count":int}
     */
    Map<String, Object> snapshot();

    /**
     * 强制重新连接全部 MCP server。
     *
     * @return 重载后的快照
     */
    Map<String, Object> reload();

    /**
     * 试连一条 server 配置（不保存、不影响现有连接）。
     *
     * @param config 单条配置，结构同设置项 mcp.servers 的元素
     * @return 形如 {"ok":bool,"tools":[...],"error":str,"duration_ms":int}
     */
    Map<String, Object> test(Map<String, Object> config);
}
