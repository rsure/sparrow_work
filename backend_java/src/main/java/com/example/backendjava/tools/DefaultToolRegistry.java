// 模块说明：工具注册表实现（对应 Python policy.py 的 POLICIES 启动自检思路）。
package com.example.backendjava.tools;

// 标准库：LinkedHashMap 保持注入顺序，便于诊断接口稳定输出
import java.util.LinkedHashMap;
// 标准库：List 返回工具清单
import java.util.List;
// 标准库：Map 保存工具名 -> 工具实例
import java.util.Map;
// 标准库：Optional 表达「可能找不到」
import java.util.Optional;
// 第三方（Spring）：声明为受管组件；构造器注入会自动收集全部 AgentTool Bean
import org.springframework.stereotype.Component;
// 项目内：工具安全策略枚举
import com.example.backendjava.common.ToolPolicy;
// 项目内：Agent 工具接口
import com.example.backendjava.service.AgentTool;
// 项目内：工具注册表接口
import com.example.backendjava.service.ToolRegistry;

/**
 * 工具注册表实现：Spring 会把所有 {@link AgentTool} 实现自动注入到构造器。
 */
@Component
public class DefaultToolRegistry implements ToolRegistry {

    /** 工具名 -> 工具实例。 */
    private final Map<String, AgentTool> tools = new LinkedHashMap<>();

    /**
     * 构造器：收集全部工具并做「重名 + 未登记策略」自检。
     *
     * @param toolList Spring 注入的全部工具 Bean
     * @param policyRegistry 策略注册表
     * @throws IllegalStateException 工具重名，或有工具没有登记安全策略（启动即失败）
     */
    public DefaultToolRegistry(List<AgentTool> toolList, ToolPolicyRegistry policyRegistry) {
        for (AgentTool tool : toolList) {
            if (tools.putIfAbsent(tool.name(), tool) != null) {
                throw new IllegalStateException("工具名重复：" + tool.name()
                        + "；工具名必须全局唯一，否则模型无法区分");
            }
            // 启动自检：没登记策略的工具一律不允许上线（与 Python verify_all_tools_registered 一致）
            if (policyRegistry.find(tool.name()).isEmpty()) {
                throw new IllegalStateException("工具 " + tool.name()
                        + " 没有登记安全策略，拒绝启动");
            }
        }
    }

    /**
     * 返回全部已登记工具。
     *
     * @return 工具列表（按注入顺序）
     */
    @Override
    public List<AgentTool> list() {
        return List.copyOf(tools.values());
    }

    /**
     * 按名称查找工具。
     *
     * @param name 工具名
     * @return 找到时返回工具；找不到时为空
     */
    @Override
    public Optional<AgentTool> find(String name) {
        return Optional.ofNullable(tools.get(name));
    }

    /**
     * 返回某个作用域可用的工具：子 Agent 只拿只读工具。
     *
     * @param subAgent true 表示子 Agent 作用域
     * @return 过滤后的工具列表
     */
    @Override
    public List<AgentTool> listForScope(boolean subAgent) {
        if (!subAgent) {
            return list();
        }
        return tools.values().stream()
                .filter(tool -> tool.policy() == ToolPolicy.READ_ONLY)
                .toList();
    }
}
