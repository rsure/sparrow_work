// 模块说明：ToolExecutor 的包装实现 —— 在工具执行前后发出 tool_start / tool_end 事件。
//
// 为什么在这里发而不是在工具里发：
//   * 工具（ReadFileTool/RunCommandTool…）是纯能力，不应该依赖 SSE；
//   * 这里是「模型要调工具」的唯一入口，天然是发事件的地方。
package com.example.backendjava.chat.runtime;

// 标准库：List 收集工具轨迹
import java.util.List;
// 标准库：Map 工具入参与结果
import java.util.Map;
// 标准库：AtomicInteger 计数器（本轮第几个工具）
import java.util.concurrent.atomic.AtomicInteger;

// LangChain4j：工具执行请求与执行器接口
import com.example.backendjava.chat.event.ChatEvents;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.service.tool.ToolExecutor;

// 本项目：工具、结果、输出治理、运行时
import com.example.backendjava.dto.ToolResult;
import com.example.backendjava.service.AgentTool;
import com.example.backendjava.tools.OutputContract;
import com.example.backendjava.tools.SessionContext;
import com.example.backendjava.tools.ToolSession;
import com.example.backendjava.util.JsonUtils;

/**
 * 工具执行器包装：执行工具，并把过程翻译成事件。
 *
 * <p>一个实例对应「一轮对话」中的一个工具，由 ChatServiceImpl.buildToolMap 创建。</p>
 */
public class ChatToolExecutor implements ToolExecutor {

    /** 工具本身。 */
    private final AgentTool tool;

    /** 会话 id。 */
    private final String sessionId;

    /** 本轮状态容器：用于累积工具轨迹、判断是否已被停止。 */
    private final TurnRecorder recorder;

    /** 会话总线：发事件用。 */
    private final ChatSessionBus bus;

    /** 输出治理：取截断信息用（它是 @Component，直接注入）。 */
    private final OutputContract outputContract;

    /** 事件工厂：构造 tool_start / tool_end 用。 */
    private final ChatEvents events;

    /** 本轮权限模式：ask / workspace / allow，原样传给 SessionContext。 */
    private final String permissionMode;

    /**
     * 构造执行器。
     *
     * @param tool           工具
     * @param sessionId      会话 id
     * @param recorder       本轮记录器
     * @param bus            会话总线
     * @param outputContract 输出治理
     * @param events         事件工厂
     * @param permissionMode 本轮权限模式
     */
    public ChatToolExecutor(AgentTool tool, String sessionId, TurnRecorder recorder,
                            ChatSessionBus bus, OutputContract outputContract,
                            ChatEvents events, String permissionMode) {
        this.tool = tool;
        this.sessionId = sessionId;
        this.recorder = recorder;
        this.bus = bus;
        this.outputContract = outputContract;
        this.events = events;
        this.permissionMode = permissionMode;
    }

    /**
     * 执行工具并发出事件。
     *
     * @param request  模型给出的工具调用请求
     * @param memoryId 记忆 id（本项目未使用，保持签名即可）
     * @return 给模型看的工具结果文本
     */
    @Override
    public String execute(ToolExecutionRequest request, Object memoryId) {
        // 1) 解析入参：JsonUtils.parseMap 是项目内已有的工具方法
        Map<String, Object> arguments = JsonUtils.parseMap(request.arguments());

        // 2) 用户已经点了停止：工具不再执行，直接把结论交回模型，让这一轮尽早收敛
        if (recorder.isStopped()) {
            String skipped = "用户已停止本轮对话，工具 " + tool.name() + " 未执行。";
            bus.emit(sessionId, events.toolEnd(tool.name(), skipped, skipped.length(), false, null));
            return skipped;
        }

        // 3) 工具开始：前端立刻显示「正在读取 xxx」
        bus.emit(sessionId, events.toolStart(tool.name(), arguments));

        ToolResult result;
        // 4) 装配 ThreadLocal 上下文：ToolRuntime 里的权限裁决、审计、预算都靠它拿 sessionId
        ToolSession.setContext(new SessionContext(
                sessionId,
                java.util.List.of(),   // 工作区根目录：走 PathPolicy 的全局白名单
                java.util.Set.of(),    // 会话级禁用工具：本轮不禁用
                java.util.Set.of(),    // 会话级命令白名单：走全局
                "",                    // 工作区 id：留给后续「记住本次授权」用
                permissionMode,
                ToolSession.SCOPE_MAIN));
        try {
            // 5) 执行：权限/预算/审计/截断全在 ToolRuntime 里，这里只管调
            result = tool.execute(arguments);
        } catch (RuntimeException ex) {
            // 工具抛异常不能让整轮对话挂掉：转成失败结果交给模型自己解释
            result = ToolResult.fail("工具执行异常：" + ex.getMessage());
        } finally {
            // 6) 线程池复用线程，必须清理，否则上一个会话的上下文会串到下一个请求
            ToolSession.clear();
        }

        // 7) 取截断信息（取走即删，只能取一次；未截断时 returned.truncated()=false）
        OutputContract.TruncateResult truncation =
                outputContract.takeLastTruncation(sessionId, tool.name());

        // 8) 工具结束：total_chars / truncated / continuation_ref 三个字段全部来自 OutputContract
        bus.emit(sessionId, events.toolEnd(
                tool.name(),
                result.content(),
                truncation == null ? result.content().length() : truncation.totalChars(),
                truncation != null && truncation.truncated(),
                truncation == null ? null : truncation.continuationRef()));

        // 9) 记轨迹：done 事件与历史消息都要用
        recorder.addToolCall(tool.name(), arguments, result.content());
        return result.content();
    }
}