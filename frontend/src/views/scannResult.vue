<script setup lang="ts">
/**
 * 扫描结果页：展示某次扫描任务实时推送来的文件列表，支持筛选、排序、分批展示与勾选导入。
 * 数据链路：useFileScan 订阅 /scan/files/stream（SSE）把文件累积进 files，
 * useFileFilter 负责关键词/类别筛选与排序，本页只负责分页展示与交互。
 */
import { computed, onMounted, ref, watch } from 'vue' // 响应式与生命周期：computed 派生展示值，ref 存本地状态，onMounted 首屏加载，watch 跟随任务切换
import { useRoute } from 'vue-router' // 只读当前路由 query：task_id / path 决定要展示哪一次扫描的结果
import { showToast } from 'vant' // 轻提示方法：导入结果、打开文件夹失败等即时反馈
import StatCard from '@/components/StatCard.vue' // 顶部统计卡片：已扫描 / 匹配文件 / 合计大小 / 已选中
import SearchBar from '@/components/SearchBar.vue' // 搜索筛选栏：关键词 + 类别 + 排序，双向绑定到 useFileFilter 的状态
import FileList from '@/components/FileList.vue' // 文件列表组件：渲染条目并把勾选、打开等操作以事件抛回来
import { useFileFilter } from '@/composables/useFileFilter' // 组合式函数：把 files 过滤 + 排序成 visible，并累计总大小
import { useFileScan } from '@/composables/useFileScan' // 组合式函数：按 task_id 订阅 SSE，产出 files / 进度 / 状态 / 错误
import type { FileEntry } from '@/services/file' // 文件条目类型：本页事件回调的入参类型
import { upload_file } from '@/services/scan' // 导入接口：把选中的文档提交给后端做切片 + 向量化

/** 路由实例：本页只读取 query，不做跳转 */
const route = useRoute()
/** 要展示的任务 id（日志页跳转时通过 query 传进来）；为空表示还没选任务，此时不会订阅任何流 */
const taskId = computed(() => (route.query.task_id as string | undefined) ?? '')
/** 本次扫描的源文件夹绝对路径，仅用于顶部「来源任务」提示条展示 */
const path = computed(() => (route.query.path as string | undefined) ?? '')

// 订阅扫描任务的文件流：files=累积到的文件，scanned/totalBytesHuman=进度展示值，state=任务状态，loadFiles=发起订阅
const { files, scanned, totalBytesHuman, state, loading, error, loadFiles } = useFileScan(taskId)
/** 已勾选的文件路径集合：Set 天然去重，作为 FileList 的选中态依据（父组件持有） */
const selectedPaths = ref<ReadonlySet<string>>(new Set())
// 筛选与排序：keyword=关键词，kind=类别，sortField/sortOrder=排序，visible=过滤后结果，totalSize=合计字节数
const { keyword, kind, sortField, sortOrder, visible, totalSize, reset } = useFileFilter(files, {
  includeDirectories: false, // 结果页不展示文件夹，筛选阶段就排除
})
/** 合计大小文案：不足 1GB 用 MB（1 位小数），达到 1GB 以上用 GB（2 位小数），避免出现超长数字 */
const totalSizeText = computed(() =>
    totalSize.value < 1024 ** 3
        ? `${(totalSize.value / 1024 ** 2).toFixed(1)} MB`
        : `${(totalSize.value / 1024 ** 3).toFixed(2)} GB`,
)
/** 扫描是否仍在进行（排队中/扫描中）：决定「已扫描」卡片是否用告警色并显示「扫描中…」 */
const isScanning = computed(() => state.value === 'pending' || state.value === 'running')

// 下拉加载更多：文件已经通过 SSE 全部累积进 files，这里只是分批把 visible 露出来
/** 当前已展示的条数（每下拉一次 +10）；数据其实早在内存里，只是控制渲染量 */
const displayCount = ref(10)
/** van-list 的加载中标记：本页是本地切片，触发后立刻置回 false 结束动画 */
const listLoading = ref(false)
/** 是否已展示完全部匹配结果：true 时列表底部显示「没有更多了」 */
const listFinished = computed(() => displayCount.value >= visible.value.length)
/** 真正交给列表渲染的那段切片；分页只影响展示，不影响筛选/排序结果 */
const pagedFiles = computed(() => visible.value.slice(0, displayCount.value))
/** van-list 滚动到底部时触发：多放 10 条出来，并结束本次加载动画 */
function onLoadMore(): void {
  displayCount.value += 10
  listLoading.value = false
}

