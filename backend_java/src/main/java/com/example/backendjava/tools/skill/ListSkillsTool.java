// 模块说明：list_skills 工具（对应 Python skill_tool.py 的 list_skills）。
package com.example.backendjava.tools.skill;

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）

// 标准库：ArrayList 结果行
import java.util.ArrayList;
// 标准库：List 技能清单与待校验路径
import java.util.List;
// 标准库：Map 技能快照与弹窗参数
import java.util.Map;
// 第三方（Spring）：延迟获取可选 Bean（技能服务可能尚未实现）
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：技能服务接口
import com.example.backendjava.service.SkillService;

/**
 * 列出本机已安装的技能（名字、一句话说明、声明会用到的工具）。
 */
@Component
public class ListSkillsTool extends AbstractGuardedTool {

    /** 技能服务；可能还没有实现 Bean。 */
    private final ObjectProvider<SkillService> skillServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime             工具执行关卡
     * @param skillServiceProvider 技能服务提供者
     */
    public ListSkillsTool(ToolRuntime runtime, ObjectProvider<SkillService> skillServiceProvider) {
        super(runtime);
        this.skillServiceProvider = skillServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "list_skills";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "列出本机已安装的技能（名字、一句话说明、声明会用到的工具）。"
                + "适用：有哪些技能可用、有没有能处理 Excel 的技能。"
                + "只看清单、不读正文；要执行某个技能前请用 read_skill 读它的完整说明。";
    }

    /**
     * 构造只读操作（无参数、无路径）。
     *
     * @param args 工具入参（无）
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        return new ToolAction(
                name(),
                ToolKind.READ,
                "技能清单",
                List.of(),
                Map.of(),
                "读取本机已安装的技能列表"
        );
    }

    /**
     * 执行查询：读取 snapshot 的 skills 数组并格式化成清单。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 技能清单
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        SkillService service = skillServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("技能服务尚未实现，当前无法读取技能清单");
        }
        try {
            Map<String, Object> snapshot = service.snapshot();
            Object rawSkills = snapshot == null ? null : snapshot.get("skills");
            if (!(rawSkills instanceof List<?> skills) || skills.isEmpty()) {
                return ToolResult.ok("当前没有安装任何技能（技能目录里没有带 SKILL.md 的子目录）");
            }
            List<String> lines = new ArrayList<>();
            for (Object raw : skills) {
                if (!(raw instanceof Map<?, ?> skill)) {
                    continue;
                }
                // Map<?, ?> 的键类型未知，不能直接用 getOrDefault("name", "")，这里手动取默认值
                String name = textOf(skill, "name");
                String description = textOf(skill, "description");
                boolean enabled = !Boolean.FALSE.equals(skill.get("enabled"));
                String state = enabled ? "可用" : "已禁用";
                String toolsText = "";
                if (skill.get("tools") instanceof List<?> tools && !tools.isEmpty()) {
                    toolsText = "，工具：" + tools.stream()
                            .map(item -> String.valueOf(item))
                            .collect(java.util.stream.Collectors.joining(", "));
                }
                lines.add("- " + name + "（" + state + "）：" + description + toolsText);
            }
            return ToolResult.ok("共 " + lines.size() + " 个技能：\n" + String.join("\n", lines));
        } catch (RuntimeException e) {
            return ToolResult.fail("读取技能清单失败: " + e.getMessage());
        }
    }

    /**
     * 从通配 Map 里安全取字符串值（键类型未知时 getOrDefault 无法通过编译）。
     *
     * @param map 原始 Map
     * @param key 键名
     * @return 字符串值；缺失时为空串
     */
    private static String textOf(Map<?, ?> map, String key) {
        Object value = map.get(key);
        return value == null ? "" : String.valueOf(value);
    }
}
