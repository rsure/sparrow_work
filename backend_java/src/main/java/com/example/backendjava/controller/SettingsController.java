// 模块说明：设置体系接口，路径与 Python 侧 /api/settings/* 一致。
package com.example.backendjava.controller;

// Spring Bean 查找器：Service 未实现时返回 501
import org.springframework.beans.factory.ObjectProvider;
// Spring Web 注解：REST 控制器
import org.springframework.web.bind.annotation.RestController;
// Spring Web 注解：统一路径前缀 /settings
import org.springframework.web.bind.annotation.RequestMapping;
// Spring Web 注解：GET 映射
import org.springframework.web.bind.annotation.GetMapping;
// Spring Web 注解：POST 映射
import org.springframework.web.bind.annotation.PostMapping;
// Spring Web 注解：PUT 映射
import org.springframework.web.bind.annotation.PutMapping;
// Spring Web 注解：DELETE 映射
import org.springframework.web.bind.annotation.DeleteMapping;
// Spring Web 注解：路径变量
import org.springframework.web.bind.annotation.PathVariable;
// Spring Web 注解：JSON 请求体
import org.springframework.web.bind.annotation.RequestBody;
// Jakarta 校验注解
import jakarta.validation.Valid;
// 项目内统一响应外壳
import com.example.backendjava.common.ApiResponse;
// 项目内 Service 获取工具
import com.example.backendjava.util.ServiceSupport;
// 设置业务接口：设置项读写与工作区管理
import com.example.backendjava.service.SettingsService;
// 设置接口的请求/响应 DTO 容器
import com.example.backendjava.dto.SettingDtos;

// 标准库：List 用于设置项与根目录列表
import java.util.List;

/**
 * 设置体系接口。
 *
 * <p>所有端点都在 {@code /api/settings} 下；普通设置与密钥设置分为两组，
 * 密钥只进不出（查询只返回是否设置与脱敏值）。</p>
 */
@RestController
@RequestMapping("/settings")
public class SettingsController {

    /** 设置服务；学习者实现后自动注入。 */
    private final ObjectProvider<SettingsService> settingsService;

    /**
     * 构造器注入可选 Service。
     *
     * @param settingsService Spring 的按类型查找器
     */
    public SettingsController(ObjectProvider<SettingsService> settingsService) {
        this.settingsService = settingsService;
    }

    // ======================================================================= //
    // 1. 工作区
    // ======================================================================= //

    /**
     * 读取历史遗留的扁平工作区根目录（单数路径，前端扫描功能仍在用）。
     *
     * @return 现存目录的绝对路径列表
     */
    @GetMapping("/workspace")
    public ApiResponse<List<String>> getWorkspaceRoots() {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").getWorkspaceRoots());
    }

    /**
     * 覆盖式保存历史遗留的扁平工作区根目录。
     *
     * @param request 根目录列表
     * @return 过滤掉不存在项后真正生效的目录列表
     */
    @PutMapping("/workspace")
    public ApiResponse<List<String>> setWorkspaceRoots(
            @RequestBody SettingDtos.WorkspacePathsRequest request
    ) {
        List<String> paths = request == null ? null : request.paths();
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").setWorkspaceRoots(paths));
    }


    /**
     * 读取全部工作区。
     *
     * @return 工作区列表
     */
    @GetMapping("/workspaces")
    public ApiResponse<SettingDtos.WorkspacesView> listWorkspaces() {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").listWorkspaces());
    }

    /**
     * 新建工作区。
     *
     * @param request 新建请求
     * @return 新建出的工作区
     */
    @PostMapping("/workspaces")
    public ApiResponse<SettingDtos.WorkspaceProfile> createWorkspace(
            @Valid @RequestBody SettingDtos.WorkspaceCreateRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").createWorkspace(request));
    }

