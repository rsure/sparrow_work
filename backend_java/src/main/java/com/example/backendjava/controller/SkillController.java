// 模块说明：技能管理接口，路径与 Python 侧 /api/skills/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /skills
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：路径变量
import org.springframework.web.bind.annotation.PathVariable;
// 项目内业务异常：技能不存在
import com.example.backendjava.common.ApiException;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 技能业务接口：技能清单发现与内容读取
import com.example.backendjava.service.SkillService;

// 标准库：Map 用于动态快照
import java.util.Map;

/**
 * 技能管理接口。
 *
 * <p>Python 侧这三个端点返回裸 JSON（不套 ApiResponse），这里保持兼容。</p>
 */
@RestController
@RequestMapping("/skills")
public class SkillController {

    /** 技能服务；学习者实现后自动注入。 */
    private final ObjectProvider<SkillService> skillService;

    /**
     * 构造器注入可选 Service。
     *
     * @param skillService Spring 的按类型查找器
     */
    public SkillController(ObjectProvider<SkillService> skillService) {
        this.skillService = skillService;
    }

    /**
     * 列出已安装技能。
     *
     * @return 技能快照
     */
    @GetMapping
    public Map<String, Object> listSkills() {
        return ServiceSupport.require(skillService, "技能服务").snapshot();
    }

    /**
     * 重新扫描技能目录。
     *
     * @return 重载后的快照
     */
    @PostMapping("/reload")
    public Map<String, Object> reloadSkills() {
        return ServiceSupport.require(skillService, "技能服务").reload();
    }

    /**
     * 读取某个技能的完整正文。
     *
     * @param name 技能名
     * @return 技能详情
     */
    @GetMapping("/{name}")
    public Map<String, Object> getSkill(@PathVariable String name) {
        Map<String, Object> skill = ServiceSupport.require(skillService, "技能服务").getSkill(name);
        // 服务层用 null 表示不存在；Controller 转成 404
        if (skill == null) {
            throw new ApiException(404, "没有名为 " + name + " 的技能");
        }
        return skill;
    }
}
