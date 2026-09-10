// 模块说明：斜杠命令清单接口（内置命令 + 已安装技能）。
package com.example.backendjava.service;

// 标准库：Map 用于动态命令清单
import java.util.Map;

/**
 * 命令服务接口。
 */
public interface CommandService {

    /**
     * 列出输入框敲 `/` 时可选的命令。
     *
     * @return 形如 {"commands":[{name,description,args_hint,source,action}]}
     */
    Map<String, Object> listCommands();
}
