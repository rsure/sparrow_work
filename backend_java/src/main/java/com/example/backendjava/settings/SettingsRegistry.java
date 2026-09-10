// 模块说明：设置注册表——所有设置项的「单一事实来源」：声明、读取、校验、写入与变更广播。
package com.example.backendjava.settings;

// 标准库：List/Map 等集合
import java.util.List;
import java.util.Map;
import java.util.Optional;
// 标准库：LinkedHashMap 让 meta 与全量设置按 key 顺序输出
import java.util.LinkedHashMap;
// 标准库：TreeMap 天然按键排序，省去手动 sort
import java.util.TreeMap;
// 标准库：ArrayList 构造只读快照
import java.util.ArrayList;
// 标准库：CopyOnWriteArrayList 支持「遍历时监听者被增删」而不抛并发异常
import java.util.concurrent.CopyOnWriteArrayList;
// 标准库：Consumer 表示监听者回调
import java.util.function.Consumer;
// 日志：记录监听者抛出的异常（不能因为一个订阅者坏了就中断广播）
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：业务异常（未声明键、类型不合法、密钥命名空间等统一 400）
import com.example.backendjava.common.ApiException;
// 项目内：JSON 工具（设置值以 JSON 文本落库，保住 int/float/string 的类型区别）
import com.example.backendjava.util.JsonUtils;

/**
 * 设置注册表：管理全部设置声明的生命周期，并提供带默认值与校验的读写入口。
 *
 * <p>核心约定有三条：</p>
 * <ol>
 *   <li><b>读宽松</b>：库里没有、值坏了、类型对不上，一律回落到声明里的默认值，
 *       调用方永远拿到一个可用的值，不必写 null 判断；</li>
 *   <li><b>写严格</b>：先对所有键做完整校验，全部通过才落库；
 *       任何一项不合法就整批拒绝，避免出现「一半生效」的配置；</li>
 *   <li><b>改完广播</b>：写入成功后按前缀通知订阅者，模型/主题等模块据此立即生效。</li>
 * </ol>
 */
@Component
public class SettingsRegistry {

    /** 日志：记录订阅者回调失败。 */
    private static final Logger log = LoggerFactory.getLogger(SettingsRegistry.class);

    /** 密钥命名空间前缀：这些键必须走 /api/settings/secrets，不能混进普通设置。 */
    public static final String SECRET_KEY_PREFIX = "secrets.";

    /** 设置行的存储入口。 */
    private final SettingRowStore rowStore;

    /** 全部声明：key → 声明，按 key 升序（TreeMap 保证顺序）。 */
    private final Map<String, SettingDefinition> definitions;

    /** 监听者：前缀 → 回调列表。空前缀表示「订阅全部设置变化」。 */
    private final Map<String, CopyOnWriteArrayList<Consumer<SettingsChangeEvent>>> listeners =
            new java.util.concurrent.ConcurrentHashMap<>();

    /**
     * 构造器：装入内置声明并做重复键检查。
     *
     * @param rowStore 设置行存储
     * @throws IllegalStateException 有两条声明用了同一个键（属于开发期错误，启动即失败）
     */
    public SettingsRegistry(SettingRowStore rowStore) {
        this.rowStore = rowStore;
        Map<String, SettingDefinition> built = new TreeMap<>();
        for (SettingDefinition definition : BuiltinSettings.definitions()) {
            // 重复键可怕的地方在于「后注册的静默覆盖前一个」，所以这里必须炸出来
            if (built.putIfAbsent(definition.key(), definition) != null) {
                throw new IllegalStateException("设置键重复声明：" + definition.key());
            }
        }
        this.definitions = java.util.Collections.unmodifiableMap(built);
    }

    /**
     * 按 key 取声明。
     *
     * @param key 设置键
     * @return 对应声明
     * @throws ApiException 键未声明时（code=400，消息与 Python 侧一致）
     */
    public SettingDefinition getDef(String key) {
        SettingDefinition definition = definitions.get(key);
        if (definition == null) {
            throw new ApiException(400, "未声明的设置键：" + key);
        }
        return definition;
    }

    /**
     * 按 key 取声明，未声明时返回空而不是抛异常（用于「要不要展示/迁移」这类判断）。
     *
     * @param key 设置键
     * @return 声明；未声明时为空
     */
    public Optional<SettingDefinition> findDef(String key) {
        return Optional.ofNullable(definitions.get(key));
    }

    /**
     * 全部声明（按 key 升序），供 GET /api/settings/meta 使用。
     *
     * @return 只读列表；不会为 null
     */
    public List<SettingDefinition> listDefs() {
        return List.copyOf(definitions.values());
    }

    /**
     * 读取一个设置的当前值。
     *
     * @param key 设置键
     * @return 规范化后的值；库里缺失或存的值不合法时返回声明里的默认值
     * @throws ApiException 键未声明时
     */
    public Object getSetting(String key) {
        SettingDefinition definition = getDef(key);
        Object stored = readStoredValue(key);
        if (stored == null) {
            return definition.defaultValue();
        }
        try {
            return definition.coerce(stored);
        } catch (ApiException e) {
            // 例如早期版本把数字存成了字符串、或候选值被下架：让用户继续拿到可用默认值
            log.debug("设置 {} 的库中值不合法，回落到默认值：{}", key, e.getMessage());
            return definition.defaultValue();
        }
    }

