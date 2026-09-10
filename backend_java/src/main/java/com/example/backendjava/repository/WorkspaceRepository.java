// 模块说明：workspace 表的数据访问接口。工作区从「设置里的一个 JSON 数组」升级为独立表，
// 每行一个工作区，便于以后挂载会话、记忆、任务等按工作区归属的数据。
package com.example.backendjava.repository;

// 第三方（Spring Data JPA）：提供 save / deleteById / findAll 等通用 CRUD
import org.springframework.data.jpa.repository.JpaRepository;
// 项目内：工作区实体
import com.example.backendjava.entity.Workspace;

/**
 * workspace 表的仓库。
 *
 * <p>工作区数量是个位数，排序与「当前生效」判断都放在 Service 里用内存完成，
 * 因此这里不需要自定义查询。</p>
 */
public interface WorkspaceRepository extends JpaRepository<Workspace, String> {
}
