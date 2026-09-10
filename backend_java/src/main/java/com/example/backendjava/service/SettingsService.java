// 模块说明：设置体系业务接口。实现建议用 app_settings 表 + 类型校验，密钥单独存钥匙串。
package com.example.backendjava.service;

// 标准库：List 用于工作区根目录、设置项清单、导入结果
import java.util.List;

// 设置接口的请求/响应 DTO 容器
import com.example.backendjava.dto.SettingDtos;

/**
 * 设置服务接口。
 */
public interface SettingsService {



    /**
     * 列出全部工作区 profile。
     *
     * @return 工作区列表与当前生效 id
     */
    SettingDtos.WorkspacesView listWorkspaces();

    /**
     * 新建工作区。
     *
     * @param request 新建请求
     * @return 新建出的工作区
     */
    SettingDtos.WorkspaceProfile createWorkspace(SettingDtos.WorkspaceCreateRequest request);

    /**
     * 更新工作区名称/根目录。
     *
     * @param workspaceId 工作区 id
     * @param request     更新请求
     * @return 更新后的工作区
     */
    SettingDtos.WorkspaceProfile updateWorkspace(
            String workspaceId,
            SettingDtos.WorkspaceUpdateRequest request
    );

    /**
     * 删除工作区。
     *
     * @param workspaceId 工作区 id
     * @return 是否确实删除了一个已存在的工作区
     */
    SettingDtos.WorkspaceDeletedResult deleteWorkspace(String workspaceId);

    /**
     * 切换当前工作区。
     *
     * @param workspaceId 目标工作区 id
     * @return 切换后的当前工作区 id
     */
    SettingDtos.ActiveSwitchResult activateWorkspace(String workspaceId);

    /**
     * 读取历史遗留的扁平工作区根目录（GET /api/settings/workspace）。
     *
     * <p>这条接口对应 Python 侧 setting_service.get_workspace_roots：读的是旧键
     * {@code workspace_roots}，并且只返回当前真实存在的目录。</p>
     *
     * @return 现存目录的绝对路径列表；从未配置时为空列表
     */
    List<String> getWorkspaceRoots();

    /**
     * 覆盖式保存历史遗留的扁平工作区根目录（PUT /api/settings/workspace）。
     *
     * @param paths 用户选定的目录绝对路径列表；空列表表示清除限制
     * @return 过滤掉不存在项之后、真正落库的目录列表
     */
    List<String> setWorkspaceRoots(List<String> paths);

    /**
     * 读取全部非密钥设置项。
     *
     * @return 设置键值对
     */
    SettingDtos.SettingsView getSettings();

    /**
     * 读取全部设置项的 schema。
     *
     * @return 设置项描述列表
     */
    List<SettingDtos.SettingMeta> getSettingsMeta();

    /**
     * 批量保存普通设置。
     *
     * @param request 要保存的键值对
     * @return 保存后的全部设置值
     */
    SettingDtos.SettingsView saveSettings(SettingDtos.SettingsBatchRequest request);

    /**
     * 导出脱敏配置。
     *
     * @return 导出结果
     */
    SettingDtos.SettingsExport exportSettings();

    /**
     * 导入脱敏配置。
     *
     * @param request 导入请求
     * @return 导入结果
     */
    SettingDtos.SettingsImportResult importSettings(SettingDtos.SettingsImportRequest request);

    /**
     * 查询某个密钥是否已设置。
     *
     * @param key 密钥名（不带 secrets. 前缀）
     * @return 脱敏状态
     */
    SettingDtos.SecretStatus getSecretStatus(String key);

    /**
     * 保存某个密钥。
     *
     * @param key     密钥名
     * @param request 密钥明文
     * @return 保存后的脱敏状态
     */
    SettingDtos.SecretStatus putSecret(String key, SettingDtos.SecretPutRequest request);

    /**
     * 删除某个密钥。
     *
     * @param key 密钥名
     * @return 是否确实删掉了一个已存在的密钥（本来就没有时为 false，不视为错误）
     */
    SettingDtos.SecretDeletedResult deleteSecret(String key);
}
