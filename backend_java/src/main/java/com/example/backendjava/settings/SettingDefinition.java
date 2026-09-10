// 模块说明：一条设置声明的不可变描述（对应 Python 侧 settings_registry.py 的 SettingDef）。
package com.example.backendjava.settings;

// 标准库：List 保存 select 候选值与候选标签
import java.util.List;

// 项目内：下发给设置页的 schema DTO（GET /api/settings/meta 的元素）
import com.example.backendjava.dto.SettingDtos;

/**
 * 一个设置项的静态声明：键、类型、默认值、取值范围与展示信息。
 *
 * <p>声明只含元数据、不含逻辑。各模块用这份声明自动获得三件事：
 * 读取有默认值兜底、写入有校验、设置页能自动渲染，不需要自己写存储或接口代码。</p>
 *
 * @param key          设置键，固定为「组.键」两段式，例如 llm.model
 * @param kind         值类型，决定校验与转换方式
 * @param defaultValue 默认值：用户没配置过时返回它，调用方因此不必写 if-else 兜底
 * @param label        中文展示名；留空时前端回退显示 key
 * @param optionLabels select 候选值的中文标签，必须与 options 一一对应；其它类型为 null
 * @param category     设置页分组 id，前端按它自动分区渲染
 * @param min          数值下界，仅 INT/FLOAT 生效；null 表示不限
 * @param max          数值上界，仅 INT/FLOAT 生效；null 表示不限
 * @param options      select 的候选值；其它类型为 null
 * @param since        首次引入的里程碑，追溯用
 * @param description  面向用户的一句话说明，会随 meta 接口下发当提示文案
 * @param secret       是否为密钥项；密钥走 SecretStore，不落普通设置接口
 */
