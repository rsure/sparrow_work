// 模块说明：设置服务的 Java 实现——工作区增删改查、普通设置读写、导入导出、密钥增删查。
// 逻辑对齐 Python 侧 controllers/setting_controller.py + services/{settings_registry,settings_transfer,
// secrets,workspace_service}.py；唯一的结构差异是「工作区」在 Java 侧已经独立成 workspace 表。
package com.example.backendjava.service.impl;

// 标准库：集合与流式处理
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
// 标准库：路径存在性判断（迁移旧的 workspace_roots 时只保留真实存在的目录）
import java.nio.file.Files;
import java.nio.file.Path;
// 标准库：导出时间戳
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
// 日志：记录「迁移/修复 active_id」这类一次性动作
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
// 第三方（Spring）：声明为服务组件，由容器注入依赖
import org.springframework.stereotype.Service;
// 项目内：统一响应 DTO（工作区/设置/密钥的请求与响应形状）
import com.example.backendjava.dto.SettingDtos;
// 项目内：业务异常（400 参数不合法、404 资源不存在）
import com.example.backendjava.common.ApiException;
// 项目内：工作区实体
import com.example.backendjava.entity.Workspace;
// 项目内：工作区表仓库
import com.example.backendjava.repository.WorkspaceRepository;
// 项目内：设置声明式注册表（默认值 + 校验 + 变更广播）
import com.example.backendjava.settings.SettingsRegistry;
// 项目内：密钥的加密存储（密文进库，接口只回脱敏值）
import com.example.backendjava.settings.SecretStore;
// 项目内：设置行存储（当前生效工作区 id 这类内部键也走它）
import com.example.backendjava.settings.SettingRowStore;
// 项目内：设置声明（清单元数据）
import com.example.backendjava.settings.SettingDefinition;
// 项目内：设置值脱敏（导出时抹掉疑似密钥）
import com.example.backendjava.settings.SettingsRedactor;
// 项目内：内置 LLM 供应商清单（导出「哪些密钥设置过」时只能从这里问密钥名）
import com.example.backendjava.llm.LlmProviderRegistry;
// 项目内：应用配置（导出文件里要写当前版本号）
import com.example.backendjava.config.AppProperties;
// 项目内：JSON 工具（内部键与设置值都以 JSON 文本落库）
import com.example.backendjava.util.JsonUtils;
// 项目内：设置服务接口（本类实现它）
import com.example.backendjava.service.SettingsService;

/**
 * 设置服务实现。
 *
 * <p>三条实现要点：</p>
 * <ol>
 *   <li><b>工作区独立成表</b>：每行一个工作区；(id, name, roots)；当前生效的工作区 id 仍存在
 *       app_settings 的内部键 {@code workspaces.active_id} 里，因为「选中谁」是全局状态；</li>
 *   <li><b>普通设置全部委托注册表</b>：默认值、类型与范围校验、变更广播都在
 *       {@link SettingsRegistry} 里，本类不再重复判断；</li>
 *   <li><b>导出必须脱敏</b>：任何疑似密钥的值都不出现在导出文件里，只记一个占位符与键名。</li>
 * </ol>
 */
@Service
public class SettingsServiceImpl implements SettingsService {

    /** 日志：记录旧数据迁移、active_id 修复等一次性动作。 */
    private static final Logger log = LoggerFactory.getLogger(SettingsServiceImpl.class);

    /** app_settings 内部键：当前生效的工作区 id（不属于普通设置项，因此不在注册表声明里）。 */
    private static final String KEY_ACTIVE_ID = "workspaces.active_id";
    private static final String KEY_WORKSPACES = "workspaces.list";

    /** app_settings 内部键：旧版扁平工作区根目录数组，迁移时只读、绝不改写。 */
    private static final String LEGACY_ROOTS_KEY = "workspace_roots";

    /** app_settings 内部键：Python 版本的「多工作区数组」，迁移时只读。 */
    private static final String LEGACY_PROFILES_KEY = "workspaces.list";

    /** app_settings 内部键：迁移完成标记，保证「删光工作区」后不会被旧数据复活。 */
    private static final String KEY_MIGRATED = "workspaces.migrated";

    /** 迁移生成的默认工作区 id：加 default 前缀是为了和新建的 w-1 / w-2 区分开。 */
    private static final String DEFAULT_WORKSPACE_ID = "w-default";

