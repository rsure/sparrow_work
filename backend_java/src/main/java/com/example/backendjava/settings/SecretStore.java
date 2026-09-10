// 模块说明：密钥仓库——把用户的 API Key 等敏感值加密后存进 app_settings，
// 与「普通设置」共用一张表但走独立命名空间（secret:<名字>），永不出现在全量设置接口里。
package com.example.backendjava.settings;

// 标准库：Base64 编解码密文
import java.util.Base64;
// 标准库：Optional 表达「这个密钥没配置过」
import java.util.Optional;
// 标准库：SecureRandom 生成主密钥与每次加密的随机 IV
import java.security.SecureRandom;
// 标准库：Path/Files 读写主密钥文件
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
// 标准库：Arrays 拼接/切分 IV 与密文
import java.util.Arrays;
// 加密：AES 密钥与 GCM 模式
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
// 标准库：异常类型
import java.security.GeneralSecurityException;
// 日志：记录密钥读取失败等可容忍问题
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为受管组件
import org.springframework.stereotype.Component;
// 项目内：JSON 工具（密文行的格式）
import com.example.backendjava.util.JsonUtils;

/**
 * 密钥的加密存储。
 *
 * <p>为什么不用明文：{@code app_settings} 表会被导出、备份、贴进 issue，
 * 明文密钥等于泄露。这里用 JDK 自带的 AES/GCM 加密，主密钥单独放在用户目录下，
 * 与数据库文件分开，拿到数据库也解不开。</p>
 *
 * <p>为什么不用 Python 侧的 Fernet：Java 没有内置等价实现，
 * 引第三方库只为存几个字符串不划算；AES/GCM 同样是「带认证的加密」，
 * 密文被篡改会直接解密失败，安全性等价。</p>
 */
@Component
public class SecretStore {

    /** 日志：记录「密文解不开」这类不致命但需要排查的问题。 */
    private static final Logger log = LoggerFactory.getLogger(SecretStore.class);

    /** 密钥行在 app_settings 里的前缀；与普通设置键（含点号）天然不会冲突。 */
    public static final String SECRET_ROW_PREFIX = "secret:";

    /** 主密钥长度（字节）：AES-256。 */
    private static final int KEY_BYTES = 32;

    /** GCM 推荐 IV 长度（字节）：12 字节是 GCM 的标准尺寸。 */
    private static final int IV_BYTES = 12;

    /** 认证标签长度（位）：128 位为 GCM 最高强度。 */
    private static final int TAG_BITS = 128;

    /** 加密算法与模式：AES + GCM（同时提供加密与完整性校验）。 */
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";

    /** 读取设置行（密文也在这张表里）。 */
    private final SettingRowStore rowStore;

    /** 进程内缓存的主密钥，避免每次加解密都读文件。 */
    private SecretKey cachedKey;

    /** 随机源：仅在首次生成主密钥与每次加密 IV 时使用。 */
    private final SecureRandom random = new SecureRandom();

    /**
     * 构造器注入设置行存储。
     *
     * @param rowStore app_settings 读写入口
     */
    public SecretStore(SettingRowStore rowStore) {
        this.rowStore = rowStore;
    }

    /**
     * 判断某个密钥是否已配置。
     *
     * @param name 密钥名，如 deepseek.api_key
     * @return true 表示库里有一行非空密文
     */
    public boolean hasSecret(String name) {
        return rowStore.read(SECRET_ROW_PREFIX + name)
                .map(text -> !text.isBlank())
                .orElse(false);
    }

