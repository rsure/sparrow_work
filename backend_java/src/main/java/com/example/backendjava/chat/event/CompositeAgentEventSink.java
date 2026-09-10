// 模块说明：事件出口组合器 —— 一条事件扇出给多个出口（SSE、轨迹、日志…）。
//
// 这就是「各种事件策略如何组织到一起」的答案：
//   * 每个出口是一个 AgentEventSink 实现（策略）；
//   * 本类把它们合成一条链（组合）；
//   * 新增出口 = 新增一个 Bean，本类与业务代码都不用改（开闭原则）。
// 容错要求：任何单个出口抛异常都不能影响其它出口，更不能打断正在进行的对话。
package com.example.backendjava.chat.event;

// 标准库：List 保存出口顺序
import java.util.List;

// 已有的事件接口与信封
import com.example.backendjava.dto.AgentDtos;

// 日志：单个出口失败时留痕，但不影响对话
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 组合事件出口：按注册顺序把事件分发给所有子出口。
 *
 * <p>子出口按构造时传入的顺序执行；顺序有意义：SSE 必须在最前，
 * 保证用户先看到输出，落库慢一点没关系。</p>
 */
public class CompositeAgentEventSink implements AgentEventSink {

    /** 本类日志。 */
    private static final Logger LOG = LoggerFactory.getLogger(CompositeAgentEventSink.class);

    /** 子出口列表；构造后不再变化。 */
    private final List<AgentEventSink> delegates;

    /**
     * 构造组合器。
     *
     * @param delegates 子出口，按期望的执行顺序排列
     */
    public CompositeAgentEventSink(List<AgentEventSink> delegates) {
        this.delegates = List.copyOf(delegates);
    }

    /**
     * 把事件逐个分发给子出口。
     *
     * @param event 事件信封
     */
    @Override
    public void emit(AgentDtos.AgentEvent event) {
        for (AgentEventSink delegate : delegates) {
            try {
                delegate.emit(event);
            } catch (RuntimeException ex) {
                // 单个出口失败（比如数据库锁）只记日志：绝不能让落库问题打断用户看到回答
                LOG.warn("事件出口 {} 处理 {} 失败：{}",
                        delegate.getClass().getSimpleName(), event.type(), ex.getMessage());
            }
        }
    }
}
