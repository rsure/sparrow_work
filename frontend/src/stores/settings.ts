/**
 * stores/settings.ts —— 设置页的全局状态层（Pinia）。
 *
 * 设计要点：
 *   - 设置页完全由「后端 meta 驱动」渲染：拿到 meta 后，按 category 分区、按 type 选控件，
 *     以后后端新增设置键，设置页零改动自动出现。
 *   - 本 store 把 meta、当前 values、各键 pending（保存中）/ error / lastSavedAt 全部纳入状态，
 *     视图层只需要 watch 这份状态就能正确反映「正在保存 / 保存失败 / 保存成功」三态。
 *   - 密钥状态（set / masked）与普通设置分开保存，因为它们的读写走不同的接口。
 *   - 任何操作失败都把错误文案写到对应字段，模板里直接渲染，无需 try/catch 一路冒泡。
 *
 * 状态归属：
 *   - meta / values / pending / errors：普通设置体系（SettingDef / SettingsMap）
 *   - secretStatuses：密钥状态（只保存 set/masked，永不保存明文）
 *   - loadError：整页拉取失败的兜底错误文案
 */

import { defineStore } from 'pinia' // Pinia 的核心 API：defineStore 创建可复用的状态模块
import {
  fetchSecretStatus,
  fetchSettings,
  fetchSettingsMeta,
  saveSecret,
  saveSettings,
  deleteSecret,
  type SecretStatus,
  type SettingDef,
  type SettingsMap,
} from '@/services/settings' // 接口封装：所有读写都走这一层

/** 单个普通设置键的运行时状态：在 SettingDef + 当前值之上，再加 pending/error/lastSavedAt 三态 */
export interface SettingEntry {
  /** 当前生效值；初次拉取前为 undefined */
  value: unknown
  /** 是否有尚未结束的保存请求（按钮可借此显示 loading） */
  pending: boolean
  /** 最近一次保存失败的文案；成功或还没保存过为空串 */
  error: string
  /** 最近一次保存成功的本地时间字符串（用于「刚刚已保存」提示）；从未成功过为空串 */
  lastSavedAt: string
}

/** 用 key 索引的设置运行时状态集合 */
export type SettingEntries = Record<string, SettingEntry>

/**
 * 新登记一条自定义模型时用的默认上下文窗口（单位：token）。
 *
 * 为什么要给默认值：用户手写一个「清单里还没有的新模型名」时，我们无从知道它真实的窗口大小，
 * 但 ARCH-5 的压缩阈值必须有这个数才能工作（缺了后端会直接丢弃这条自定义模型）。
 * 128000 是当前主流模型的常见量级，偏保守；登记后用户可以在设置页「自定义模型」里改准确值。
 */
export const DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW = 128000

/**
 * 从设置值里取出 llm.custom_models 的可写副本。
 *
 * @param value 设置里 llm.custom_models 的原始值（可能不是数组，比如用户填错了 JSON）
 * @return 只含对象元素的数组；结构不对时返回空数组，避免用一处脏数据把整次保存搞崩
 */
function readCustomModelList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is Record<string, unknown> => typeof item === 'object' && item !== null,
  )
}

/**
 * 判断某个「供应商 + 模型名」是否已经登记在自定义模型列表里（避免重复登记出多条）。
 *
 * @param list 已登记的自定义模型列表（见 readCustomModelList）
 * @param providerId 供应商 id
 * @param modelName 模型名
 * @return true 表示已登记过同名同供应商的一项
 */
function hasRegisteredModel(
  list: Array<Record<string, unknown>>,
  providerId: string,
  modelName: string,
): boolean {
  return list.some(
    (item) => String(item.provider ?? '') === providerId && String(item.model ?? '') === modelName,
  )
}