    /**
     * 读取并解密一个密钥。
     *
     * @param name 密钥名
     * @return 明文；未配置或密文损坏时为空
     */
    public Optional<String> getSecret(String name) {
        Optional<String> row = rowStore.read(SECRET_ROW_PREFIX + name);
        if (row.isEmpty() || row.get().isBlank()) {
            return Optional.empty();
        }
        try {
            String cipherText = JsonUtils.parse(row.get(), SecretPayload.class).cipher();
            return Optional.of(decrypt(cipherText));
        } catch (RuntimeException | GeneralSecurityException e) {
            // 换了机器或主密钥文件丢失时必然走到这里：当成「没配置」，让用户重新填，
            // 而不是让整个设置页 500
            log.warn("密钥 {} 解密失败，已按未配置处理：{}", name, e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * 保存（或覆盖）一个密钥。
     *
     * @param name  密钥名
     * @param value 明文密钥；空串等同于删除
     */
    public void setSecret(String name, String value) {
        if (value == null || value.isBlank()) {
            deleteSecret(name);
            return;
        }
        try {
            rowStore.write(SECRET_ROW_PREFIX + name, JsonUtils.toJson(new SecretPayload(encrypt(value))));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("密钥加密失败：" + e.getMessage(), e);
        }
    }

    /**
     * 删除一个密钥。
     *
     * @param name 密钥名
     * @return true 表示确实删掉了一行
     */
    public boolean deleteSecret(String name) {
        return rowStore.delete(SECRET_ROW_PREFIX + name);
    }

    /**
     * 返回给前端看的「打码后的密钥」，用于确认用户填的是哪一把。
     *
     * @param name 密钥名
     * @return 打码文本；未配置时为 null
     */
    public String maskedSecret(String name) {
        return getSecret(name).map(SecretStore::maskSecret).orElse(null);
    }

    /**
     * 把密钥打码：只保留头尾少量字符，确保截图/日志里不泄露完整值。
     *
     * @param value 明文密钥；null 或空串返回 null（空值代表「未设置」，不该回显成 ****）
     * @return 形如 {@code sk-****abcd} 的文本；长度不足 8 时统一返回 {@code ****}
     */
    public static String maskSecret(String value) {
        // 与 Python 侧 `if not value: return None` 对齐：空串也视为「未设置」
        if (value == null || value.isEmpty()) {
            return null;
        }
        if (value.length() < 8) {
            // 短值保留头尾就等于全泄露，直接全遮
            return "****";
        }
        return value.substring(0, 3) + "****" + value.substring(value.length() - 4);
    }

    /**
     * 加密明文，返回 base64(iv || 密文+认证标签)。
     *
     * @param plaintext 待加密明文
     * @return base64 文本
     * @throws GeneralSecurityException 加密失败时
     */
    private String encrypt(String plaintext) throws GeneralSecurityException {
        // 每次加密都用新的随机 IV：GCM 下 IV 重用会直接摧毁安全性
        byte[] iv = new byte[IV_BYTES];
        random.nextBytes(iv);
        Cipher cipher = Cipher.getInstance(TRANSFORMATION);
        cipher.init(Cipher.ENCRYPT_MODE, loadKey(), new GCMParameterSpec(TAG_BITS, iv));
        byte[] encrypted = cipher.doFinal(plaintext.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        byte[] combined = new byte[iv.length + encrypted.length];
        System.arraycopy(iv, 0, combined, 0, iv.length);
        System.arraycopy(encrypted, 0, combined, iv.length, encrypted.length);
        return Base64.getEncoder().encodeToString(combined);
    }

    /**
     * 解密 base64(iv || 密文+认证标签)。
     *
     * @param payload base64 文本
     * @return 明文
     * @throws GeneralSecurityException 主密钥不对或密文被篡改时
     */
    private String decrypt(String payload) throws GeneralSecurityException {
        byte[] combined = Base64.getDecoder().decode(payload);
        if (combined.length <= IV_BYTES) {
            throw new GeneralSecurityException("密文长度不合法");
        }
        byte[] iv = Arrays.copyOfRange(combined, 0, IV_BYTES);
        byte[] encrypted = Arrays.copyOfRange(combined, IV_BYTES, combined.length);
        Cipher cipher = Cipher.getInstance(TRANSFORMATION);
        cipher.init(Cipher.DECRYPT_MODE, loadKey(), new GCMParameterSpec(TAG_BITS, iv));
        return new String(cipher.doFinal(encrypted), java.nio.charset.StandardCharsets.UTF_8);
    }

    /**
     * 取得主密钥：进程内缓存一份；首次使用时读文件，文件不存在就生成后落盘。
     *
     * @return AES 主密钥
     * @throws GeneralSecurityException 生成密钥时
     */
    private synchronized SecretKey loadKey() throws GeneralSecurityException {
        if (cachedKey != null) {
            return cachedKey;
        }
        Path keyFile = keyFilePath();
        try {
            if (Files.exists(keyFile)) {
                byte[] bytes = Base64.getDecoder().decode(Files.readString(keyFile).trim());
                cachedKey = new SecretKeySpec(bytes, "AES");
                return cachedKey;
            }
            KeyGenerator generator = KeyGenerator.getInstance("AES");
            generator.init(KEY_BYTES * 8);
            SecretKey generated = generator.generateKey();
            Files.createDirectories(keyFile.getParent());
            Files.writeString(keyFile, Base64.getEncoder().encodeToString(generated.getEncoded()),
                    StandardOpenOption.CREATE);
            restrictPermissions(keyFile);
            cachedKey = generated;
            return cachedKey;
        } catch (java.io.IOException e) {
            throw new IllegalStateException("主密钥文件读写失败（" + keyFile + "）：" + e.getMessage(), e);
        }
    }

    /**
     * 计算主密钥文件路径：允许用系统属性 {@code app.secretKeyFile} 覆盖，默认放在用户目录。
     *
     * @return 主密钥文件路径
     */
    private Path keyFilePath() {
        String override = System.getProperty("app.secretKeyFile");
        if (override != null && !override.isBlank()) {
            return Path.of(override);
        }
        return Path.of(System.getProperty("user.home"), ".vue3-ts-python-learn", "app-secret.key");
    }

    /**
     * 收紧主密钥文件权限（仅 POSIX 文件系统；Windows 上静默跳过）。
     *
     * @param keyFile 主密钥文件
     */
    private void restrictPermissions(Path keyFile) {
        try {
            Files.setPosixFilePermissions(keyFile, PosixFilePermissions.fromString("rw-------"));
        } catch (java.io.IOException | RuntimeException e) {
            // Windows 不支持 POSIX 权限（抛 UnsupportedOperationException，属 RuntimeException 子类）：
            // 这里不是错误，只是没法进一步收紧
            log.debug("跳过主密钥文件权限设置：{}", e.getMessage());
        }
    }

    /**
     * 密文在库里的 JSON 形状。
     *
     * @param cipher base64(iv || 密文+认证标签)
     */
    private record SecretPayload(
            // 密文本体
            String cipher
    ) {
    }

    /**
     * 供测试与诊断使用的主密钥缓存清理：下次读写会重新读文件。
     */
    public synchronized void clearKeyCache() {
        cachedKey = null;
    }
}