    /** 新建工作区名称留空时的占位名。 */
    private static final String DEFAULT_WORKSPACE_NAME = "默认工作区";

    /** 新建工作区 id 前缀，形如 w-1、w-2…… */
    private static final String WORKSPACE_ID_PREFIX = "w-";

    /** 导出格式标识：导入时用它判断「这是不是本应用的配置文件」。 */
    private static final String EXPORT_FORMAT = "app-settings/1";

    /** 导出时替换敏感值的占位符（与 Python 侧一致，便于两边导出文件互相导回）。 */
    private static final String REDACTED = SettingsRedactor.REDACTED;

    /** 设置注册表：普通设置的唯一读写入口。 */
    private final SettingsRegistry settingsRegistry;

    /** 密钥存储：加密落库，接口层只接触脱敏值。 */
    private final SecretStore secretStore;

    /** 设置行存储：读写 workspace*.active_id 这类内部键。 */
    private final SettingRowStore rowStore;

    /** 工作区表仓库。 */
    private final WorkspaceRepository workspaceRepository;

    /** 内置 LLM 供应商清单：导出时据此列出「哪些密钥设置过」。 */
    private final LlmProviderRegistry providerRegistry;

    /** 应用配置：导出文件里写版本号。 */
    private final AppProperties appProperties;

    /**
     * 构造器注入全部依赖。
     *
     * @param settingsRegistry    设置注册表
     * @param secretStore         密钥存储
     * @param rowStore            设置行存储
     * @param workspaceRepository 工作区仓库
     * @param providerRegistry    供应商清单
     * @param appProperties       应用配置
     */
    public SettingsServiceImpl(SettingsRegistry settingsRegistry,
                               SecretStore secretStore,
                               SettingRowStore rowStore,
                               WorkspaceRepository workspaceRepository,
                               LlmProviderRegistry providerRegistry,
                               AppProperties appProperties) {
        this.settingsRegistry = settingsRegistry;
        this.secretStore = secretStore;
        this.rowStore = rowStore;
        this.workspaceRepository = workspaceRepository;
        this.providerRegistry = providerRegistry;
        this.appProperties = appProperties;
    }

    // ------------------------------------------------------------------ //
    // 一、工作区（独立表）
    // ------------------------------------------------------------------ //

    /**
     * 列出全部工作区，并给出当前生效的 id。
     *
     * <p>与 Python 侧一致：active 标记只是「冗余提示」，权威值是被选中的那个 id；
     * 若库里存的 active_id 悬空（指向已删除的工作区），这里返回空串而顺手改库，
     * 真正的修正在 update / delete 里做（这两个动作才会重写 active_id）。</p>
     *
     * @return 工作区列表（w-default 在前，其余按编号顺序）+ 当前生效 id
     */
    @Override
    public SettingDtos.WorkspacesView listWorkspaces() {
        List<Workspace> rows = ensureMigrated();
        String storedActiveId = readActiveId();
        List<SettingDtos.WorkspaceProfile> profiles = new ArrayList<>(rows.size());
        for (Workspace row : rows) {
            boolean active = !storedActiveId.isEmpty() && storedActiveId.equals(row.getId());
            profiles.add(toProfile(row, active));
        }
        // 以「列表里 active=true 的那个」为权威 id：一个工作区都没有时为空串
        String activeId = profiles.stream()
                .filter(SettingDtos.WorkspaceProfile::active)
                .map(SettingDtos.WorkspaceProfile::id)
                .findFirst()
                .orElse("");
        return new SettingDtos.WorkspacesView(profiles, activeId);
    }

    /**
     * 新建工作区；若这是第一个工作区，它会自动成为当前工作区。
     *
     * @param request 名称与根目录
     * @return 新建出的工作区
     */
    @Override
    public SettingDtos.WorkspaceProfile createWorkspace(SettingDtos.WorkspaceCreateRequest request) {
        List<Workspace> rows = ensureMigrated();
        Workspace workspace = new Workspace();
        workspace.setId(nextWorkspaceId(rows));
        String name = request.name() == null ? "" : request.name().trim();
        workspace.setName(name.isEmpty() ? DEFAULT_WORKSPACE_NAME : name);
        workspace.setRoots(normalizeRoots(request.roots()));
        workspaceRepository.save(workspace);

        String activeId = readActiveId();
        if (activeId.isEmpty()) {
            // 第一个工作区自动生效：否则用户新建完还得手动切一次，体验断档
            activeId = workspace.getId();
            writeActiveId(activeId);
        }
        return toProfile(workspace, workspace.getId().equals(activeId));
    }