    /**
     * 更新工作区。
     *
     * @param workspaceId 工作区 id
     * @param request     更新请求
     * @return 更新后的工作区
     */
    @PutMapping("/workspaces/{workspaceId}")
    public ApiResponse<SettingDtos.WorkspaceProfile> updateWorkspace(
            @PathVariable String workspaceId,
            @RequestBody SettingDtos.WorkspaceUpdateRequest request
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(settingsService, "设置服务").updateWorkspace(workspaceId, request)
        );
    }

    /**
     * 删除工作区。
     *
     * @param workspaceId 工作区 id
     * @return 删除结果
     */
    @DeleteMapping("/workspaces/{workspaceId}")
    public ApiResponse<SettingDtos.WorkspaceDeletedResult> deleteWorkspace(
            @PathVariable String workspaceId
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(settingsService, "设置服务").deleteWorkspace(workspaceId)
        );
    }

    /**
     * 切换当前工作区。
     *
     * @param request 目标工作区 id
     * @return 切换结果
     */
    @PostMapping("/workspaces/active")
    public ApiResponse<SettingDtos.ActiveSwitchResult> activateWorkspace(
            @RequestBody SettingDtos.WorkspaceActiveRequest request
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(settingsService, "设置服务").activateWorkspace(request.resolveId())
        );
    }

    // ======================================================================= //
    // 2. 普通设置
    // ======================================================================= //

    /**
     * 读取全部非密钥设置项。
     *
     * @return 设置值
     */
    @GetMapping
    public ApiResponse<SettingDtos.SettingsView> getSettings() {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").getSettings());
    }

    /**
     * 读取设置项 schema。
     *
     * @return 设置项描述列表
     */
    @GetMapping("/meta")
    public ApiResponse<List<SettingDtos.SettingMeta>> getSettingsMeta() {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").getSettingsMeta());
    }

    /**
     * 批量保存普通设置。
     *
     * @param request 要保存的键值对
     * @return 保存后的设置值
     */
    @PutMapping
    public ApiResponse<SettingDtos.SettingsView> saveSettings(
            @RequestBody SettingDtos.SettingsBatchRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").saveSettings(request));
    }

    // ======================================================================= //
    // 3. 导入 / 导出 / 密钥
    // ======================================================================= //

    /**
     * 导出脱敏配置。
     *
     * @return 导出结果
     */
    @GetMapping("/export")
    public ApiResponse<SettingDtos.SettingsExport> exportSettings() {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").exportSettings());
    }

    /**
     * 导入脱敏配置。
     *
     * @param request 导入请求
     * @return 导入结果
     */
    @PostMapping("/import")
    public ApiResponse<SettingDtos.SettingsImportResult> importSettings(
            @RequestBody SettingDtos.SettingsImportRequest request
    ) {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").importSettings(request));
    }

    /**
     * 查询密钥是否已设置。
     *
     * @param key 密钥名
     * @return 脱敏状态
     */
    @GetMapping("/secrets/{key}")
    public ApiResponse<SettingDtos.SecretStatus> getSecretStatus(@PathVariable String key) {
        return ApiResponse.ok(
                ServiceSupport.require(settingsService, "设置服务").getSecretStatus(key)
        );
    }

    /**
     * 保存密钥。
     *
     * @param key     密钥名
     * @param request 密钥明文
     * @return 脱敏状态
     */
    @PutMapping("/secrets/{key}")
    public ApiResponse<SettingDtos.SecretStatus> putSecret(
            @PathVariable String key,
            @Valid @RequestBody SettingDtos.SecretPutRequest request
    ) {
        return ApiResponse.ok(
                ServiceSupport.require(settingsService, "设置服务").putSecret(key, request)
        );
    }

    /**
     * 删除密钥。
     *
     * @param key 密钥名
     * @return deleted=是否确实删掉了一个已存在的密钥
     */
    @DeleteMapping("/secrets/{key}")
    public ApiResponse<SettingDtos.SecretDeletedResult> deleteSecret(@PathVariable String key) {
        return ApiResponse.ok(ServiceSupport.require(settingsService, "设置服务").deleteSecret(key));
    }
}