/** 首次挂载就开始加载：订阅该任务的 SSE 并把已扫到的文件补进来 */
onMounted(() => {
  void loadFiles()
})
/** 任务切换（query 里的 task_id 变化）时重置分页并重新订阅新任务的文件流 */
watch(taskId, () => {
  displayCount.value = 10
  void loadFiles()
})
/**
 * 勾选 / 取消勾选单个文件：整体替换 Set 实例，保证 Vue 能检测到变化。
 * @param path 被点击文件的绝对路径
 */
function toggleOne(path: string): void {
  const next = new Set(selectedPaths.value) // 换新实例，语义更清晰
  if (next.has(path)) next.delete(path)
  else next.add(path)
  selectedPaths.value = next
}

/**
 * 将扫描到的文档文件导入 RAG 索引（切片 + 向量化），成功后给出提示。
 * 文件夹与非文档类型直接拒绝，不发起请求。
 * @param entry 被点击「导入」的那条文件记录
 */
async function uploadFile(entry: FileEntry): Promise<void> {

  if (entry.isDirectory) {
    showToast(`无法导入文件夹`)
  } else if(entry.kind !== 'document') {
    showToast(`暂不支持导入文档之外的文件类型`)
  } else {
    try {
      await upload_file(entry.path);
      showToast(`导入成功：${entry.name}`)
    } catch (error) {
      console.error('导入失败:', error)
      showToast('导入失败')
    }
  }
}

/**
 * 在系统文件管理器中定位该条目：目录直接打开，文件则高亮所在位置。
 * 仅桌面端可用（浏览器里 window.desktop 不存在）。
 * @param entry 被点击「打开所在文件夹」的那条文件记录
 */
async function openInFolder(entry: FileEntry): Promise<void> {
  if (!window.desktop) {
    showToast('当前环境不支持打开文件夹（仅桌面端可用）')
    return
  }
  try {
    if (entry.isDirectory) {
      const err = await window.desktop.openPath(entry.path)
      if (err) showToast(`打开失败：${err}`)
    } else {
      await window.desktop.showItemInFolder(entry.path)
    }
  } catch (error) {
    console.error('打开文件夹失败:', error)
    showToast('打开失败')
  }
}
</script>


<template>
  <!-- position/transform 让内部 van-dropdown-item(position: fixed) 的定位上下文收敛在本容器内，
       而不是整个 viewport，避免下拉面板横向撑满页面、超出外层卡片边界 -->
  <div class="scan-result">
    <van-notice-bar v-if="taskId" left-icon="info-o" class="task-id-hint">
      来源任务：{{ path }}
    </van-notice-bar>

    <SearchBar
        v-model:keyword="keyword"
        v-model:kind="kind"
        v-model:sort-field="sortField"
        v-model:sort-order="sortOrder"
        :match-count="visible.length"
        @reset="reset"
    />

    <div class="stat-row">
      <StatCard
          label="已扫描"
          :value="`${scanned} 个 · ${totalBytesHuman}`"
          :tone="isScanning ? 'warn' : 'default'"
          :hint="isScanning ? '扫描中…' : undefined"
      />
      <StatCard label="匹配文件" :value="String(visible.length)" />
      <StatCard label="合计大小" :value="totalSizeText" tone="primary" />
      <StatCard label="已选中" :value="String(selectedPaths.size)" />
    </div>

    <van-empty v-if="error" image="error" :description="error" />
    <van-list
        v-else
        v-model:loading="listLoading"
        :finished="listFinished"
        finished-text="没有更多了"
        @load="onLoadMore"
    >
      <FileList
          :files="pagedFiles"
          :selected="selectedPaths"
          :loading="loading && files.length === 0"
          @toggle="toggleOne"
          @open-folder="openInFolder"
          @open="uploadFile"
          @select-all="selectedPaths = new Set(visible.map((f) => f.path))"
          @clear-selection="selectedPaths = new Set()"
      />
    </van-list>
  </div>
</template>

<style scoped>
.scan-result {
  position: relative;
  /* 为内部 fixed 定位的下拉面板建立新的包含块 */
  transform: translateZ(0);
}

.task-id-hint {
  margin: 0 0 12px;
  border-radius: 8px;
}

.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0;
}

.stat-row :deep(.stat-card) {
  flex: 1 1 calc(50% - 6px);
  min-width: 120px;
}
</style>