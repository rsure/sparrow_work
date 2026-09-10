// 模块说明：扫描任务表的数据访问接口。
package com.example.backendjava.repository;

// 第三方（Spring Data JPA）：提供 save / deleteById / findAll 等通用 CRUD
import org.springframework.data.jpa.repository.JpaRepository;
// 项目内：扫描任务实体
import com.example.backendjava.entity.ScanTask;

// 标准库：List 保存查询结果
import java.util.List;

/**
 * task_info 表的仓库。
 */
public interface ScanTaskRepository extends JpaRepository<ScanTask, String> {

    /**
     * 按创建时间倒序查询全部任务（最近创建的排前面）。
     *
     * @return 任务列表
     */
    List<ScanTask> findAllByOrderByCreatedAtDesc();
}