public record SettingDefinition(
        // 设置键
        String key,
        // 值类型
        SettingKind kind,
        // 默认值
        Object defaultValue,
        // 展示名
        String label,
        // select 候选标签
        List<String> optionLabels,
        // 设置页分组
        String category,
        // 数值下界
        Double min,
        // 数值上界
        Double max,
        // select 候选值
        List<String> options,
        // 里程碑
        String since,
        // 说明
        String description,
        // 是否密钥项
        boolean secret
) {

    /**
     * 紧凑构造器：在注册声明时就做自检，把「明显写错的声明」挡在启动阶段。
     *
     * <p>为什么不等到用户写入时才报错：声明写错是开发者的 bug，应该在启动时就炸掉，
     * 而不是让用户在设置页里撞上一个莫名其妙的 400。</p>
     */
    public SettingDefinition {
        // 键必须是「组.键」两段式：这是模块命名空间的基础约定
        if (key == null || !key.contains(".") || key.startsWith(".") || key.endsWith(".")) {
            throw new IllegalArgumentException(
                    "设置键 " + SettingKind.repr(key) + " 必须形如「组.键」，例如 llm.model");
        }
        if (kind == null) {
            throw new IllegalArgumentException("设置 " + key + " 缺少值类型");
        }
        // select 必须给候选值，否则前端只能渲染成自由文本框、用户能存进非法值
        if (kind == SettingKind.SELECT && (options == null || options.isEmpty())) {
            throw new IllegalArgumentException("设置 " + key + " 声明为 select，但没给 options 候选值");
        }
        if (optionLabels != null) {
            if (kind != SettingKind.SELECT) {
                throw new IllegalArgumentException("设置 " + key + " 不是 select，不该声明 option_labels");
            }
            // 长度不齐会让下拉项错位（显示 A 的值、存 B 的值）
            if (options != null && optionLabels.size() != options.size()) {
                throw new IllegalArgumentException(
                        "设置 " + key + " 的 option_labels 有 " + optionLabels.size() + " 项，"
                                + "与 options 的 " + options.size() + " 项不一致");
            }
        }
        if (min != null && max != null && min > max) {
            throw new IllegalArgumentException("设置 " + key + " 的 min(" + min + ") 大于 max(" + max + ")");
        }
        // 默认值必须能通过自身的类型与范围校验，避免「默认值本身就是非法的」
        Object normalizedDefault = kind.coerce(defaultValue, key);
        checkRangeOf(key, kind, normalizedDefault, min, max, options);
        // 展示字段给安全默认值：新增设置项时「先能跑」比「先取个好名字」重要
        if (label == null) {
            label = "";
        }
        if (category == null || category.isBlank()) {
            category = "advanced";
        }
        if (since == null || since.isBlank()) {
            since = "M1";
        }
        if (description == null) {
            description = "";
        }
    }

    /**
     * 校验并规范化一个写入值：先按类型转换，再校验区间/候选值。
     *
     * @param value 待写入的原始值
     * @return 规范化后的值，可直接落库
     * @throws com.example.backendjava.common.ApiException 类型或取值不合法时（code=400）
     */
    public Object coerce(Object value) {
        return checkRange(kind.coerce(value, key));
    }

    /**
     * 在类型转换之后，再校验数值区间与 select 候选值。
     *
     * @param value 已通过 kind.coerce 的值
     * @return 原样返回该值
     * @throws com.example.backendjava.common.ApiException 超出区间或不在候选内（code=400）
     */
    public Object checkRange(Object value) {
        return checkRangeOf(key, kind, value, min, max, options);
    }

    /**
     * 区间/候选值校验的具体实现（静态，便于紧凑构造器在校验默认值时复用）。
     *
     * @param key     设置键
     * @param kind    值类型
     * @param value   已规范化的值
     * @param min     下界
     * @param max     上界
     * @param options select 候选值
     * @return 原样返回该值
     */
    private static Object checkRangeOf(String key, SettingKind kind, Object value,
                                       Double min, Double max, List<String> options) {
        // select 的候选校验放这里：coerce 拿不到 options，只能做类型检查
        if (kind == SettingKind.SELECT && options != null && !options.isEmpty()
                && !options.contains(value)) {
            String candidates = String.join("、", options);
            throw new com.example.backendjava.common.ApiException(
                    400, "设置 " + key + " 只能取以下候选值之一：" + candidates + "；收到 " + SettingKind.repr(value));
        }
        // 区间校验只对数值类型有意义
        if (kind == SettingKind.INT || kind == SettingKind.FLOAT) {
            double number = ((Number) value).doubleValue();
            if (min != null && number < min) {
                throw new com.example.backendjava.common.ApiException(
                        400, "设置 " + key + " 不能小于 " + formatBound(min) + "（收到 " + formatBound(number) + "）");
            }
            if (max != null && number > max) {
                throw new com.example.backendjava.common.ApiException(
                        400, "设置 " + key + " 不能大于 " + formatBound(max) + "（收到 " + formatBound(number) + "）");
            }
        }
        return value;
    }

    /**
     * 把上下界格式化成用户易读的文本：整数不显示 ".0"。
     *
     * @param number 上下界数值
     * @return 形如 "1" 或 "0.95" 的字符串
     */
    private static String formatBound(double number) {
        if (number == Math.rint(number) && Math.abs(number) < 1e15) {
            return String.valueOf((long) number);
        }
        return String.valueOf(number);
    }

    /**
     * 转成 GET /api/settings/meta 下发的 schema 形状（只含元数据，不含当前值）。
     *
     * @return 设置页渲染单个设置项所需的描述
     */
    public SettingDtos.SettingMeta toMeta() {
        return new SettingDtos.SettingMeta(
                key,
                label,
                kind.value(),
                defaultValue,
                min,
                max,
                options,
                optionLabels,
                category,
                since,
                description,
                secret);
    }

    /**
     * 创建一条声明的流式构造入口。
     *
     * @param key          设置键
     * @param kind         值类型
     * @param defaultValue 默认值
     * @return 构造器；后续用链式方法补 label/category/区间等可选信息
     */
    public static Builder of(String key, SettingKind kind, Object defaultValue) {
        return new Builder(key, kind, defaultValue);
    }

    /**
     * 声明构造器：把 12 个字段里「大多数声明都相同」的部分收成默认值。
     *
     * <p>没有它，67 条声明每条都要写满 12 个参数，既难读也容易写错位置。</p>
     */
    public static final class Builder {

        // 已确定的三要素
        private final String key;
        // 值类型
        private final SettingKind kind;
        // 默认值
        private final Object defaultValue;
        // 展示名（默认空串，前端回退显示 key）
        private String label = "";
        // select 候选标签（默认 null）
        private List<String> optionLabels;
        // 设置页分组（默认 advanced）
        private String category = "advanced";
        // 数值下界（默认不限）
        private Double min;
        // 数值上界（默认不限）
        private Double max;
        // select 候选值（默认 null）
        private List<String> options;
        // 里程碑（默认 M1）
        private String since = "M1";
        // 说明（默认空串）
        private String description = "";
        // 是否密钥项（默认 false）
        private boolean secret;

        /**
         * 由 of() 调用，外部不要直接 new。
         *
         * @param key          设置键
         * @param kind         值类型
         * @param defaultValue 默认值
         */
        private Builder(String key, SettingKind kind, Object defaultValue) {
            this.key = key;
            this.kind = kind;
            this.defaultValue = defaultValue;
        }

        /**
         * 设置中文展示名。
         *
         * @param label 展示名
         * @return 本构造器，便于链式调用
         */
        public Builder label(String label) {
            this.label = label;
            return this;
        }

        /**
         * 设置设置页分组。
         *
         * @param category 分组 id，如 "model"、"theme"
         * @return 本构造器
         */
        public Builder category(String category) {
            this.category = category;
            return this;
        }

        /**
         * 设置数值下界（只对 INT/FLOAT 有意义）。
         *
         * @param min 下界
         * @return 本构造器
         */
        public Builder min(double min) {
            this.min = min;
            return this;
        }

        /**
         * 设置数值上界（只对 INT/FLOAT 有意义）。
         *
         * @param max 上界
         * @return 本构造器
         */
        public Builder max(double max) {
            this.max = max;
            return this;
        }

        /**
         * 设置 select 候选值。
         *
         * @param options 候选值，顺序与 optionLabels 必须一一对应
         * @return 本构造器
         */
        public Builder options(String... options) {
            this.options = List.of(options);
            return this;
        }

        /**
         * 设置 select 候选值的中文标签。
         *
         * @param optionLabels 候选标签，顺序与 options 必须一一对应
         * @return 本构造器
         */
        public Builder optionLabels(String... optionLabels) {
            this.optionLabels = List.of(optionLabels);
            return this;
        }

        /**
         * 设置面向用户的说明。
         *
         * @param description 一句话说明
         * @return 本构造器
         */
        public Builder description(String description) {
            this.description = description;
            return this;
        }

        /**
         * 设置首次引入的里程碑。
         *
         * @param since 里程碑标识，如 "M5"
         * @return 本构造器
         */
        public Builder since(String since) {
            this.since = since;
            return this;
        }

        /**
         * 标记为密钥项（正常情况下内置声明里没有密钥项）。
         *
         * @return 本构造器
         */
        public Builder secret() {
            this.secret = true;
            return this;
        }

        /**
         * 生成声明并触发自检。
         *
         * @return 不可变的设置声明
         * @throws IllegalArgumentException 声明本身不合法时（键格式、区间、默认值等）
         */
        public SettingDefinition build() {
            return new SettingDefinition(key, kind, defaultValue, label, optionLabels,
                    category, min, max, options, since, description, secret);
        }
    }
}
