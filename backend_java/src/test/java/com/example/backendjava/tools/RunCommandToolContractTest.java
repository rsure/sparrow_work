// 模块说明：run_command 的工具契约测试（参数声明 + schema 翻译 + 报错文案）。
//
// 为什么需要这个类：Java 侧移植时工具参数只剩一句人话说明，模型拿不到字段名，只能靠猜。
// 线上真实出现过：模型把 command_args 写成 args / arguments / subcommand 等十几种名字，
// 每一轮都被拒，而拒的原因只写「命令 node 需要给出子命令」，于是它一直换名字重试。
// Python 侧有回归测试守着 command_args（见 backend/tests/test_tools.py），这里补上 Java 对应的一份。
package com.example.backendjava.tools;

// 标准库：List 构造命令参数与参数字段清单
import java.util.List;
// 标准库：Map 构造一份「模型按声明填好」的入参，喂给 ToolArgs 验证键名对得上
import java.util.Map;
// 标准库：Set 比较字段名集合
import java.util.Set;
// 标准库：stream 把字段声明映射成字段名集合
import java.util.stream.Collectors;
// LangChain4j：数组型 schema，用来断言 command_args 被翻译成「字符串数组」
import dev.langchain4j.model.chat.request.json.JsonArraySchema;
// LangChain4j：字符串 schema，用来断言数组元素是字符串
import dev.langchain4j.model.chat.request.json.JsonStringSchema;
// LangChain4j：对象型 schema，翻译结果的整体类型
import dev.langchain4j.model.chat.request.json.JsonObjectSchema;
// LangChain4j：整数 schema，用来断言 timeout 被翻译成整数
import dev.langchain4j.model.chat.request.json.JsonIntegerSchema;
// 项目内：参数字段的领域声明（字段名 / 类型 / 说明 / 是否必填）
import com.example.backendjava.service.ToolParameter;
// 项目内：命令执行工具（被测对象）
import com.example.backendjava.tools.exec.RunCommandTool;
// 测试框架：JUnit 5 断言
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
// 测试框架：JUnit 5 测试方法标记
import org.junit.jupiter.api.Test;

/**
 * run_command 的参数声明、schema 翻译与报错文案契约。
 */
class RunCommandToolContractTest {

    /**
     * 取工具声明的参数字段。
     *
     * <p>传 null 给构造器是故意的：{@link RunCommandTool#parameters()} 只读静态声明，
     * 不碰执行关卡，所以这里不需要装配一个假的 ToolRuntime。</p>
     *
     * @return 工具声明的参数字段
     */
    private static List<ToolParameter> declaredParameters() {
        return new RunCommandTool(null).parameters();
    }

    /**
     * 工具必须声明模型真正要传的五个字段，其中前三个是必填。
     *
     * <p>只声明 command / cwd 是不够的：模型看不到 command_args 就会自己编一个名字，
     * 然后被 ToolArgs.stringList 当成「缺失」处理。</p>
     */
    @Test
    void parametersDeclareTheFieldsTheToolReads() {
        List<ToolParameter> parameters = declaredParameters();

        Set<String> names = parameters.stream()
                .map(ToolParameter::name)
                .collect(Collectors.toSet());
        assertEquals(Set.of("command", "command_args", "cwd", "timeout", "purpose"), names,
                "字段名必须与 ToolArgs 读取的键名逐字一致");

        Map<String, ToolParameter> byName = parameters.stream()
                .collect(Collectors.toMap(ToolParameter::name, parameter -> parameter));
        assertEquals(ToolParameter.Kind.STRING, byName.get("command").kind());
        assertEquals(ToolParameter.Kind.STRING_ARRAY, byName.get("command_args").kind());
        assertEquals(ToolParameter.Kind.STRING, byName.get("cwd").kind());
        assertEquals(ToolParameter.Kind.INTEGER, byName.get("timeout").kind());
        assertEquals(ToolParameter.Kind.STRING, byName.get("purpose").kind());

        // 必填项：允许列表里每个程序都要带参数，所以 command_args 也必填；
        // timeout / purpose 有默认值，可以省略
        assertTrue(byName.get("command").required(), "command 必须是必填");
        assertTrue(byName.get("command_args").required(), "command_args 必须是必填");
        assertTrue(byName.get("cwd").required(), "cwd 必须是必填");
        assertFalse(byName.get("timeout").required(), "timeout 有默认值，不应必填");
        assertFalse(byName.get("purpose").required(), "purpose 有默认值，不应必填");

        // 每个字段都要有给模型看的说明，否则模型仍然只能猜
        for (ToolParameter parameter : parameters) {
            assertTrue(parameter.description() != null && !parameter.description().isBlank(),
                    "字段 " + parameter.name() + " 缺少说明");
        }
    }

