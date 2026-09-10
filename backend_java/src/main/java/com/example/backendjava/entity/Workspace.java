// 模块说明：工作区实体——一行代表一个「用户授权给 AI 操作的根目录集合」。
// 工作区先从设置里抽出为独立表，因此这里不再复用 app_settings 的 JSON 行。
package com.example.backendjava.entity;

// 标准库：List 保存工作区根目录
import java.util.ArrayList;
import java.util.List;
// 第三方（JPA）：实体/表/列/主键等注解
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
// 第三方（Lombok）：自动生成 getter/setter，实体不需要手写样板代码
import lombok.Getter;
import lombok.Setter;
// 项目内：List<String> ⇄ JSON 文本 的列转换器（保留路径里的逗号）
import com.example.backendjava.common.JsonStringListConverter;

/**
 * 工作区：一个具名的根目录集合，AI 只能在这些目录里读写文件。
 *
 * <p>当前生效的工作区 id 不属于本表，而是存在 app_settings 的内部键
 * {@code workspaces.active_id} 里——因为「当前选中谁」是全局状态，
 * 不是某个工作区自身的属性。</p>
 */
@Getter
@Setter
@Entity
@Table(name = "workspace")
public class Workspace {

    /** 工作区 id：由 Service 生成，形如 w-1 / w-2；默认工作区固定为 w-default。 */
    @Id
    @Column(name = "id", nullable = false)
    private String id;

    /** 工作区名称：用户在设置页看到并可以改的名字。 */
    @Column(name = "name", nullable = false)
    private String name;

    /** 根目录绝对路径列表：AI 的文件工具只能在这些目录范围内操作。 */
    @Convert(converter = JsonStringListConverter.class)
    @Column(name = "roots", nullable = false, length = 4000)
    private List<String> roots = new ArrayList<>();
}
