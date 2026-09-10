// 模块说明：斜杠命令注册表（UX-8）——把「输入框里敲 `/` 能选什么」变成后端可下发的一份清单。
//
// 为什么要有注册表，而不是前端写死一份：
//     技能是**磁盘上装进来的**（`<用户数据目录>/app-backend/skills` 与设置里的额外目录），
//     用户随时可能新增/禁用技能。如果 `/` 列表写在前端，装完新技能必须改代码才有得选；
//     放在后端，装好技能 → 刷新 → `/` 列表里自动就出现了（验收项之一）。
//
// 两类命令，执行路径完全不同（这是本文件最需要说清的一点）：
//     - **内置命令**（source="builtin"）：由前端自己执行，`action` 字段告诉它做哪件事
//       （doc=改走文档库链路、model=弹出模型选择、clear=新开一段对话、
//       export=导出本会话、help=列出全部命令）。后端不认识它们，也不需要认识。
//     - **技能命令**（source="skill"，action=""）：前端只负责把原始文本发出去，
//       由后端按技能链路解析，把技能说明书拼进这一轮的用户消息。本文件只是**登记**它。
//
// 名字冲突的约定：同名时以**内置命令**为准（前端按 source 排序，builtin 在前且优先生效）。
// 这样即使有人装了个叫 `help` 的技能，`/help` 也还是"列出全部命令"，不会突然变成别的东西。
package com.example.backendjava.service.impl;

// 第三方（Spring）：声明为本服务的 Bean 实现
import org.springframework.stereotype.Service;

// 标准库：ArrayList 收集命令清单
import java.util.ArrayList;
// 标准库：LinkedHashMap 保持每条命令字段顺序
import java.util.LinkedHashMap;
// 标准库：List 命令清单
import java.util.List;
// 标准库：Map 动态清单
import java.util.Map;

// 项目内：命令服务接口（本类实现它）
import com.example.backendjava.service.CommandService;
// 项目内：技能服务（`/` 列表里技能那一半的数据源）
import com.example.backendjava.service.SkillService;

/**
 * 斜杠命令注册表实现。
 *
 * <p>内置命令是编译期写死的 5 条，技能命令来自 {@link SkillService#snapshot()}
 * 里的技能清单——技能在磁盘上，所以技能命令每次都现拼，装完技能刷新即可见。</p>
 */
@Service
public class CommandServiceImpl implements CommandService {

    /** 技能服务：提供「技能总开关」与「已安装技能清单」两份数据。 */
    private final SkillService skillService;

    /**
     * 构造器注入技能服务。
     *
     * @param skillService 技能服务
     */
    public CommandServiceImpl(SkillService skillService) {
        this.skillService = skillService;
    }

    /**
     * 内置命令清单。
     *
     * <p>只登记「前端真的能执行完」的命令——宁可少几条，也不要摆一排点了没反应的假按钮。</p>
     */
    private static final List<CommandSpec> BUILTIN_COMMANDS = List.of(
            new CommandSpec(
                    "doc",
                    "文档库：列出 / 检索 / 导入 / 删除已入库文档（与 \\doc 等价）",
                    "-l 列表 / -s 关键词 / -i 路径 / -d 编号 / -h 帮助",
                    "builtin",
                    "doc"
            ),
            new CommandSpec(
                    "model",
                    "查看当前模型，或切换到指定模型（只影响下一轮）",
                    "不带参数=弹出选择；也可直接写 provider/model",
                    "builtin",
                    "model"
            ),
            new CommandSpec(
                    "clear",
                    "清空当前会话上下文，开始一段新对话（历史记录保留在左栏）",
                    "",
                    "builtin",
                    "clear"
            ),
            new CommandSpec(
                    "export",
                    "导出当前会话（Markdown 便于阅读 / JSON 便于再加工）",
                    "md 或 json，默认 md",
                    "builtin",
                    "export"
            ),
            new CommandSpec(
                    "help",
                    "列出全部可用命令（含已安装的技能）",
                    "",
                    "builtin",
                    "help"
            )
    );

    /**
     * 返回当前可用命令清单：内置命令在前，技能命令按名字排序在后。
     *
     * <p>技能总开关关闭（{@code skill.enabled=false}）时不列技能——列出来也调不动，
     * 不如让 `/` 列表诚实反映"现在真的能用什么"。</p>
     *
     * @return 形如 {"commands":[{name,description,args_hint,source,action}]}
     */
    @Override
    public Map<String, Object> listCommands() {
        List<Map<String, Object>> items = new ArrayList<>();
        for (CommandSpec spec : BUILTIN_COMMANDS) {
            items.add(spec.toMap());
        }

        Map<String, Object> snapshot = skillService.snapshot();
        if (!isTrue(snapshot.get("enabled"))) {
            return wrap(items);
        }
        Object skills = snapshot.get("skills");
        if (skills instanceof List<?> list) {
            for (Object item : list) {
                if (!(item instanceof Map<?, ?> skill)) {
                    continue;
                }
                // 技能命令只列「当前真的能用」的那部分：单条被禁用（enabled=false）的一并跳过
                if (!isTrue(skill.get("enabled"))) {
                    continue;
                }
                // 技能命令的 action 留空：前端只负责把原始文本发出去，展开由后端做
                items.add(new CommandSpec(
                        textOf(skill.get("name")),
                        textOf(skill.get("description")),
                        "可带参数，原样传给技能",
                        "skill",
                        ""
                ).toMap());
            }
        }
        return wrap(items);
    }

    /**
     * 把命令清单包进接口约定的外衣。
     *
     * @param items 命令条目
     * @return 形如 {"commands":[...]} 的响应
     */
    private static Map<String, Object> wrap(List<Map<String, Object>> items) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("commands", items);
        return result;
    }

    /**
     * 把任意值安全读成布尔：只认真正的 {@link Boolean#TRUE}。
     *
     * @param value 任意值
     * @return true 表示值为布尔 true
     */
    private static boolean isTrue(Object value) {
        return Boolean.TRUE.equals(value);
    }

    /**
     * 把任意值安全转成去空白的字符串。
     *
     * @param value 任意值
     * @return 字符串；null 转成空串
     */
    private static String textOf(Object value) {
        return value == null ? "" : String.valueOf(value).strip();
    }

    /**
     * 一条斜杠命令的元信息（下发给前端渲染 `/` 列表用）。
     *
     * @param name        命令名，**不含**斜杠，例如 "doc"、"model"；技能命令就是技能名
     * @param description 一句话说明：列表里显示在名字右边
     * @param argsHint    参数提示（可为空串），只用于占位展示，不做校验
     * @param source      命令来源："builtin"=内置（前端执行），"skill"=技能（后端展开提示词）
     * @param action      前端要执行的动作；技能命令为空串（表示"原样发给后端"）
     */
    private record CommandSpec(
            // 命令名
            String name,
            // 一句话说明
            String description,
            // 参数提示
            String argsHint,
            // 命令来源
            String source,
            // 前端动作
            String action
    ) {

        /**
         * 转成可 JSON 序列化的字典（接口直接下发这一份）。
         *
         * @return {"name","description","args_hint","source","action"}
         */
        Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("name", name);
            map.put("description", description);
            map.put("args_hint", argsHint);
            map.put("source", source);
            map.put("action", action);
            return map;
        }
    }
}
