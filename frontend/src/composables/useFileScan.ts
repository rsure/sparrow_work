// composables/useFileScan.ts
/**
 * 模块说明：把「扫描任务的文件列表」用 SSE 增量订阅进来，并累积成页面可直接渲染的响应式状态。
 * 使用场景：扫描详情页打开/刷新时调用它，拿到 files、进度数字 loading/error 与 loadFiles 方法。
 * 关键点：后端对「进行中」和「已完成」的任务走同一套推送逻辑，所以这里只需处理 files / end / error 三种事件。
 */
// Vue 生命周期与响应式工具：onUnmounted 用来在页面卸载时断开 SSE，ref 用来存文件列表与进度数字
import { onUnmounted, ref, type Ref } from 'vue'
// 文件条目类型：SSE 推来的每个文件在结构上就是一个 FileEntry，直接用于列表渲染
import type { FileEntry } from '@/services/file'
// 扫描相关接口：scan_files_stream_url 生成 EventSource 要连的地址；
// ScanFileChunk 是每个 "files" 事件的数据结构；ScanTaskInfo 用来取任务状态这个联合类型
import { scan_files_stream_url, type ScanFileChunk, type ScanTaskInfo } from '@/services/scan'

/**
 * 通过 SSE 增量订阅扫描到的文件，累积展示；文件数/大小随进度实时更新。
 * @param taskId 要订阅的扫描任务 id（响应式 ref，变化后可再次调用 loadFiles 重新订阅）
 * @returns files 已扫描到的文件数组、scanned/totalBytes/totalBytesHuman 进度、state 任务状态、
 *          loading 加载中标志、error 错误文案，以及 loadFiles（重新订阅）方法
 */
export function useFileScan(taskId: Ref<string>) {
  /** 目前累计收到的文件列表（可能有多批，每批 concat 进来），只读给模板用 */
  const files = ref<readonly FileEntry[]>([])
  /** 是否还在加载：订阅建立到收到 end/error 之间为 true */
  const loading = ref(true)
  /** 加载失败时的错误文案；null 表示没有错误 */
  const error = ref<string | null>(null)

  /** 扫描进度：已处理的文件个数（来自每个 chunk 的 scanned 字段） */
  const scanned = ref(0)
  /** 扫描进度：已扫描的总字节数，用于展示和后续格式化 */
  const totalBytes = ref(0)
  /** 扫描进度：后端已格式化好的总大小文案（如 "1.5 GB"），前端直接显示不再换算 */
  const totalBytesHuman = ref('0 B')
  /** 任务状态：pending（排队）/ running（进行中）/ done / cancelled / failed，初值 pending */
  const state = ref<ScanTaskInfo['status']>('pending')

  // EventSource 连接句柄；null 表示当前没有在订阅（未开始或已关闭）
  let es: EventSource | null = null

  /** 关闭当前的 SSE 连接并清空句柄；重复调用是安全的（已关闭时什么都不做） */
  const closeStream = () => {
    es?.close()
    es = null
  }

  /** 把后端推来的一个 chunk 合并进本地状态：追加新文件、覆盖进度数字、记录任务状态与错误 */
  const applyChunk = (chunk: ScanFileChunk) => {
    if (chunk.items.length > 0) {
      files.value = [...files.value, ...chunk.items]
    }
    scanned.value = chunk.scanned
    totalBytes.value = chunk.totalBytes
    totalBytesHuman.value = chunk.totalBytesHuman
    state.value = chunk.state
    if (chunk.error) error.value = chunk.error
  }

    /**
   * 清空旧状态并重新订阅该任务的文件流；taskId 为空字符串时直接结束加载（不发请求）。
   * 切换任务或点击刷新时调用它即可拿到最新列表。
   *
   * 后端 /scan/files/stream 对"进行中"和"已完成"的任务走的是同一套循环，区别只在于
   * 后端那边 task._files 是否还在增长：
   * - 进行中的任务：后端每 1s 检查一次 task._files 比上次多了多少，多出来的部分单独包一个
   *   'files' 事件推过来；本函数会收到很多次 'files' 事件，每次都把新文件 concat 进 files，
   *   直到任务跑完，后端才发 'end'（带上最终统计）并关流。
   * - 已完成的任务（包括重新打开历史记录、服务重启后从库里 files_json 还原的）：后端第一轮
   *   循环就发现状态已是终态，直接把全部文件当一个 'files' 事件整批发出，紧接着同一轮发 'end'。
   *   本函数这边感知不到区别——只是 'files' 只触发一次就立刻收到 'end'，整个过程几乎是瞬时的。
   */
  async function loadFiles(): Promise<void> {
    closeStream()
    files.value = []
    loading.value = true
    error.value = null

    if (!taskId.value) {
      loading.value = false
      return
    }

    es = new EventSource(scan_files_stream_url(taskId.value))

    // 进行中：这个事件会连续触发多次，每次只带"新增的"文件（增量）
    // 已完成：只触发一次，带着全部文件
    es.addEventListener('files', (event) => {
      applyChunk(JSON.parse((event as MessageEvent).data) as ScanFileChunk)
    })

    // 任务到达终态（done/cancelled/failed）后，无论之前是进行中还是一开始就已完成，
    // 都会收到这一条，随后后端主动关闭连接
    es.addEventListener('end', (event) => {
      applyChunk(JSON.parse((event as MessageEvent).data) as ScanFileChunk)
      loading.value = false
      closeStream()
    })

    /** 连接异常或后端提前断开：只有在还没拿到任何文件时才提示失败，并关闭连接避免自动重连 */
    es.onerror = () => {
      if (files.value.length === 0) error.value = '加载文件列表失败'
      loading.value = false
      closeStream()
    }
  }

  // 组件卸载时务必断开 SSE，否则连接会一直挂着（后端也会认为客户端还在）
  onUnmounted(() => {
    closeStream()
  })

  // 对外暴露：文件列表、进度数字、任务状态、加载与错误标志，以及重新订阅的方法
  return { files, scanned, totalBytes, totalBytesHuman, state, loading, error, loadFiles }
}