    /**
     * 更新工作区的名称和/或根目录（字段为 null 表示「保持原值」）。
     *
     * @param workspaceId 工作区 id
     * @param request     新名称与新根目录，均可为 null
     * @return 更新后的工作区
     * @throws ApiException code=404 该 id 不存在
     */
    @Override
    public SettingDtos.WorkspaceProfile updateWorkspace(String workspaceId,
                                                        SettingDtos.WorkspaceUpdateRequest request) {
        ensureMigrated();
        Workspace workspace = workspaceRepository.findById(workspaceId)
                .orElseThrow(() -> new ApiException(404, "工作区不存在：" + workspaceId));

        if (request.name() != null) {
            String trimmed = request.name().trim();
            // 空名会渲染出一个看不见的工作区，这里直接忽略而不是把名字清空
            if (!trimmed.isEmpty()) {
                workspace.setName(trimmed);
            }
        }
        if (request.roots() != null) {
            workspace.setRoots(normalizeRoots(request.roots()));
        }
        workspaceRepository.save(workspace);

        String activeId = readActiveId();
        List<Workspace> rows = sortedWorkspaces();
        // 兜底：active_id 悬空（历史数据坏了）时顺手修正为第一个，避免「没有当前工作区」
        // 用 final 副本给 lambda 用：activeId 下面会被重新赋值，lambda 不能捕获可变量
        String currentId = activeId;
        if (!currentId.isEmpty() && rows.stream().noneMatch(row -> row.getId().equals(currentId))) {
            activeId = rows.isEmpty() ? "" : rows.get(0).getId();
            writeActiveId(activeId);
        }
        return toProfile(workspace, workspace.getId().equals(activeId));
    }

    /**
     * 删除工作区；若删掉的是当前工作区，就把当前工作区顺延到剩下的第一个。
     *
     * <p>顺延而不是置空：白名单为空在工具层意味着「不限制范围」，对用户是危险的方向。</p>
     *
     * @param workspaceId 工作区 id
     * @return deleted=是否确实删掉了一个已存在的工作区
     */
    @Override
    public SettingDtos.WorkspaceDeletedResult deleteWorkspace(String workspaceId) {
        ensureMigrated();
        if (workspaceRepository.findById(workspaceId).isEmpty()) {
            return new SettingDtos.WorkspaceDeletedResult(false);
        }
        workspaceRepository.deleteById(workspaceId);

        List<Workspace> remaining = sortedWorkspaces();
        String activeId = readActiveId();
        // 同上：给 lambda 用 final 副本，activeId 后面会按顺延结果重新赋值
        String currentId = activeId;
        boolean activeGone = currentId.equals(workspaceId)
                || remaining.stream().noneMatch(row -> row.getId().equals(currentId));
        if (activeGone) {
            activeId = remaining.isEmpty() ? "" : remaining.get(0).getId();
            writeActiveId(activeId);
        }
        return new SettingDtos.WorkspaceDeletedResult(true);
    }

    /**
     * 切换当前生效工作区。
     *
     * @param workspaceId 目标工作区 id
     * @return 切换后的当前工作区 id
     * @throws ApiException code=400 id 为空；code=404 该 id 不存在
     */
    @Override
    public SettingDtos.ActiveSwitchResult activateWorkspace(String workspaceId) {
        ensureMigrated();
        String targetId = workspaceId == null ? "" : workspaceId.trim();
        if (targetId.isEmpty()) {
            throw new ApiException(400, "请提供要切换的工作区 id（字段 id 或 workspace_id）");
        }
        boolean exists = sortedWorkspaces().stream().anyMatch(row -> row.getId().equals(targetId));
        if (!exists) {
            throw new ApiException(404, "工作区不存在：" + targetId);
        }
        writeActiveId(targetId);
        return new SettingDtos.ActiveSwitchResult(targetId);
    }

