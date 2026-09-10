// 模块说明：斜杠命令接口，路径与 Python 侧 GET /api/commands 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /commands
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 斜杠命令业务接口：命令清单与执行
import com.example.backendjava.service.CommandService;

// 标准库：Map 用于动态命令清单
import java.util.Map;

/**
 * 斜杠命令接口。
 *
 * <p>Python 侧返回裸 JSON（{@code {"commands":[...]}}），这里保持兼容。</p>
 */
@RestController
@RequestMapping("/commands")
public class CommandController {

    /** 命令服务；学习者实现后自动注入。 */
    private final ObjectProvider<CommandService> commandService;

    /**
     * 构造器注入可选 Service。
     *
     * @param commandService Spring 的按类型查找器
     */
    public CommandController(ObjectProvider<CommandService> commandService) {
        this.commandService = commandService;
    }

    /**
     * 列出可用命令。
     *
     * @return 命令清单
     */
    @GetMapping
    public Map<String, Object> listCommands() {
        return ServiceSupport.require(commandService, "命令服务").listCommands();
    }
}