export const useSettingsStore = defineStore('settings', {
  // ------------------------------------------------------------------------ //
  // 状态字段
  // ------------------------------------------------------------------------ //
  state: () => ({
    /** 全部设置项的 meta（不含值）；首次加载完成后由视图层渲染分区 */
    meta: [] as SettingDef[],
    /** 全部非密钥设置项的当前值；后端「已落库值优先，未落库回落到默认值」 */
    values: {} as SettingsMap,
    /** 按 key 组织的运行时状态（当前值 + 三态）；meta 还没回来时为空对象 */
    entries: {} as SettingEntries,
    /** 是否正在拉取 meta + values（视图层借此显示整页 loading） */
    loading: false,
    /** 整页拉取失败的兜底错误文案；空字符串表示没出错 */
    loadError: '',
    /** 密钥状态：key → { set, masked }；按需加载，访问哪个就拉哪个 */
    secretStatuses: {} as Record<string, SecretStatus>,
  }),

  // ------------------------------------------------------------------------ //
  // 计算属性
  // ------------------------------------------------------------------------ //
  getters: {
    /** 按 category 分组的 meta 数组（保留原顺序），用于 SettingSection 自动分区渲染 */
    metaByCategory(state): Record<string, SettingDef[]> {
      const grouped: Record<string, SettingDef[]> = {}
      for (const def of state.meta) {
        const bucket = grouped[def.category] ?? []
        bucket.push(def)
        grouped[def.category] = bucket
      }
      return grouped
    },
  },

  // ------------------------------------------------------------------------ //
  // 行为
  // ------------------------------------------------------------------------ //
  actions: {
    /**
     * 首次进入设置页：并行拉 meta + 当前值，然后按 meta 把每个键的 entry 初始化好。
     * 已存在的 entry 保留其 pending/error/lastSavedAt（用户可能正在编辑它）。
     */
    async loadAll(): Promise<void> {
      this.loading = true
      this.loadError = ''
      try {
        // 并行请求减少首屏等待；任一失败由 Promise.all 抛第一个 ApiError
        const [meta, values] = await Promise.all([fetchSettingsMeta(), fetchSettings()])
        this.meta = meta
        this.values = values
        // 把每个键的 entry 初始化好；已经存在的 entry 不覆盖（保留「正在保存」标记）
        for (const def of meta) {
          if (!this.entries[def.key]) {
            this.entries[def.key] = {
              value: values[def.key] ?? def.default,
              pending: false,
              error: '',
              lastSavedAt: '',
            }
          }
        }
      } catch (err) {
        // 错误直接展示给用户；store 调用方不需要再包一层 try/catch
        this.loadError = err instanceof Error ? err.message : String(err)
      } finally {
        this.loading = false
      }
    },

    /**
     * 保存单个普通设置：调用 PUT /api/settings（仅含本次要改的键），成功后用返回值原地刷新视图。
     * 失败时把错误写到 entry.error，让控件就地显示提示，不需要切到全局错误页。
     */
    async saveOne(key: string, value: unknown): Promise<void> {
      const entry = this.entries[key]
      if (!entry) return
      // 在写入前先标记 pending，让按钮立刻变成「保存中」状态，避免用户重复点击
      entry.pending = true
      entry.error = ''
      try {
        const newValues = await saveSettings({ [key]: value })
        // 后端回的是「保存后全部设置项的当前值」，用它原地刷新视图，避免按 key 单独读一次
        this.values = newValues
        // 同步更新所有 entry 的 value（防止后续编辑用到旧值）；其它 entry 的 lastSavedAt 不清
        for (const def of this.meta) {
          if (this.entries[def.key]) {
            this.entries[def.key].value = newValues[def.key] ?? def.default
          }
        }
        entry.lastSavedAt = new Date().toLocaleTimeString()
      } catch (err) {
        entry.error = err instanceof Error ? err.message : String(err)
      } finally {
        entry.pending = false
      }
    },

    /**
     * 批量保存多键：用于 json 类型控件一次性写一整段文本的场景。
     * 任何一个键失败会整体 400（后端策略），本方法成功时才整体刷新，失败时把错误写到第一个键。
     */
    async saveMany(patch: SettingsMap): Promise<void> {
      // 把所有涉及的 key 先标 pending，让控件显示保存中
      for (const key of Object.keys(patch)) {
        if (this.entries[key]) {
          this.entries[key].pending = true
          this.entries[key].error = ''
        }
      }
      try {
        const newValues = await saveSettings(patch)
        this.values = newValues
        for (const def of this.meta) {
          if (this.entries[def.key]) {
            this.entries[def.key].value = newValues[def.key] ?? def.default
          }
        }
        for (const key of Object.keys(patch)) {
          if (this.entries[key]) this.entries[key].lastSavedAt = new Date().toLocaleTimeString()
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        // 后端失败是整批拒绝，把错误文案写到第一个键的 entry.error 上，便于控件就近展示
        const firstKey = Object.keys(patch)[0]
        if (firstKey && this.entries[firstKey]) {
          this.entries[firstKey].error = message
        }
      } finally {
        for (const key of Object.keys(patch)) {
          if (this.entries[key]) this.entries[key].pending = false
        }
      }
    },

    /**
     * 选模型：一次写入「供应商 + 模型名」，必要时把清单里没有的模型名登记成自定义模型。
     *
     * 为什么需要这一层（而不是各处直接 saveMany 两个键）：
     *   1. 内置供应商的后端只接受预置清单里的模型名（lex 报错而不是静默换模型），
     *      但厂商发布新模型的速度远快于我们更新清单，所以「手写新名字」必须能用；
     *      做法就是把它补进 llm.custom_models，之后 resolve_model_spec 就能精确命中。
     *   2. 设置页与对话页的模型面板共用这段判断，避免两边行为不一致。
     * 自定义端点（custom-*）本来就接受任意模型名，不需要登记。
     *
     * @param providerId 供应商 id，如 "deepseek" 或 "custom-myapi"
     * @param modelName 模型名，如 "deepseek-flash"（允许是清单里没有的新名字）
     * @param knownModels 该供应商预置清单里的模型名（来自 /api/llm/providers）
     * @param isCustomProvider 是否自定义端点（true 时后端接受任意模型名）
     * @return registered=是否新登记了一条自定义模型（调用方可据此提示用户「窗口值可改」）
     */
    async selectModel(
      providerId: string,
      modelName: string,
      knownModels: string[],
      isCustomProvider: boolean,
    ): Promise<{ registered: boolean }> {
      const provider = providerId.trim()
      const model = modelName.trim()
      // 缺供应商或模型名时什么都不写：半套配置比不改更危险
      if (!provider || !model) return { registered: false }

      const patch: SettingsMap = { 'llm.provider': provider, 'llm.model': model }
      const registered =
        !isCustomProvider &&
        !knownModels.includes(model) &&
        !hasRegisteredModel(
          readCustomModelList(this.values['llm.custom_models']),
          provider,
          model,
        )
      if (registered) {
        // 不改动已有条目，只在末尾追加：用户自己写过的窗口/单价不能被我们覆盖
        const next = [
          ...readCustomModelList(this.values['llm.custom_models']),
          {
            provider,
            model,
            label: model,
            context_window: DEFAULT_CUSTOM_MODEL_CONTEXT_WINDOW,
            supports_tools: true,
          },
        ]
        patch['llm.custom_models'] = next
      }
      await this.saveMany(patch)
      return { registered }
    },

    /**
     * 拉取某个密钥的状态（是否设置、脱敏值）。
     * 只保存 set/masked 两个字段——**绝不**让明文进入 store（后端也从不返回）。
     */
    async loadSecretStatus(key: string): Promise<void> {
      try {
        const status = await fetchSecretStatus(key)
        this.secretStatuses = { ...this.secretStatuses, [key]: status }
      } catch {
        // 拉取失败当作「未设置」展示，不要让设置页崩
        this.secretStatuses = {
          ...this.secretStatuses,
          [key]: { set: false, masked: null },
        }
      }
    },

    /**
     * 覆盖写入一个密钥。保存成功后用返回的脱敏值刷新本地状态。
     * 注意：传入的 value 是明文，但只用于发 PUT，函数返回后不会再保留它。
     */
    async saveSecretValue(key: string, value: string): Promise<boolean> {
      try {
        const status = await saveSecret(key, value)
        this.secretStatuses = { ...this.secretStatuses, [key]: status }
        return true
      } catch (err) {
        // 把错误抛给组件，让它显示在自己附近；store 不缓存明文
        throw err instanceof Error ? err : new Error(String(err))
      }
    },

    /** 删除某个密钥；删除成功后清掉本地缓存的状态（让它回到「未设置」） */
    async removeSecret(key: string): Promise<void> {
      try {
        await deleteSecret(key)
        const next = { ...this.secretStatuses }
        delete next[key]
        this.secretStatuses = next
      } catch (err) {
        throw err instanceof Error ? err : new Error(String(err))
      }
    },
  },
})