    // ------------------------------------------------------------------ //
    // 一·补、历史遗留的扁平工作区根目录接口
    // ------------------------------------------------------------------ //

    /**
     * 读取旧版扁平接口（{@code GET /api/settings/workspace}）的根目录列表。
     *
     * <p>为什么还要保留这条接口：前端扫描目录的代码仍在调用单数的 /settings/workspace；
     * 它读的是旧键 {@code workspace_roots}，与独立表 workspace 是两套数据，互不干扰。</p>
     *
     * @return 现存目录的绝对路径列表；从未配置或配置无法解析时为空列表
     */
    @Override
    public List<String> getWorkspaceRoots() {
        Optional<String> raw = rowStore.read(LEGACY_ROOTS_KEY);
        if (raw.isEmpty() || raw.get().isBlank()) {
            return new ArrayList<>();
        }
        List<String> configured = new ArrayList<>();
        try {
            for (Object item : JsonUtils.parseList(raw.get())) {
                if (item instanceof String text) {
                    configured.add(text);
                }
            }
        } catch (RuntimeException e) {
            // 手工改库写坏了不该让设置页整体 500：按「没配置过」处理
            log.warn("旧的 workspace_roots 无法解析，按未配置处理：{}", e.getMessage());
            return new ArrayList<>();
        }
        // 只返回真实存在的目录：目录被删或移动后，旧配置不能继续当工具白名单用
        List<String> existing = new ArrayList<>();
        for (String root : normalizeRoots(configured)) {
            if (isExistingDirectory(root)) {
                existing.add(root);
            }
        }
        return existing;
    }

    /**
     * 覆盖式保存旧版扁平接口的根目录列表。
     *
     * <p>只把真实存在的目录落库（与 Python set_workspace_roots 一致）：这样读取端
     * 拿到的一定是可用路径，也避免把用户的笔误永久写进配置。</p>
     *
     * @param paths 用户选定的目录列表；null 与空列表都表示清除限制
     * @return 真正落库的目录列表
     */
    @Override
    public List<String> setWorkspaceRoots(List<String> paths) {
        List<String> valid = new ArrayList<>();
        if (paths != null) {
            for (String path : normalizeRoots(paths)) {
                if (isExistingDirectory(path)) {
                    valid.add(path);
                }
            }
        }
        rowStore.write(LEGACY_ROOTS_KEY, JsonUtils.toJson(valid));
        return valid;
    }

    // ------------------------------------------------------------------ //
    // 二、普通设置
    // ------------------------------------------------------------------ //

    /**
     * 读取全部非密钥设置项。
     *
     * <p>安全红线：任何密钥都不会出现在这个响应里（既没有明文，也没有脱敏值）。</p>
     *
     * @return 键值对
     */
    @Override
    public SettingDtos.SettingsView getSettings() {
        Map<String, Object> allSettings = settingsRegistry.getAllSettings();
        //allSettings.put(KEY_WORKSPACES , listWorkspaces());
        return new SettingDtos.SettingsView(allSettings);
    }

    /**
     * 读取全部设置项的 schema（只含元数据、不含当前值），供设置页自动渲染。
     *
     * @return 按键名升序的设置项描述
     */
    @Override
    public List<SettingDtos.SettingMeta> getSettingsMeta() {
        return settingsRegistry.listDefs().stream()
                .map(SettingDefinition::toMeta)
                .toList();
    }

    /**
     * 批量保存普通设置：全部校验通过后一次性落库，任何一个键非法就整批拒绝。
     *
     * @param request 要保存的键值对
     * @return 保存后的全部设置值
     */
    @Override
    public SettingDtos.SettingsView saveSettings(SettingDtos.SettingsBatchRequest request) {
        // 请求体里没写 values 时按「一个都不改」处理：GET 与 PUT 用同一个视图，前端可能只回传部分字段
        Map<String, Object> values = request == null || request.values() == null ? Map.of() : request.values();
        return new SettingDtos.SettingsView(settingsRegistry.putSettings(values));
    }

    // ------------------------------------------------------------------ //
    // 三、配置导入导出
    // ------------------------------------------------------------------ //

