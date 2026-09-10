// 模块说明：read_skill 工具（对应 Python skill_tool.py 的 read_skill）。
package com.example.backendjava.tools.skill;

import com.example.backendjava.tools.ToolArgs; // 项目内：工具入参读取与类型校验

import com.example.backendjava.tools.AbstractGuardedTool; // 项目内：工具基类（统一裁决、执行与输出治理骨架）
import com.example.backendjava.tools.ToolAction; // 项目内：一次待裁决的操作描述
import com.example.backendjava.tools.ToolKind; // 项目内：工具操作类型（READ/WRITE/EXEC/NET）
import com.example.backendjava.tools.ToolRuntime; // 项目内：工具执行关卡（裁决/预算/确认/治理）

// 标准库：ArrayList 可用技能名
import java.util.ArrayList;
// 标准库：List 待校验路径
import java.util.List;
// 标准库：Map 技能详情与弹窗参数
import java.util.Map;
// 第三方（Spring）：延迟获取可选 Bean
import org.springframework.beans.factory.ObjectProvider;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：工具执行结果
import com.example.backendjava.dto.ToolResult;
// 项目内：技能服务接口
import com.example.backendjava.service.SkillService;

/**
 * 读取某个技能的完整说明正文。
 */
@Component
public class ReadSkillTool extends AbstractGuardedTool {

    /** 最多列出多少个可用技能名，避免错误提示本身过长。 */
    private static final int MAX_NAMES = 12;

    /** 技能服务；可能还没有实现 Bean。 */
    private final ObjectProvider<SkillService> skillServiceProvider;

    /**
     * 构造器。
     *
     * @param runtime              工具执行关卡
     * @param skillServiceProvider 技能服务提供者
     */
    public ReadSkillTool(ToolRuntime runtime, ObjectProvider<SkillService> skillServiceProvider) {
        super(runtime);
        this.skillServiceProvider = skillServiceProvider;
    }

    /** 返回工具名。 */
    @Override
    public String name() {
        return "read_skill";
    }

    /** 返回工具说明。 */
    @Override
    public String description() {
        return "读取某个技能的完整说明正文，然后按说明执行。"
                + "执行技能前请先调用它：技能的具体步骤（用哪个工具、注意什么）只写在正文里，"
                + "凭名字猜步骤往往做错。";
    }

    /**
     * 构造只读操作。
     *
     * @param args 工具入参：name
     * @return 待裁决操作
     */
    @Override
    protected ToolAction buildAction(Map<String, Object> args) {
        String name = ToolArgs.requiredString(args, "name");
        return new ToolAction(
                name(),
                ToolKind.READ,
                name,
                List.of(),
                Map.of("name", name),
                "读取技能 " + name + " 的说明正文"
        );
    }

    /**
     * 执行读取：返回技能描述、声明工具与完整正文。
     *
     * @param args   工具入参
     * @param action 已裁决的操作
     * @return 技能正文
     */
    @Override
    protected ToolResult run(Map<String, Object> args, ToolAction action) {
        SkillService service = skillServiceProvider.getIfAvailable();
        if (service == null) {
            return ToolResult.fail("技能服务尚未实现，当前无法读取技能正文");
        }
        String name = ToolArgs.requiredString(args, "name");
        try {
            Map<String, Object> skill = service.getSkill(name);
            if (skill == null || Boolean.FALSE.equals(skill.get("enabled"))) {
                return ToolResult.fail("没有名为 " + name + " 的可用技能。"
                        + availableHint(service));
            }
            String description = String.valueOf(skill.getOrDefault("description", ""));
            StringBuilder header = new StringBuilder("技能 " + name + "：" + description);
            if (skill.get("tools") instanceof List<?> tools && !tools.isEmpty()) {
                header.append("\n声明会用到的工具：")
                        .append(tools.stream().map(item -> String.valueOf(item))
                                .collect(java.util.stream.Collectors.joining(", ")));
            }
            String body = String.valueOf(skill.getOrDefault("body", ""));
            return ToolResult.ok(header + "\n\n" + body);
        } catch (RuntimeException e) {
            return ToolResult.fail("读取技能失败: " + e.getMessage());
        }
    }

    /**
     * 拼出「当前可用技能」提示。
     *
     * @param service 技能服务
     * @return 例如「可用：a、b」；没有技能时返回「当前也没有安装任何技能」
     */
    private static String availableHint(SkillService service) {
        try {
            Map<String, Object> snapshot = service.snapshot();
            Object rawSkills = snapshot == null ? null : snapshot.get("skills");
            if (!(rawSkills instanceof List<?> skills)) {
                return "当前也没有安装任何技能";
            }
            List<String> names = new ArrayList<>();
            for (Object raw : skills) {
                if (raw instanceof Map<?, ?> skill
                        && !Boolean.FALSE.equals(skill.get("enabled"))) {
                    names.add(textOf(skill, "name"));
                }
            }
            if (names.isEmpty()) {
                return "当前也没有安装任何可用技能";
            }
            return "可用：" + String.join("、", names.subList(0, Math.min(MAX_NAMES, names.size())));
        } catch (RuntimeException e) {
            return "无法读取可用技能清单";
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