    /**
     * 声明要能被翻译成模型库的 JSON Schema：数组字段是真的数组，必填项真的出现在 required 里。
     */
    @Test
    void parametersAreTranslatedToJsonSchema() {
        JsonObjectSchema schema = ToolSchemaMapper.toJsonSchema(declaredParameters());

        assertEquals(Set.of("command", "command_args", "cwd", "timeout", "purpose"),
                schema.properties().keySet(), "五个字段都要出现在 properties 里");

        JsonArraySchema commandArgs = assertInstanceOf(
                JsonArraySchema.class, schema.properties().get("command_args"));
        assertInstanceOf(JsonStringSchema.class, commandArgs.items(), "数组元素必须是字符串");
        assertInstanceOf(JsonIntegerSchema.class, schema.properties().get("timeout"));

        assertEquals(Set.of("command", "command_args", "cwd"), Set.copyOf(schema.required()),
                "required 里只放真正必填的三个字段");
    }

    /**
     * 没有声明字段的工具要保持历史行为：翻译成「开放对象」，任何字段都放行。
     *
     * <p>老工具的说明文字里已经写了字段名，这条路径不能因为新契约而失效。</p>
     */
    @Test
    void undeclaredParametersKeepOpenSchema() {
        JsonObjectSchema schema = ToolSchemaMapper.toJsonSchema(List.of());
        assertEquals(Boolean.TRUE, schema.additionalProperties(),
                "没声明字段时要放行任意字段");
        assertTrue(schema.properties().isEmpty(), "开放对象不带任何字段声明");
    }

    /**
     * 声明的字段名必须真的能被 ToolArgs 读到：防止「schema 改了名字、执行处没跟着改」。
     *
     * <p>这里按声明构造一份入参，再用执行处同一套读取方法取值。名字对不上就会抛异常，
     * 也就是线上那种「模型传对了却被判成没传」的故障。</p>
     */
    @Test
    void declaredNamesAreAcceptedByToolArgs() {
        List<String> commandArgs = List.of("--version");
        Map<String, Object> args = Map.of(
                "command", "node",
                "command_args", commandArgs,
                "cwd", "D:\\Users\\leade\\IdeaProjects\\sparrow_work",
                "timeout", 30,
                "purpose", "查一下 node 版本");

        assertEquals("node", ToolArgs.requiredString(args, "command"));
        assertEquals(commandArgs, ToolArgs.stringList(args, "command_args"),
                "command_args 必须能原样读回字符串数组");
        assertEquals("D:\\Users\\leade\\IdeaProjects\\sparrow_work", ToolArgs.requiredString(args, "cwd"));
        assertEquals(30, ToolArgs.optionalInt(args, "timeout", 60));
        assertEquals("查一下 node 版本", ToolArgs.optionalString(args, "purpose", ""));
    }

    /**
     * 工具说明里要写出参数名：有些客户端只看 description，不看 schema。
     */
    @Test
    void descriptionNamesTheParameters() {
        String description = new RunCommandTool(null).description();
        for (String name : List.of("command", "command_args", "cwd", "timeout", "purpose")) {
            assertTrue(description.contains(name), "说明文字里缺少参数名 " + name);
        }
    }

    /**
     * 参数数组为空时，报错必须点名 command_args，并给出允许的子命令。
     *
     * <p>旧文案只说「需要给出子命令」，模型会以为子命令写错了，继续换名字重试。</p>
     */
    @Test
    void missingCommandArgsNamesTheParameter() {
        String reason = RunCommandTool.checkCommand("node", List.of());
        assertNotNull(reason);
        assertTrue(reason.contains("command_args"), "报错要点名缺哪个参数，实际：" + reason);
        assertTrue(reason.contains("--version"), "报错要给出允许的子命令，实际：" + reason);
    }

    /**
     * 子命令不在允许列表时，报错要保留模型给的值，并列出允许项。
     */
    @Test
    void unknownSubcommandListsAllowedValues() {
        String reason = RunCommandTool.checkCommand("git", List.of("commit"));
        assertNotNull(reason);
        assertTrue(reason.contains("commit"), "报错要回显模型给的值，实际：" + reason);
        assertTrue(reason.contains("status"), "报错要列出允许项，实际：" + reason);
    }

    /**
     * echo 不是可执行文件：Windows 上它是 cmd/PowerShell 的内建命令，没有 echo.exe。
     *
     * <p>进程用 ProcessBuilder 直接启动、刻意不经过 shell，所以放行 echo 只会让模型拿到
     * 「找不到可执行文件」，白白浪费一轮。这里锁死「echo 不再登记在允许列表」。</p>
     */
    @Test
    void echoIsNoLongerAllowlisted() {
        assertNotNull(RunCommandTool.checkCommand("echo", List.of("hi")));
    }

    /**
     * 已登记的程序名大小写与 .exe 后缀都要能正常识别（模型可能写 Git.exe）。
     */
    @Test
    void commandNameIsCaseInsensitiveAndAcceptsExeSuffix() {
        assertNull(RunCommandTool.checkCommand("Git.exe", List.of("status")));
        assertNull(RunCommandTool.checkCommand("NODE", List.of("--version")));
    }
}