    /**
     * 读取全部「非密钥」设置，供 GET /api/settings 使用。
     *
     * @return 按 key 升序的键值对；密钥声明会被拒绝而不是悄悄漏出
     * @throws ApiException 声明里出现密钥项时（这类项必须走密钥接口）
     */
    public Map<String, Object> getAllSettings() {
        Map<String, Object> result = new LinkedHashMap<>();
        for (SettingDefinition definition : definitions.values()) {
            String key = definition.key();
            if (definition.secret() || key.startsWith(SECRET_KEY_PREFIX)) {
                throw new ApiException(400, "设置键 " + key + " 属于密钥命名空间，不能进全量设置接口");
            }
            result.put(key, getSetting(key));
        }
        return result;
    }

    /**
     * 批量写入设置：先整体校验，再逐个落库，最后逐个广播。
     *
     * @param partial 键 → 新值；值按声明做类型转换与范围校验
     * @return 写入后的全量设置（与 GET /api/settings 一致）
     * @throws ApiException 有任何一个键未声明、属于密钥命名空间或值不合法时
     */
    public Map<String, Object> putSettings(Map<String, Object> partial) {
        if (partial == null) {
            throw new ApiException(400, "设置值必须是键值对对象，收到 " + SettingKind.describeType(null));
        }
        // 第一步：全部校验，任何一项失败都整批拒绝（此时库还没动过）
        Map<String, Object> validated = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : partial.entrySet()) {
            String key = entry.getKey();
            if (key == null) {
                throw new ApiException(400, "设置键必须是字符串，收到 null");
            }
            if (key.startsWith(SECRET_KEY_PREFIX)) {
                throw new ApiException(400,
                        "设置键 " + key + " 属于密钥命名空间，请改用 /api/settings/secrets 接口");
            }
            SettingDefinition definition = getDef(key);
            validated.put(key, definition.coerce(entry.getValue()));
        }
        // 第二步：逐个落库，并记下变更前的值用于广播
        List<SettingsChangeEvent> events = new ArrayList<>(validated.size());
        for (Map.Entry<String, Object> entry : validated.entrySet()) {
            String key = entry.getKey();
            Object oldValue = readStoredValue(key);
            rowStore.write(key, JsonUtils.toJson(entry.getValue()));
            events.add(new SettingsChangeEvent(key, entry.getValue(), oldValue));
        }
        // 第三步：落库全部成功后再广播，避免「监听者已按新值动作、但后面的键写失败」
        for (SettingsChangeEvent event : events) {
            publish(event);
        }
        return getAllSettings();
    }

    /**
     * 订阅某前缀下的设置变化（空前缀表示订阅全部）。
     *
     * @param prefix   键前缀，如 "llm." 或 "theme."
     * @param listener 变化回调；抛异常会被吞掉并记录日志
     */
    public void subscribe(String prefix, Consumer<SettingsChangeEvent> listener) {
        listeners.computeIfAbsent(prefix == null ? "" : prefix, ignored -> new CopyOnWriteArrayList<>())
                .add(listener);
    }

    /**
     * 取消订阅。
     *
     * @param prefix   订阅时使用的前缀
     * @param listener 订阅时传入的回调实例
     */
    public void unsubscribe(String prefix, Consumer<SettingsChangeEvent> listener) {
        CopyOnWriteArrayList<Consumer<SettingsChangeEvent>> group =
                listeners.get(prefix == null ? "" : prefix);
        if (group != null) {
            group.remove(listener);
        }
    }

    /**
     * 把一次变更通知给匹配前缀的订阅者。
     *
     * @param event 变更事件
     */
    private void publish(SettingsChangeEvent event) {
        for (Map.Entry<String, CopyOnWriteArrayList<Consumer<SettingsChangeEvent>>> entry : listeners.entrySet()) {
            String prefix = entry.getKey();
            // 空前缀 = 通配；其余按 startswith 匹配，例如 "llm." 能收到 llm.model 的变化
            if (prefix.isEmpty() || event.key().startsWith(prefix)) {
                for (Consumer<SettingsChangeEvent> listener : entry.getValue()) {
                    try {
                        listener.accept(event);
                    } catch (RuntimeException e) {
                        // 单个订阅者（比如重建模型客户端）失败不应影响已经成功的保存
                        log.warn("设置监听者处理 {} 失败：{}", event.key(), e.getMessage(), e);
                    }
                }
            }
        }
    }

    /**
     * 读出库里存的值并解析成 JSON 对象。
     *
     * @param key 设置键
     * @return 解析后的值；没有这行、内容为空或不是合法 JSON 时为 null
     */
    private Object readStoredValue(String key) {
        Optional<String> text;
        try {
            text = rowStore.read(key);
        } catch (RuntimeException e) {
            // 读库失败时按「没配置」处理：设置页不该因为一次查询失败就整体 500
            log.warn("读取设置 {} 失败，按默认值处理：{}", key, e.getMessage());
            return null;
        }
        if (text.isEmpty() || text.get().isBlank()) {
            return null;
        }
        try {
            return JsonUtils.parse(text.get(), Object.class);
        } catch (RuntimeException e) {
            log.debug("设置 {} 的库中内容不是合法 JSON，按默认值处理：{}", key, e.getMessage());
            return null;
        }
    }
}