    /**
     * 导出当前全部非密钥设置（已脱敏），供用户备份或迁移到另一台机器。
     *
     * @return 导出快照
     */
    @Override
    public SettingDtos.SettingsExport exportSettings() {
        Map<String, Object> raw = settingsRegistry.getAllSettings();
        Map<String, Object> values = new LinkedHashMap<>();
        List<String> redactedKeys = new ArrayList<>();
        for (Map.Entry<String, Object> entry : raw.entrySet()) {
            Object cleaned = SettingsRedactor.redact(entry.getValue(), entry.getKey());
            // 用 JSON 文本比较而不是引用比较：脱敏会重建容器，引用必然不同
            if (!sameJson(cleaned, entry.getValue())) {
                // 值里含疑似密钥（典型是 mcp.servers 的 env / headers）：
                // 整个值都不导出，只留占位提示，避免「看着像脱敏了其实结构还在」的误判
                values.put(entry.getKey(), REDACTED);
                redactedKeys.add(entry.getKey());
            } else {
                values.put(entry.getKey(), entry.getValue());
            }
        }
        List<SettingDtos.SecretPoint> secrets = secretKeyNames().stream()
                .map(name -> new SettingDtos.SecretPoint(name, secretStore.hasSecret(name)))
                .toList();
        String exportedAt = LocalDateTime.now().truncatedTo(ChronoUnit.SECONDS).toString();
        return new SettingDtos.SettingsExport(EXPORT_FORMAT, exportedAt, appProperties.getVersion(),
                values, redactedKeys, secrets);
    }

    /**
     * 导入一份配置：逐键取舍，只写本机认识且未被脱敏的键，其余如实记进 skipped。
     *
     * <p>为什么不像 PUT /settings 那样整批原子：配置文件是跨机器/跨版本搬来的，
     * 里面必然有本机没声明的键；整批失败会让用户只能手工删 JSON。</p>
     *
     * @param request 导入内容
     * @return applied / skipped / 导入后的全量设置
     * @throws ApiException code=400 格式不认识或 values 缺失
     */
    @Override
    public SettingDtos.SettingsImportResult importSettings(SettingDtos.SettingsImportRequest request) {
        if (request == null) {
            throw new ApiException(400, "配置内容必须是一个 JSON 对象");
        }
        String format = request.format();
        if (format != null && !format.isBlank() && !EXPORT_FORMAT.equals(format)) {
            throw new ApiException(400, "不认识的配置格式：" + format + "（本机只支持 " + EXPORT_FORMAT + "）");
        }
        Map<String, Object> candidate = request.values();
        if (candidate == null) {
            throw new ApiException(400, "配置内容缺少 values 字段（或它不是对象）");
        }
        Set<String> payloadRedacted = request.redactedKeys() == null
                ? Set.of()
                : new HashSet<>(request.redactedKeys());

        Map<String, Object> accepted = new LinkedHashMap<>();
        List<SettingDtos.ImportSkipped> skipped = new ArrayList<>();
        for (Map.Entry<String, Object> entry : candidate.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();
            if (key == null) {
                skipped.add(new SettingDtos.ImportSkipped("null", "键名不是字符串"));
                continue;
            }
            // 密钥命名空间先判：secrets.* 根本没有声明，先走 get_def 只会得到
            // 「本机未声明的设置键」这种误导性的原因，用户就不知道该去填写密钥了
            if (key.startsWith(SettingsRegistry.SECRET_KEY_PREFIX)) {
                skipped.add(new SettingDtos.ImportSkipped(key, "密钥不随配置导入，请到设置页单独填写"));
                continue;
            }
            Optional<SettingDefinition> definition = settingsRegistry.findDef(key);
            if (definition.isEmpty()) {
                skipped.add(new SettingDtos.ImportSkipped(key, "本机未声明的设置键"));
                continue;
            }
            if (definition.get().secret()) {
                skipped.add(new SettingDtos.ImportSkipped(key, "密钥不随配置导入，请到设置页单独填写"));
                continue;
            }
            if (payloadRedacted.contains(key) || REDACTED.equals(value)) {
                skipped.add(new SettingDtos.ImportSkipped(key, "导出时已脱敏，导入会污染配置"));
                continue;
            }
            try {
                // 先单键试算：只把合法的键交给 putSettings，避免「一个坏键拖垮整份配置」
                definition.get().coerce(value);
            } catch (ApiException e) {
                skipped.add(new SettingDtos.ImportSkipped(key, "值不合法：" + e.getMessage()));
                continue;
            }
            accepted.put(key, value);
        }

        Map<String, Object> values = accepted.isEmpty()
                ? settingsRegistry.getAllSettings()
                : settingsRegistry.putSettings(accepted);
        List<String> applied = new ArrayList<>(accepted.keySet());
        applied.sort(Comparator.naturalOrder());
        return new SettingDtos.SettingsImportResult(applied, skipped, values);
    }

