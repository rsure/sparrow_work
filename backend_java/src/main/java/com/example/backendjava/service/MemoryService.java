// 模块说明：工作区记忆业务接口。实现建议用 SQLite 存正文、用 EmbeddingModel 生成向量。
package com.example.backendjava.service;

// Spring MVC 的 SSE 发射器：检索问答是流式返回
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

// 标准库：Map 用于动态返回结构
import java.util.Map;

// 记忆接口的请求/响应 DTO 容器
import com.example.backendjava.dto.MemoryDtos;

/**
 * 记忆服务接口。
 */
public interface MemoryService {

    /**
     * 列出当前工作区的记忆。
     *
     * @param workspaceId 工作区 id；null 表示当前 active
     * @param category    只看某一类；null 表示全部
     * @param limit       最多返回多少条
     * @return 形如 {"workspace_id","enabled","memories":[...]}
     */
    Map<String, Object> list(String workspaceId, String category, int limit);

    /**
     * 返回记忆条数与分类分布。
     *
     * @param workspaceId 工作区 id；null 表示当前 active
     * @return 形如 {"workspace_id","total","by_category":{...}}
     */
    Map<String, Object> stats(String workspaceId);

    /**
     * 本地相似度检索（不调用大模型）。
     *
     * @param request 检索请求
     * @return 形如 {"workspace_id","query","hits":[...]}
     */
    Map<String, Object> search(MemoryDtos.MemorySearchRequest request);

    /**
     * 检索记忆并用大模型回答（SSE 流式）。
     *
     * @param request 检索请求
     * @return SSE 发射器
     */
    SseEmitter query(MemoryDtos.MemorySearchRequest request);

    /**
     * 手动新增一条记忆。
     *
     * @param request 新增请求
     * @return 新增后的记忆
     */
    Map<String, Object> create(MemoryDtos.MemoryCreateRequest request);

    /**
     * 删除一条记忆。
     *
     * @param memoryId 记忆 id
     * @return 删除结果
     */
    Map<String, Object> delete(String memoryId);

    /**
     * 清空某个工作区的全部记忆。
     *
     * @param workspaceId 工作区 id；null 表示当前 active
     * @return 删除条数等结果
     */
    Map<String, Object> clear(String workspaceId);

    /**
     * 对某个会话手动触发一次记忆抽取。
     *
     * @param request 抽取请求
     * @return 抽取结果
     */
    Map<String, Object> extract(MemoryDtos.MemoryExtractRequest request);

    /**
     * 立即整理记忆（过期淘汰 + 条数上限）。
     *
     * @param request 维护请求
     * @return 整理结果
     */
    Map<String, Object> prune(MemoryDtos.MemoryMaintenanceRequest request);

    /**
     * 按当前向量化后端重建记忆向量。
     *
     * @param request 维护请求
     * @return 重建结果
     */
    Map<String, Object> reindex(MemoryDtos.MemoryMaintenanceRequest request);
}
