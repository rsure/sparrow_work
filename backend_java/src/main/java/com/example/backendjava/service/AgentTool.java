// 模块说明：Agent 工具接口。每个工具是一个原子能力，由 ToolRegistry 统一登记。
package com.example.backendjava.service;

// 标准库：Map 用于工具入参
import java.util.Map;

// 工具执行结果（成功/失败 + 输出）
import com.example.backendjava.dto.ToolResult;
// 工具安全策略枚举：是否需要用户确认
import com.example.backendjava.common.ToolPolicy;

/**
 * Agent 工具接口。
 *
 * <p>实现类建议放在 {@code service.impl} 包下（沿用「接口在 service、实现在 service.impl」的约定），
 * 一个文件一个工具；
 * 工具名、描述、参数说明都要写清楚，模型会直接读这些文字来决定是否调用。</p>
 */
public interface AgentTool {

    /**
     * 工具名：全局唯一，模型调用时使用。
     *
     * @return 工具名，如 read_file
     */
    String name();

    /**
     * 工具说明：告诉模型“什么时候该用它”。
     *
     * @return 一句话说明
     */
    String description();

    /**
     * 工具策略：是否需要用户确认、是否允许在子 Agent 中使用。
     *
     * @return 策略枚举
     */
    ToolPolicy policy();

    /**
     * 执行工具。
     *
     * @param arguments 工具入参；键名与工具描述保持一致
     * @return 执行结果
     */
    ToolResult execute(Map<String, Object> arguments);
}