    // ------------------------------------------------------------------ //
    // 四、密钥
    // ------------------------------------------------------------------ //

    /**
     * 查询某个密钥是否已设置（只回脱敏值）。
     *
     * @param key 密钥名（不带 secrets. 前缀），如 deepseek.api_key
     * @return set=是否已设置；masked=脱敏值或 null
     */
    @Override
    public SettingDtos.SecretStatus getSecretStatus(String key) {
        return new SettingDtos.SecretStatus(secretStore.hasSecret(key), secretStore.maskedSecret(key));
    }

    /**
     * 保存一个密钥（覆盖式写入），返回脱敏状态，前端无需再发一次 GET。
     *
     * @param key     密钥名
     * @param request 密钥明文
     * @return set=true + 打码后的值
     * @throws ApiException code=400 密钥名或密钥值为空
     */
    @Override
    public SettingDtos.SecretStatus putSecret(String key, SettingDtos.SecretPutRequest request) {
        if (key == null || key.isBlank()) {
            throw new ApiException(400, "密钥名不能为空");
        }
        String value = request == null ? null : request.value();
        if (value == null || value.isEmpty()) {
            // 空值不等同于「清空」：清空必须走删除接口，否则用户会误以为保存成功
            throw new ApiException(400, "密钥值不能为空（如需清空请用删除接口）");
        }
        secretStore.setSecret(key, value);
        return new SettingDtos.SecretStatus(true, SecretStore.maskSecret(value));
    }

    /**
     * 删除一个密钥，使其回到「未设置」状态。
     *
     * @param key 密钥名
     * @return 是否确实删掉了一个已存在的密钥（本来就没有时为 false）
     */
    @Override
    public SettingDtos.SecretDeletedResult deleteSecret(String key) {
        return new SettingDtos.SecretDeletedResult(secretStore.deleteSecret(key));
    }

    // ------------------------------------------------------------------ //
    // 五、内部工具
    // ------------------------------------------------------------------ //

    /**
     * 保证工作区表里有数据：空表时从旧版本数据做一次只读迁移。
     *
     * @return 按展示顺序排好的工作区行
     */
    private List<Workspace> ensureMigrated() {
        List<Workspace> rows = sortedWorkspaces();
        if (!rows.isEmpty()) {
            return rows;
        }
        // 迁移只做一次：打上标记后，用户把工作区全删光也不会被旧数据复活
        if (rowStore.read(KEY_MIGRATED).isPresent()) {
            return rows;
        }
        boolean migrated = migrateFromProfilesJson() || migrateFromLegacyRoots();
        if (migrated) {
            log.info("已从旧版本数据迁移出工作区（独立表 workspace）");
        }
        // 无论迁移到东西没有都打标记：否则每次列表都重新扫旧数据，且用户删光工作区后会被旧数据复活
        rowStore.write(KEY_MIGRATED, JsonUtils.toJson("1"));
        List<Workspace> migratedRows = sortedWorkspaces();
        // 迁移出来的工作区必须有一个生效，否则设置页会显示「没有当前工作区」，用户还得手动切一次
        if (migrated && readActiveId().isEmpty() && !migratedRows.isEmpty()) {
            writeActiveId(migratedRows.get(0).getId());
        }
        return migratedRows;
    }

