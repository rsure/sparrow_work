// 模块说明：设置值的类型枚举与写入校验（对应 Python 侧 settings_registry.py 的 SettingKind）。
package com.example.backendjava.settings;

// 标准库：科学计数法/小数形态判断需要精确的类型名
import java.math.BigDecimal;
import java.math.BigInteger;
// 标准库：List 表示 JSON 数组值
import java.util.List;
// 标准库：Map 表示 JSON 对象值
import java.util.Map;

// 项目内：校验失败统一抛 400 业务异常，由全局异常处理器转成 ApiResponse
import com.example.backendjava.common.ApiException;
// 项目内：json 类型只校验「能否序列化」，复用全局 ObjectMapper
import com.example.backendjava.util.JsonUtils;

/**
 * 设置项的值类型：决定写入时如何校验与转换。
 *
 * <p>六种类型覆盖设置页的全部控件：开关、整数、小数、文本框、JSON 编辑器、下拉框。
 * 错误文案与 Python 侧逐字一致，前端不需要为「Java 后端 / Python 后端」写两套提示。</p>
 */
public enum SettingKind {

    /** 开关型：只接受 true/false。 */
    BOOL("bool"),

    /** 整数型：接受整数、整值小数、可解析的字符串；可配 min/max。 */
    INT("int"),

    /** 浮点型：接受整数与小数；可配 min/max。 */
    FLOAT("float"),

    /** 字符串型：原样保存，不做任何类型转换。 */
    STRING("string"),

    /** JSON 型：任意可序列化结构（数组/对象），保存前做一次序列化校验。 */
    JSON("json"),

    /** 选择型：字符串，且必须落在声明里的候选值中（候选校验在 SettingDefinition）。 */
    SELECT("select");

    /** 对外的类型名（下发给前端渲染控件的 type 字段）。 */
    private final String value;

    /**
     * 构造枚举成员。
     *
     * @param value 对外的类型名，如 "bool"
     */
    SettingKind(String value) {
        this.value = value;
    }

    /**
     * 返回对外的类型名，例如 "int"。
     *
     * @return 类型名字符串
     */
    public String value() {
        return value;
    }

