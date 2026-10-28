// 模块说明：LangGraph4j 检查点存储的 Bean 装配。本类只回答「保存器怎么建」，不涉及图结构（图在 AgentGraphConfig）。
package com.example.backendjava.config;

// Spring 注解：声明这是配置类，容器启动时会解析其中的 @Bean 方法
import org.springframework.context.annotation.Configuration;
// Spring 注解：把方法返回值注册成容器里的 Bean，供 AgentGraphConfig 注入
import org.springframework.context.annotation.Bean;
// LangGraph4j 检查点接口：Bean 用接口类型暴露，图编译时只依赖抽象、不依赖 SQLite 实现
import org.bsc.langgraph4j.checkpoint.BaseCheckpointSaver;
// LangGraph4j 官方 SQLite 保存器：按 threadId 把图状态落盘，对应 Python 侧的 AsyncSqliteSaver
import org.bsc.langgraph4j.checkpoint.SQLiteSaver;
// LangGraph4j 状态基类：序列化器需要一个「空状态工厂」，配合 AgentState::new 使用
import org.bsc.langgraph4j.state.AgentState;
// 桥接序列化器：LangChain4j 的 ChatMessage / ToolExecutionRequest 交给 Jackson 处理，
// 否则落盘后再读回来会变成 LinkedHashMap，恢复图时拿不到原始类型
import org.bsc.langgraph4j.langchain4j.serializer.jackson.LC4jJacksonStateSerializer;

/**
 * 检查点存储配置。
 *
 * <p>检查点是「中断 / 恢复」的前提：图执行到 {@code interruptBefore} 指定的节点时，
 * 会把当前状态写进 SQLite；前端确认后带着同一个 threadId 再次调用 {@code GraphInput.resume(...)}，
 * 图就能从暂停处继续。</p>
 *
 * <p>数据库默认与业务表共用 app.db（见 {@link AppProperties#getCheckpointDbPath()}）。
 * SQLiteSaver 自己创建 checkpoints 相关表，与业务 schema 中的表互不冲突。</p>
 */
@Configuration
public class GraphConfig {

    /**
     * 创建 SQLite 版检查点保存器，全应用共用一个实例。
     *
     * <p>为什么必须是单例：同一个 SQLite 文件被多个 Saver 实例各持一条连接时，
     * 并发写会互相锁库；单例可以让「保存」和「恢复」走同一个连接池配置。</p>
     *
     * @param properties 应用配置；这里只读取 app.checkpoint-db-path（默认 app.db）
     * @return 检查点保存器，实现为 {@link SQLiteSaver}
     * @throws Exception 数据库文件无法打开或建表失败时抛出；直接让启动失败，避免带病运行
     */
    @Bean
    public BaseCheckpointSaver checkpointSaver(AppProperties properties) throws Exception {
        // 反序列化时要能把 JSON 还原成 AgentState 子类实例，所以给一个空状态工厂
        var serializer = new LC4jJacksonStateSerializer<AgentState>(AgentState::new);
        return SQLiteSaver.builder()
                // 数据库文件路径：与业务库共用 app.db，便于备份与排查
                .databasePath(properties.getCheckpointDbPath())
                // 首次启动库是空的：让 Saver 自己建表，省去手工执行迁移脚本
                .createTables(true)
                // 指定序列化器，保证 ChatMessage 等类型往返无损
                .stateSerializer(serializer)
                .build();
    }
}