    /**
     * 迁移来源一：Python 版本的 workspaces.list（多工作区 JSON 数组）。
     *
     * @return true 表示至少迁移出 / 认领了一个工作区
     */
    private boolean migrateFromProfilesJson() {
        Optional<String> rawText = rowStore.read(LEGACY_PROFILES_KEY);
        if (rawText.isEmpty() || rawText.get().isBlank()) {
            return false;
        }
        List<Object> items;
        try {
            items = JsonUtils.parseList(rawText.get());
        } catch (RuntimeException e) {
            log.warn("旧工作区数据无法解析，跳过迁移：{}", e.getMessage());
            return false;
        }
        boolean saved = false;
        Set<String> usedIds = new HashSet<>();
        for (Object item : items) {
            if (!(item instanceof Map<?, ?> map)) {
                continue;
            }
            String id = textOf(map.get("id"));
            if (id.isEmpty()) {
                id = nextWorkspaceIdFrom(usedIds);
            }
            if (!usedIds.add(id)) {
                // 重复 id 会让「按 id 定位」变得不确定，直接跳过后者
                continue;
            }
            Workspace workspace = new Workspace();
            workspace.setId(id);
            String name = textOf(map.get("name"));
            workspace.setName(name.isEmpty() ? id : name);
            workspace.setRoots(normalizeRoots(rootsOf(map.get("roots"))));
            workspaceRepository.save(workspace);
            saved = true;
        }
        return saved;
    }

    /**
     * 迁移来源二：更早版本的扁平键 workspace_roots（只读；旧键原样保留，方便用户手工回退）。
     *
     * @return true 表示迁移出了一个默认工作区
     */
    private boolean migrateFromLegacyRoots() {
        Optional<String> rawText = rowStore.read(LEGACY_ROOTS_KEY);
        if (rawText.isEmpty() || rawText.get().isBlank()) {
            return false;
        }
        List<Object> items;
        try {
            items = JsonUtils.parseList(rawText.get());
        } catch (RuntimeException e) {
            log.warn("旧的 workspace_roots 无法解析，跳过迁移：{}", e.getMessage());
            return false;
        }
        List<String> candidates = new ArrayList<>();
        for (Object item : items) {
            if (item instanceof String text) {
                candidates.add(text);
            }
        }
        // 只迁移当前真实存在的目录：全是死路径时宁可当作没有旧数据，
        // 也不要造出一个「看着有配置、实际全是死路径」的工作区
        List<String> existing = normalizeRoots(candidates).stream()
                .filter(this::isExistingDirectory)
                .toList();
        if (existing.isEmpty()) {
            return false;
        }
        Workspace workspace = new Workspace();
        workspace.setId(DEFAULT_WORKSPACE_ID);
        workspace.setName(DEFAULT_WORKSPACE_NAME);
        workspace.setRoots(new ArrayList<>(existing));
        workspaceRepository.save(workspace);
        // 只有当前还没有生效工作区时才抢占：避免把用户已经选好的工作区改掉
        if (readActiveId().isEmpty()) {
            writeActiveId(DEFAULT_WORKSPACE_ID);
        }
        return true;
    }

    /**
     * 判断路径是否是一个当前真实存在的目录；判断本身出错时按「不存在」处理。
     *
     * @param text 绝对路径字符串
     * @return true 表示是现存目录
     */
    private boolean isExistingDirectory(String text) {
        try {
            return Files.isDirectory(Path.of(text));
        } catch (RuntimeException e) {
            // 非法路径、断开的网络盘等都会在这里抛错
            return false;
        }
    }

    /**
     * 读取当前生效的工作区 id。
     *
     * @return id 字符串；未配置时为空串
     */
    private String readActiveId() {
        Optional<String> raw = rowStore.read(KEY_ACTIVE_ID);
        if (raw.isEmpty() || raw.get().isBlank()) {
            return "";
        }
        try {
            Object parsed = JsonUtils.parse(raw.get(), Object.class);
            if (parsed instanceof String text) {
                return text.trim();
            }
            if (parsed != null) {
                return String.valueOf(parsed).trim();
            }
        } catch (RuntimeException e) {
            // 旧数据可能是不带引号的裸 id，落到下面的兜底解析
            log.debug("active_id 不是合法 JSON，按原始文本解析：{}", e.getMessage());
        }
        return raw.get().trim();
    }

    /**
     * 写入当前生效的工作区 id（以 JSON 字符串形式存，和普通设置值的存法保持一致）。
     *
     * @param workspaceId 工作区 id；空串表示「当前没有生效的工作区」
     */
    private void writeActiveId(String workspaceId) {
        rowStore.write(KEY_ACTIVE_ID, JsonUtils.toJson(workspaceId));
    }

