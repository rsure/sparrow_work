// 模块说明：工具注册表接口。Agent 建图前从这里取工具，并按策略做启动自检。
package com.example.backendjava.service;

// 标准库：List 用于工具清单
import java.util.List;
// 标准库：Optional 用于“可能找不到”
import java.util.Optional;

/**
 * 工具注册表接口。
 */
public interface ToolRegistry {

    /**
     * 返回全部已登记工具。
     *
     * @return 工具列表
     */
    List<AgentTool> list();

    /**
     * 按名称查找工具。
     *
     * @param name 工具名
     * @return 找到时返回工具；找不到时返回 Optional.empty()
     */
    Optional<AgentTool> find(String name);

    /**
     * 返回某个作用域可用的工具：主 Agent 可取全部，子 Agent 只取只读工具。
     *
     * @param subAgent true 表示子 Agent 作用域
     * @return 过滤后的工具列表
     */
    List<AgentTool> listForScope(boolean subAgent);
}
