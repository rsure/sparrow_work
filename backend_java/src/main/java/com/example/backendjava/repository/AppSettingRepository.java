// 模块说明：app_settings 表的数据访问接口。该表是「键 → JSON 文本」的通用配置表，
// 普通设置、内部键（如 workspaces.active_id）与密钥密文都放在这里。
package com.example.backendjava.repository;

// 标准库：Optional 表达查询可能没有结果
import java.util.Optional;
// 第三方（Spring Data JPA）：提供 save / deleteById / findAll 等通用 CRUD
import org.springframework.data.jpa.repository.JpaRepository;
// 项目内：设置行实体
import com.example.backendjava.entity.AppSetting;

/**
 * app_settings 表的仓库。
 *
 * <p>只保留一个按主键查询的方法：写入统一走 {@code save}（实体主键已知，
 * 存在则更新、不存在则插入），这样不必维护额外的手写 SQL，也就不会出现
 * 「JPQL 里写了不存在的实体名」这类只在启动时才暴露的错误。</p>
 */
public interface AppSettingRepository extends JpaRepository<AppSetting, String> {

    /**
     * 按设置键查一行。
     *
     * @param key 设置键
     * @return 命中时为该行，不存在时为空
     */
    Optional<AppSetting> findByKey(String key);
}