    /**
     * 读取全部工作区并排序。
     *
     * @return w-default 在前，其余按 w-<编号> 的数字顺序升序
     */
    private List<Workspace> sortedWorkspaces() {
        List<Workspace> rows = new ArrayList<>(workspaceRepository.findAll());
        rows.sort(Comparator
                .comparingInt((Workspace row) -> workspaceOrder(row.getId()))
                .thenComparing(row -> row.getId() == null ? "" : row.getId()));
        return rows;
    }

    /**
     * 计算工作区的展示顺序：数字编号越小越靠前，非数字 id（如 w-default）排最前。
     *
     * @param id 工作区 id
     * @return 排序键
     */
    private static int workspaceOrder(String id) {
        if (id == null || !id.startsWith(WORKSPACE_ID_PREFIX)) {
            return -1;
        }
        try {
            return Integer.parseInt(id.substring(WORKSPACE_ID_PREFIX.length()));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /**
     * 生成一个不与现有 id 冲突的编号（w-1、w-2……）。
     *
     * @param rows 现有工作区
     * @return 新 id
     */
    private String nextWorkspaceId(List<Workspace> rows) {
        Set<String> used = new HashSet<>();
        for (Workspace row : rows) {
            used.add(row.getId());
        }
        return nextWorkspaceIdFrom(used);
    }

    /**
     * 从已占用 id 集合里找最小空闲编号。
     *
     * @param usedIds 已占用的 id
     * @return 新 id
     */
    private String nextWorkspaceIdFrom(Set<String> usedIds) {
        int index = 1;
        while (usedIds.contains(WORKSPACE_ID_PREFIX + index)) {
            index++;
        }
        return WORKSPACE_ID_PREFIX + index;
    }

    /**
     * 把任意值读成字符串（迁移旧数据时字段可能缺失或类型不对）。
     *
     * @param value 任意值
     * @return 去掉首尾空白的字符串；null 或空值返回空串
     */
    private static String textOf(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 把旧数据里的 roots 字段读成字符串列表（只收字符串元素。
     *
     * @param value 任意值
     * @return 字符串列表；不是数组时返回空列表
     */
    private static List<String> rootsOf(Object value) {
        List<String> result = new ArrayList<>();
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof String text) {
                    result.add(text);
                }
            }
        }
        return result;
    }

    /**
     * 归一化根目录：去首尾空白、去掉空项、按原顺序去重。
     *
     * @param roots 原始列表；null 视为空
     * @return 归一化后的新列表（可安全修改）
     */
    private List<String> normalizeRoots(List<String> roots) {
        if (roots == null) {
            return new ArrayList<>();
        }
        Set<String> seen = new LinkedHashSet<>();
        for (String root : roots) {
            if (root == null) {
                continue;
            }
            String trimmed = root.trim();
            if (!trimmed.isEmpty()) {
                seen.add(trimmed);
            }
        }
        return new ArrayList<>(seen);
    }

    /**
     * 把实体转成接口返回的工作区对象。
     *
     * @param workspace 工作区实体
     * @param active    是否当前生效
     * @return 接口用的 profile
     */
    private SettingDtos.WorkspaceProfile toProfile(Workspace workspace, boolean active) {
        List<String> roots = workspace.getRoots() == null
                ? new ArrayList<>()
                : new ArrayList<>(workspace.getRoots());
        return new SettingDtos.WorkspaceProfile(workspace.getId(), workspace.getName(), roots, active);
    }

    /**
     * 列出本应用可能用到的全部密钥名（去重、保持供应商顺序）。
     *
     * @return 密钥名列表，如 ["deepseek.api_key", ...]
     */
    private List<String> secretKeyNames() {
        Set<String> names = new LinkedHashSet<>();
        for (var provider : providerRegistry.listProviders()) {
            // secret_key 为空表示这家供应商不需要密钥（例如本地 Ollama）
            if (provider.secretKey() != null && !provider.secretKey().isBlank()) {
                names.add(provider.secretKey());
            }
        }
        return new ArrayList<>(names);
    }

    /**
     * 判断两个值在 JSON 层面是否完全相等（用于检测脱敏是否真的改动了内容）。
     *
     * @param left  第一个值
     * @param right 第二个值
     * @return true 表示序列化结果一致
     */
    private boolean sameJson(Object left, Object right) {
        return Objects.equals(JsonUtils.toJson(left), JsonUtils.toJson(right));
    }
}
