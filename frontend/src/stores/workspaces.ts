/**
 * stores/workspaces.ts —— 工作区多 profile 的全局状态层（Pinia）。
 *
 * 设计要点：
 *   - 工作区列表 + 当前 active id 是设置页「工作区」分区需要展示/操作的全部数据；
 *   - 每次 create/update/delete/active 操作后都重新拉一次（简单可靠，避免本地与后端脱节）；
 *   - 操作失败时把错误写到 loadError，UI 就近展示；store 不缓存中间状态。
 *
 * 不放进 settings.ts 的原因：工作区是一组对象数组（不是单键），放一起会让 keys 命名风格分裂。
 */

import { defineStore } from 'pinia' // Pinia 的核心 API：defineStore 创建可复用的状态模块
import {
  createWorkspace as apiCreateWorkspace,
  deleteWorkspace as apiDeleteWorkspace,
  fetchWorkspaces,
  setActiveWorkspace as apiSetActiveWorkspace,
  updateWorkspace as apiUpdateWorkspace,
  type Workspace,
} from '@/services/settings' // 接口封装：工作区的 CRUD + active 切换

export const useWorkspacesStore = defineStore('workspaces', {
  // ------------------------------------------------------------------------ //
  // 状态字段
  // ------------------------------------------------------------------------ //
  state: () => ({
    /** 全部工作区，按后端返回顺序（与用户创建顺序一致） */
    list: [] as Workspace[],
    /** 当前生效工作区的 id；没有工作区时为空串 */
    activeId: '',
    /** 是否正在拉取列表（首次进入 / 刷新时显示 loading） */
    loading: false,
    /** 最近一次失败的错误文案；空字符串表示没出错 */
    loadError: '',
    /** 是否有任意写操作正在执行（创建/更新/删除/切换），用于整体禁用按钮 */
    pending: false,
  }),

  // ------------------------------------------------------------------------ //
  // 计算属性
  // ------------------------------------------------------------------------ //
  getters: {
    /** 当前生效工作区对象（找不到时为 null），便于详情面板直接渲染 */
    activeWorkspace(state): Workspace | null {
      return state.list.find((w) => w.id === state.activeId) ?? null
    },
  },

  // ------------------------------------------------------------------------ //
  // 行为
  // ------------------------------------------------------------------------ //
  actions: {
    /** 拉取全部工作区；写入失败时把错误塞到 loadError 让 UI 展示 */
    async loadAll(): Promise<void> {
      this.loading = true
      this.loadError = ''
      try {
        const data = await fetchWorkspaces()
        this.list = data.workspaces
        this.activeId = data.active_id
      } catch (err) {
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.loading = false
      }
    },

    /** 创建工作区；成功后整体刷新（后端可能调整了 active_id） */
    async create(name: string, roots: string[]): Promise<void> {
      this.pending = true
      this.loadError = ''
      try {
        await apiCreateWorkspace(name, roots)
        await this.loadAll()
      } catch (err) {
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.pending = false
      }
    },

    /** 更新工作区（改名/改 roots）；patch 里没传的字段保持原值 */
    async update(id: string, patch: { name?: string; roots?: string[] }): Promise<void> {
      this.pending = true
      this.loadError = ''
      try {
        await apiUpdateWorkspace(id, patch)
        await this.loadAll()
      } catch (err) {
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.pending = false
      }
    },

    /** 删除工作区；后端若删的是当前 active，会自动顺延到下一个 */
    async remove(id: string): Promise<void> {
      this.pending = true
      this.loadError = ''
      try {
        await apiDeleteWorkspace(id)
        await this.loadAll()
      } catch (err) {
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.pending = false
      }
    },

    /** 切换当前工作区；切换后白名单自动跟随 */
    async setActive(id: string): Promise<void> {
      this.pending = true
      this.loadError = ''
      try {
        const result = await apiSetActiveWorkspace(id)
        this.activeId = result.active_id
        // 同步更新本地 active 标记；避免再发一次 list 请求
        this.list = this.list.map((w) => ({ ...w, active: w.id === result.active_id }))
      } catch (err) {
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.pending = false
      }
    },
  },
})