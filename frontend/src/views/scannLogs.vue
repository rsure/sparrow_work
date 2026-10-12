<script setup lang="ts">
/**
 * 扫描日志页：选择文件夹 → 发起扫描 → 展示任务列表并实时刷新进度。
 * 数据来源：GET /scan/pages 拿任务列表，EventSource 订阅 /scan/stream 拿进度。
 */
import {scan_logs, scan_start, scan_stream_url, type ScanTaskInfo, type ScanProgress} from "@/services/scan"; // 扫描接口层：查任务列表、发起扫描、拼 SSE 地址，另含两个返回体类型
import {onActivated, onMounted, onUnmounted, ref} from "vue"; // 响应式与生命周期：ref 存状态，onMounted 首次加载，onActivated 配合 KeepAlive，onUnmounted 关流
import {useRouter} from "vue-router"; // 编程式导航：发起扫描或点击任务行后跳到扫描结果页

import { showToast } from 'vant'; // 轻提示方法：选择文件夹、加载失败等场景给用户即时反馈

/** 路由实例：用于 push 到扫描结果页 */
const router = useRouter();

/** 用户选中的待扫描文件夹绝对路径；输入框只读，只能由原生选择框写入 */
const folderPath = ref('');

/**
 * 点击「选择文件夹」：调用 Electron 原生目录选择框，把返回的绝对路径写进 folderPath。
 * 仅桌面端可用（浏览器里 window.desktop 不存在），用户取消时什么都不做。
 */
const handleSelectFolder = async () => {
  if (!window.desktop) {
    showToast('当前环境不支持选择文件夹（仅桌面端可用）');
    return;
  }
  try {
    // 调用 Electron 原生对话框，直接拿到完整绝对路径
    const fullPath = await window.desktop.selectFolder();

    if (fullPath) {
      folderPath.value = fullPath; // 例如 "C:\Users\Name\Documents"
      showToast('文件夹已选择');
    }
    // 如果为 null，说明用户取消了选择，不需要处理
  } catch (error) {
    console.error('选择文件夹失败:', error);
    showToast('选择文件夹失败');
  }
};

/** 点击「扫描」：把当前路径提交给后端创建任务，成功后立刻跳到扫描结果页订阅这次任务 */
const handleChoosePath = async ()=>{
  showToast('已加入扫描队列');
  const taskId = await scan_start(folderPath.value);
  router.push({ name: 'scannResult', query: { task_id: taskId, path: folderPath.value } });
}

/** 任务列表数据：一页扫描任务；SSE 进度会原地更新其中对应的行 */
const tasks = ref<ScanTaskInfo[]>([]);
/** 是否正在加载任务列表：true 时列表区域显示加载动画 */
const loading = ref(false);

/**
 * 任务状态 → 展示样式映射。
 * text=中文状态文案（悬停提示/无障碍），color=状态图标颜色（十六进制），icon=Vant 图标名。
 */
const STATUS_MAP: Record<ScanTaskInfo['status'], { text: string; color: string; icon: string }> = {
  pending: { text: '等待中', color: '#969799', icon: 'clock-o' },
  running: { text: '扫描中', color: '#1989fa', icon: 'underway-o' },
  done: { text: '已完成', color: '#07c160', icon: 'passed' },
  cancelled: { text: '已取消', color: '#ff976a', icon: 'revoke' },
  failed: { text: '失败', color: '#ee0a24', icon: 'close' },
};

// 正在扫描中的任务：task_id -> EventSource，页面卸载/任务结束时需关闭
const activeStreams = new Map<string, EventSource>();

/**
 * 关闭某个任务的事件流并把它从登记表里移除，避免任务结束后连接一直空挂。
 * @param taskId 要关闭的任务 id
 */
const closeStream = (taskId: string) => {
  const es = activeStreams.get(taskId);
  if (es) {
    es.close();
    activeStreams.delete(taskId);
  }
};

/** 关闭全部事件流：页面卸载时调用，防止组件销毁后仍持续请求、造成内存泄漏 */
const closeAllStreams = () => {
  activeStreams.forEach((es) => es.close());
  activeStreams.clear();
};

/**
 * 用进度快照原地更新任务列表中的对应行，避免整页刷新导致滚动位置丢失。
 * @param prog 后端推来的进度事件数据，按其中的 task_id 定位要更新的那一行
 */
const applyProgress = (prog: ScanProgress) => {
  const task = tasks.value.find((t) => t.task_id === prog.task_id);
  if (!task) return;
  task.status = prog.state;
  task.scanned = prog.scanned;
  task.total_bytes = prog.total_bytes;
  task.total_bytes_human = prog.total_bytes_human;
  task.skipped = prog.skipped;
  task.elapsed = prog.elapsed;
  task.error = prog.error;
};

/**
 * 为单个任务订阅 SSE 进度：progress 事件更新该行数据，end 事件更新后关闭流，出错也主动关闭以免无限重连。
 * 已在订阅中的任务直接返回，避免重复建连。
 * @param taskId 要订阅的任务 id
 */