    /**
     * 把声明里写的类型名解析成枚举，例如 "int" → INT。
     *
     * @param raw 类型名（大小写与首尾空白会被忽略）
     * @return 对应的枚举成员
     * @throws IllegalArgumentException 类型名不在六种受支持类型里
     */
    public static SettingKind parse(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("不支持的设置类型 'None'，受支持的类型有：" + supportedNames());
        }
        String normalized = raw.trim().toLowerCase();
        for (SettingKind kind : values()) {
            if (kind.value.equals(normalized)) {
                return kind;
            }
        }
        throw new IllegalArgumentException(
                "不支持的设置类型 '" + raw + "'，受支持的类型有：" + supportedNames());
    }

    /**
     * 拼接全部受支持的类型名，用于报错提示。
     *
     * @return 形如 "bool、int、float、string、json、select" 的字符串
     */
    private static String supportedNames() {
        StringBuilder builder = new StringBuilder();
        for (SettingKind kind : values()) {
            if (builder.length() > 0) {
                builder.append("、");
            }
            builder.append(kind.value);
        }
        return builder.toString();
    }

    /**
     * 按本类型校验并规范化一个写入值。
     *
     * <p>这是「声明式校验」的核心：类型不符、区间越界、下拉候选不匹配都在这里被拦下，
     * 调用方拿到的一定是已经合法的值。</p>
     *
     * @param value 待校验的原始值（来自 HTTP 请求体，类型不可信）
     * @param key   设置键，仅用于拼接错误信息，让报错能指明是哪个键
     * @return 规范化后的值：INT→Integer/Long，FLOAT→Double，JSON 保持原结构
     * @throws ApiException 类型不匹配（code=400）
     */
    public Object coerce(Object value, String key) {
        // 错误信息前缀：有键名时带上，便于前端直接定位到具体设置项
        String where = key == null || key.isEmpty() ? "" : "设置 " + key + " ";
        return switch (this) {
            case BOOL -> coerceBool(value, where);
            case INT -> coerceInt(value, where);
            case FLOAT -> coerceFloat(value, where);
            case STRING -> coerceString(value, where);
            case JSON -> coerceJson(value, where);
            case SELECT -> coerceSelect(value, where);
        };
    }

    /**
     * 开关型校验：只接受真正的布尔值。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return 原布尔值
     * @throws ApiException 不是布尔值时（"true" 字符串也不放行，避免各语言真值表打架）
     */
    private static Object coerceBool(Object value, String where) {
        if (value instanceof Boolean) {
            return value;
        }
        throw new ApiException(400, where + "要求布尔值（true/false），收到 " + describeType(value));
    }

    /**
     * 整数型校验：整数、整值小数、可解析字符串都能转成整数。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return Integer（放得下时）或 Long
     * @throws ApiException 布尔值、带小数的数字、无法解析的字符串
     */
    private static Object coerceInt(Object value, String where) {
        // 显式拒绝布尔：前端传 true 几乎一定是 bug，放行会静默存成 1
        if (value instanceof Boolean) {
            throw new ApiException(400, where + "要求整数，收到布尔值");
        }
        if (value instanceof Integer || value instanceof Long
                || value instanceof Short || value instanceof Byte || value instanceof BigInteger) {
            return narrowInteger(((Number) value).longValue());
        }
        if (value instanceof Double || value instanceof Float || value instanceof BigDecimal) {
            double number = ((Number) value).doubleValue();
            // 只有整值小数才允许收下（0.5 不能悄悄变成 0）
            if (Double.isFinite(number) && number == Math.rint(number)) {
                return narrowInteger((long) number);
            }
            throw new ApiException(400, where + "要求整数，收到 " + describeType(value));
        }
        if (value instanceof String text) {
            String trimmed = text.trim();
            try {
                return narrowInteger(Long.parseLong(trimmed));
            } catch (NumberFormatException e) {
                // 解析失败要说清「收到的是什么」，否则用户不知道该改成什么
                throw new ApiException(400, where + "要求整数，收到 " + repr(value));
            }
        }
        throw new ApiException(400, where + "要求整数，收到 " + describeType(value));
    }

    /**
     * 把 long 收窄成 Integer（放得下时），保持与前端 JSON 数字一致的类型观感。
     *
     * @param number 原始整数
     * @return Integer 或 Long
     */
    private static Object narrowInteger(long number) {
        if (number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE) {
            return (int) number;
        }
        return number;
    }

    /**
     * 浮点型校验：整数与小数都接受，统一规范成 Double。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return Double
     * @throws ApiException 布尔值、无法解析的字符串、其它类型
     */
    private static Object coerceFloat(Object value, String where) {
        // bool 同样要拒绝：True 转成 1.0 几乎一定是误用
        if (value instanceof Boolean) {
            throw new ApiException(400, where + "要求数字，收到布尔值");
        }
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        if (value instanceof String text) {
            try {
                return Double.parseDouble(text.trim());
            } catch (NumberFormatException e) {
                throw new ApiException(400, where + "要求数字，收到 " + repr(value));
            }
        }
        throw new ApiException(400, where + "要求数字，收到 " + describeType(value));
    }

    /**
     * 字符串型校验：只接受字符串，数字不自动转换。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return 原字符串
     * @throws ApiException 非字符串（避免把版本号 "14" 存成数字 14）
     */
    private static Object coerceString(Object value, String where) {
        if (value instanceof String) {
            return value;
        }
        throw new ApiException(400, where + "要求字符串，收到 " + describeType(value));
    }

    /**
     * JSON 型校验：只校验「能不能序列化」，不约束内部结构。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return 原值（保持 List/Map 结构）
     * @throws ApiException 无法序列化成 JSON 时
     */
    private static Object coerceJson(Object value, String where) {
        try {
            JsonUtils.toJson(value);
            return value;
        } catch (RuntimeException e) {
            throw new ApiException(400, where + "要求可序列化的 JSON 值：" + e.getMessage());
        }
    }

    /**
     * 选择型校验：先只确认是字符串，候选值范围由 SettingDefinition 统一校验。
     *
     * @param value 待校验值
     * @param where 错误信息前缀
     * @return 原字符串
     * @throws ApiException 非字符串时
     */
    private static Object coerceSelect(Object value, String where) {
        if (value instanceof String) {
            return value;
        }
        throw new ApiException(400, where + "要求字符串（从固定候选中选一个），收到 " + describeType(value));
    }

    /**
     * 把 Java 类型翻译成 Python 风格的类型名，让错误文案与 Python 后端一致。
     *
     * @param value 任意值
     * @return str / int / float / bool / list / dict / NoneType 之类的名字
     */
    static String describeType(Object value) {
        if (value == null) {
            return "NoneType";
        }
        if (value instanceof String) {
            return "str";
        }
        if (value instanceof Boolean) {
            return "bool";
        }
        if (value instanceof Integer || value instanceof Long || value instanceof Short
                || value instanceof Byte || value instanceof BigInteger) {
            return "int";
        }
        if (value instanceof Double || value instanceof Float || value instanceof BigDecimal) {
            return "float";
        }
        if (value instanceof List<?>) {
            return "list";
        }
        if (value instanceof Map<?, ?>) {
            return "dict";
        }
        return value.getClass().getSimpleName();
    }

    /**
     * 生成 Python repr 风格的展示文本：字符串带单引号，布尔用 true/false，空值用 None。
     *
     * @param value 任意值
     * @return 便于用户照抄改正的展示文本
     */
    static String repr(Object value) {
        if (value == null) {
            return "None";
        }
        if (value instanceof String text) {
            return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'";
        }
        if (value instanceof Boolean flag) {
            return flag ? "true" : "false";
        }
        if (value instanceof Double number && number == Math.rint(number) && Double.isFinite(number)) {
            // 5.0 保留小数点，让用户看得出这是浮点类型的键
            return number.toString();
        }
        return String.valueOf(value);
    }
}
