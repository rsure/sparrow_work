// 模块说明：设置行的存储读写（app_settings 表的唯一入口），把 JPA 细节挡在设置逻辑之外。
package com.example.backendjava.settings;

// 标准库：Optional 表达「这行可能不存在」，避免用 null 表示缺失
import java.util.Optional;
// 标准库：List 返回全部设置行
import java.util.List;
// 标准库：LocalDateTime 生成 updated_at 时间戳
import java.time.LocalDateTime;
// 第三方（Spring）：声明本类是受管组件，由容器注入仓库
import org.springframework.stereotype.Component;
// 项目内：设置行实体
import com.example.backendjava.entity.AppSetting;
// 项目内：app_settings 表的仓库接口
import com.example.backendjava.repository.AppSettingRepository;

/**
 * 设置行的存取层：只负责「一行字符串进、一行字符串出」。
 *
 * <p>为什么不直接在 Service 里用仓库：设置值与密钥密文都存在同一张表里，
 * 把读写收在一个类里，将来换存储（改成文件/缓存）只改这里。</p>
 */
@Component
public class SettingRowStore {

    /** app_settings 表的仓库。 */
    private final AppSettingRepository repository;

    /**
     * 构造器注入仓库。
     *
     * @param repository app_settings 表仓库
     */
    public SettingRowStore(AppSettingRepository repository) {
        this.repository = repository;
    }

    /**
     * 读取一个键的原始值。
     *
     * @param key 设置键（含内部键，如 workspaces.active_id）
     * @return 库里的原始 JSON 文本；不存在时为空
     */
    public Optional<String> read(String key) {
        return repository.findByKey(key).map(AppSetting::getValue);
    }

    /**
     * 写入一个键（存在则覆盖，不存在则插入），并刷新 updated_at。
     *
     * @param key   设置键
     * @param value 要存的原始文本（通常是 JSON）
     */
    public void write(String key, String value) {
        // 先查再改：直接 new 一个实体去 save 会让 JPA 认为这是「新增」，
        // 对已存在的行虽然也能覆盖，但拿不到原本的创建信息，这里显式复用已有行更直观
        AppSetting row = repository.findByKey(key).orElseGet(() -> {
            AppSetting created = new AppSetting();
            created.setKey(key);
            return created;
        });
        row.setValue(value);
        row.setUpdatedAt(LocalDateTime.now().toString());
        repository.save(row);
    }

    /**
     * 删除一个键。
     *
     * @param key 设置键
     * @return true 表示确实删掉了一行；false 表示本来就不存在
     */
    public boolean delete(String key) {
        if (repository.findByKey(key).isEmpty()) {
            return false;
        }
        repository.deleteById(key);
        return true;
    }

    /**
     * 列出全部设置行（含密钥密文行），供导入导出统计与迁移判断使用。
     *
     * @return 全部行；不会为 null
     */
    public List<AppSetting> all() {
        return repository.findAll();
    }
}