const watchTask = (taskId: string) => {
  if (activeStreams.has(taskId)) return;

  const es = new EventSource(scan_stream_url(taskId));
  activeStreams.set(taskId, es);

  es.addEventListener('progress', (event) => {
    const prog = JSON.parse((event as MessageEvent).data) as ScanProgress;
    applyProgress(prog);
  });

  es.addEventListener('end', (event) => {
    const prog = JSON.parse((event as MessageEvent).data) as ScanProgress;
    applyProgress(prog);
    closeStream(taskId);
  });

  es.onerror = () => {
    closeStream(taskId);
  };
};

/** 遍历当前列表，为所有「等待中/扫描中」的任务补上 SSE 订阅；已结束的任务无需订阅 */
const watchRunningTasks = () => {
  for (const task of tasks.value) {
    if (task.status === 'pending' || task.status === 'running') {
      watchTask(task.task_id);
    }
  }
};

/** 拉取第一页扫描任务并渲染；拿到数据后立刻为进行中的任务订阅实时进度 */
const loadTasks = async () => {
  loading.value = true;
  try {
    const page = await scan_logs();
    tasks.value = page.items;
    watchRunningTasks();
  } catch (error) {
    console.error('加载任务列表失败:', error);
    showToast('加载任务列表失败');
  } finally {
    loading.value = false;
  }
}

// 刷新按钮防抖：1 秒内重复点击直接忽略
let refreshLocked = false;
/** 点击刷新图标：1 秒内只允许触发一次 loadTasks，避免连点把后端打爆 */
const handleRefresh = async () => {
  if (refreshLocked) return;
  refreshLocked = true;
  setTimeout(() => { refreshLocked = false; }, 1000);
  await loadTasks();
};

/**
 * 点击某一行任务：跳到扫描结果页，并用 query 把 task_id / path 传过去。
 * @param task 被点击的那条任务记录
 */
const goDetail = (task: ScanTaskInfo) => {
  router.push({ name: 'scannResult', query: { task_id: task.task_id, path: task.path } });
};

/** 首次挂载加载一次任务列表；之后依赖 KeepAlive 保留数据，再次激活不重新请求 */
onMounted(async ()=>{
  if (tasks.value.length === 0) {
    await loadTasks();
  }
})

/** KeepAlive 缓存页再次激活时触发：数据仍在内存里，这里刻意不重新请求，只保留 SSE 的实时性 */
onActivated(() => {
  // 从扫描结果页切回来时数据仍在，无需重新加载
});

/** 页面卸载时统一关闭所有 SSE 连接（含进行中的唯一一次请求），防止回调写到已销毁的组件上 */
onUnmounted(() => {
  closeAllStreams();
});
</script>
<template>
  <!-- 路径显示文本框 -->
  <div class="scan-panel">
    <!-- 路径显示框：保留 readonly，因为路径由选择器决定 -->
    <van-field
        v-model="folderPath"
        label="文件夹路径"
        placeholder="点击右侧按钮选择文件夹"
        readonly
    >
      <template #button>
        <div class="scan-panel__actions">
          <!-- 按钮文案改为「选择文件夹」或「确认」都可以 -->
          <van-button size="small" type="primary" @click="handleSelectFolder">
            选择文件夹
          </van-button>
          <!-- 按钮文案改为「选择文件夹」或「确认」都可以 -->
          <van-button size="small" type="primary" @click="handleChoosePath">
            扫描
          </van-button>
        </div>
      </template>
    </van-field>
  </div>

  <div class="task-toolbar">
    <span class="task-toolbar__title">任务列表</span>
    <van-icon name="replay" class="task-toolbar__refresh" @click="handleRefresh" />
  </div>

  <van-loading v-if="loading" class="task-loading" vertical>加载中...</van-loading>
  <van-empty v-else-if="tasks.length === 0" description="暂无扫描任务" />
  <van-cell-group v-else inset class="task-list">
    <van-cell
        v-for="task in tasks"
        :key="task.task_id"
        :title="task.path"
        :label="`扫描 ${task.scanned} 个文件 · ${task.total_bytes_human} · 耗时 ${task.elapsed.toFixed(1)}s`"
        :title-style="{ 'word-break': 'break-all' }"
        center
        clickable
        @click="goDetail(task)"
    >
      <template #icon>
        <van-icon
            :name="STATUS_MAP[task.status].icon"
            :color="STATUS_MAP[task.status].color"
            :title="STATUS_MAP[task.status].text"
            class="task-cell__status-icon"
        />
      </template>
      <template #right-icon>
        <van-icon name="arrow" class="task-cell__detail-icon" />
      </template>
    </van-cell>
  </van-cell-group>
</template>

<style scoped>
.scan-panel {
  padding: 16px;
}

.scan-panel__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px 8px;
}

.task-toolbar__title {
  font-size: 14px;
  color: var(--color-text-muted, #646566);
}

.task-toolbar__refresh {
  font-size: 18px;
  color: var(--color-primary, #1989fa);
  cursor: pointer;
  padding: 4px;
}

.task-toolbar__refresh:active {
  opacity: 0.6;
}

.task-loading {
  padding: 32px 0;
  justify-content: center;
}

.task-list {
  margin-bottom: 16px;
}

.task-cell__status-icon {
  font-size: 18px;
  margin-right: 4px;
}

.task-cell__detail-icon {
  font-size: 16px;
  color: var(--color-text-muted, #969799);
}
</style>
