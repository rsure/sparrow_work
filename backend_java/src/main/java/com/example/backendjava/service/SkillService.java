// 模块说明：技能管理业务接口（对应 Python 的 EXT-1）。技能本质是磁盘上的 SKILL.md。
package com.example.backendjava.service;

// 标准库：Map 用于返回动态快照（含 skills / errors / dirs 等键）
import java.util.Map;

/**
 * 技能服务接口。
 *
 * <p>返回 Map 而不是强类型 DTO，是因为技能快照里同时包含成功清单、解析错误、
 * 扫描目录三类结构差异较大的数据；实现时请按 Python 侧 snapshot() 的键名返回。</p>
 */
public interface SkillService {

    /**
     * 返回技能清单与扫描状态。
     *
     * @return 形如 {"enabled":bool,"disabled":[...],"dirs":[...],"skills":[...],"errors":[...]}
     */
    Map<String, Object> snapshot();

    /**
     * 重新扫描技能目录并返回最新快照。
     *
     * @return 重载后的快照
     */
    Map<String, Object> reload();

    /**
     * 读取某个技能的完整正文。
     *
     * @param name 技能名
     * @return 形如 {"name","description","tools","body","path","enabled"}；不存在时返回 null
     */
    Map<String, Object> getSkill(String name);
}
