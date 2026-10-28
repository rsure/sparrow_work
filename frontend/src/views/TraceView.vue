<!--
  views/TraceView.vue —— 执行轨迹回放（ARCH-7 的前端部分）。
  为什么单独一页而不是塞进对话页：
    轨迹是给"排查为什么这么答"用的，一次要横向看好几步（工具调用 → 结果 → 再调用），
    塞进气泡里只能竖着滚很久；独立页面可以用"会话 / 轮次 / 事件"三级钻取。
  数据全部只读，来自 GET /api/trace/sessions*，不动对话状态。
-->
<script setup lang="ts">
/**
 * TraceView —— 选会话 → 选轮次 → 看这一轮每一步都做了什么。
 *
 * 三级钻取的顺序是固定的：会话（一次对话） → 轮次（一问一答） → 事件（每次工具调用/模型调用）。
 * 事件不预加载：一轮可能有几百条，只有真的点开才查。
 */
// Vue：ref 存三级选择与加载状态（没有派生状态，所以不需要 computed）
import { ref } from 'vue'
// Vant：加载失败与"轨迹开关关闭"的提示
import { showToast } from 'vant'
// 轨迹接口：会话列表 / 轮次列表 / 某轮事件
import { fetch_trace_events, list_trace_sessions, list_trace_turns } from '@/services/trace'
// 轨迹数据类型：三个接口的返回行
import type { TraceEventRow, TraceSessionRow, TraceTurnRow } from '@/services/trace'

/** 会话清单（按最后事件时间倒序） */
const sessions = ref<TraceSessionRow[]>([])
/** 当前选中会话的轮次清单 */
const turns = ref<TraceTurnRow[]>([])
/** 当前展示的事件清单 */
const events = ref<TraceEventRow[]>([])
/** 当前选中的会话 id；空串表示还没选 */
const selectedSession = ref('')
/** 当前选中的轮次 id；空串表示"这一会话的全部轮次" */
const selectedTurn = ref('')
/** 是否正在加载会话清单 */
const loadingSessions = ref(false)
/** 是否正在加载轮次/事件 */
const loadingDetail = ref(false)
/** 已展开 payload 的事件 id 集合（折叠是默认，payload 可能很长） */
const expanded = ref<number[]>([])

/**
 * 事件类型 → 中文标签。
 * 后端 kinds 目前是 turn_start / tool_call / tool_result / done / memory /
 * task_start / task_end / plan / budget / confirm / error / steer；
 * 未知类型原样显示，便于发现后端新增却没同步前端的情况。
 *
 * @param kind 事件类型
 */
function kindLabel(kind: string): string {
  const table: Record<string, string> = {
    turn_start: '开始',
    tool_call: '调用工具',
    tool_result: '工具返回',
    done: '回答完成',
    memory: '记忆',
    task_start: '子任务开始',
    task_end: '子任务结束',
    plan: '任务计划',
    budget: '预算',
    confirm: '等待确认',
    error: '错误',
    steer: '用户插话',
  }
  return table[kind] ?? kind
}

/**
 * 事件类型的配色分类：失败/等待为人注意的一类，工具与模型各自一类，其余中性。
 *
 * @param kind 事件类型
 */
function kindClass(kind: string): string {
  if (kind === 'error') return 'trace__kind--danger'
  // 插话与预算/确认同色：都是"用户在过程中介入了"
  if (kind === 'confirm' || kind === 'budget' || kind === 'steer') return 'trace__kind--warn'
  if (kind === 'tool_call' || kind === 'tool_result') return 'trace__kind--tool'
  return ''
}

/**
 * 把后端返回的 ISO 时间转成本地「MM-DD HH:mm:ss」。
 *
 * @param iso UTC 时间字符串（可能不带时区后缀）
 * @returns 简短时间文案；空值返回空串
 */
function shortTime(iso: string | null): string {
  if (!iso) return ''
  const normalized = /Z|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`
}

/**
 * payload 转成可读 JSON。
 *
 * 后端已经把过长的字符串截断到 2000 字符，这里只负责缩进；
 * 序列化失败时退回 String()，绝不因为一条脏数据把整页搞崩。
 *
 * @param payload 任意结构化内容
 */
function prettyPayload(payload: unknown): string {
  if (payload === null || payload === undefined) return '（无内容）'
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
}

/** 展开 / 收起一条事件的 payload 详情 */
function togglePayload(id: number): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

/**
 * 拉取会话清单。
 * 失败时只提示，不清空已有数据——用户可能只是网络抖了一下。
 */
async function loadSessions(): Promise<void> {
  loadingSessions.value = true
  try {
    // 会话条数交给后端契约表（默认 50、上限 200），这里不传 limit
    sessions.value = await list_trace_sessions()
  } catch (error) {
    console.error('加载轨迹会话失败:', error)
    showToast('加载轨迹失败，请确认诊断里的轨迹开关已打开')
  } finally {
    loadingSessions.value = false
  }
}

/**
 * 拉取某一轮的事件；turnId 为空表示这一会话的全部轮次。
 *
 * @param sessionId 会话 id
 * @param turnId 轮次 id（空串=全部）
 */
async function loadEvents(sessionId: string, turnId: string): Promise<void> {
  loadingDetail.value = true
  try {
    // 事件条数交给后端契约表（默认 500、上限 5000），这里不传 limit
    events.value = await fetch_trace_events(sessionId, turnId || undefined)
    // 换了一批事件，之前的展开状态就没意义了
    expanded.value = []
  } catch (error) {
    console.error('加载轨迹事件失败:', error)
    events.value = []
    showToast('加载轨迹事件失败')
  } finally {
    loadingDetail.value = false
  }
}

/**
 * 选中一个会话：拉它的轮次，并默认展示全部轮次的事件。
 *
 * @param sessionId 会话 id
 */
async function selectSession(sessionId: string): Promise<void> {
  selectedSession.value = sessionId
  selectedTurn.value = ''
  turns.value = []
  loadingDetail.value = true
  try {
    // 轮次条数交给后端契约表（默认 50、上限 200），这里不传 limit
    turns.value = await list_trace_turns(sessionId)
  } catch (error) {
    console.error('加载轮次失败:', error)
    showToast('加载轮次失败')
  }
  await loadEvents(sessionId, '')
}

/**
 * 选中一个轮次（或"全部轮次"）并刷新事件。
 *
 * @param turnId 轮次 id；空串表示全部轮次
 */
async function selectTurn(turnId: string): Promise<void> {
  if (!selectedSession.value) return
  selectedTurn.value = turnId
  await loadEvents(selectedSession.value, turnId)
}

// 进页面就拉会话清单：这一页没有别的入口，不自动加载的话用户会看到一片空白
void loadSessions()
</script>

<template>
  <div class="trace">
    <header class="trace__head">
      <div>
        <h1 class="trace__title">执行轨迹</h1>
        <p class="trace__sub">只读回放：选会话 → 选轮次 → 看每一步的工具调用与耗时</p>
      </div>
      <button type="button" class="trace__btn" :disabled="loadingSessions" @click="loadSessions">
        刷新
      </button>
    </header>

    <div class="trace__body">
      <!-- 第一级：会话 -->
      <aside class="trace__sessions">
        <p v-if="loadingSessions" class="trace__empty">加载中…</p>
        <p v-else-if="sessions.length === 0" class="trace__empty">
          还没有轨迹记录（诊断页里打开「记录执行轨迹」后才会产生）
        </p>
        <button
          v-for="row in sessions"
          :key="row.session_id"
          type="button"
          class="trace__session"
          :class="{ 'trace__session--active': row.session_id === selectedSession }"
          @click="selectSession(row.session_id)"
        >
          <span class="trace__session-title">{{ row.title || row.session_id.slice(0, 8) }}</span>
          <span class="trace__session-meta">
            {{ row.turn_count }} 轮 · {{ row.event_count }} 事件 · {{ shortTime(row.last_at) }}
          </span>
        </button>
      </aside>

      <!-- 第二、三级：轮次 + 事件 -->
      <section class="trace__main">
        <p v-if="!selectedSession" class="trace__empty">左侧选一个会话开始查看</p>
        <template v-else>
          <div class="trace__turns">
            <button
              type="button"
              class="trace__turn"
              :class="{ 'trace__turn--active': selectedTurn === '' }"
              @click="selectTurn('')"
            >
              全部轮次
            </button>
            <button
              v-for="turn in turns"
              :key="turn.turn_id"
              type="button"
              class="trace__turn"
              :class="{ 'trace__turn--active': turn.turn_id === selectedTurn }"
              @click="selectTurn(turn.turn_id)"
            >
              {{ turn.turn_id.slice(0, 8) }} · {{ turn.mode }} · {{ turn.event_count }} 条 ·
              {{ shortTime(turn.last_at) }}
            </button>
          </div>

          <p v-if="loadingDetail" class="trace__empty">加载中…</p>
          <p v-else-if="events.length === 0" class="trace__empty">这一个范围内没有事件</p>
          <ol v-else class="trace__events">
            <li v-for="event in events" :key="event.id" class="trace__event">
              <div class="trace__event-head">
                <span class="trace__kind" :class="kindClass(event.kind)">{{ kindLabel(event.kind) }}</span>
                <span class="trace__seq">#{{ event.seq }}</span>
                <span v-if="event.name" class="trace__name">{{ event.name }}</span>
                <span v-if="event.duration_ms" class="trace__dur">{{ event.duration_ms }} ms</span>
                <span class="trace__time">{{ shortTime(event.created_at) }}</span>
                <button
                  v-if="event.payload"
                  type="button"
                  class="trace__toggle"
                  @click="togglePayload(event.id)"
                >
                  {{ expanded.includes(event.id) ? '收起' : '详情' }}
                </button>
              </div>
              <pre v-if="event.payload && expanded.includes(event.id)" class="trace__payload">{{
                prettyPayload(event.payload)
              }}</pre>
            </li>
          </ol>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.trace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 16px 20px;
  gap: 12px;
}

.trace__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.trace__title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
}

.trace__sub {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

.trace__btn {
  appearance: none;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
}

.trace__btn:hover:not(:disabled) {
  color: var(--color-text);
}

.trace__body {
  display: flex;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

.trace__sessions {
  flex: 0 0 220px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  min-height: 0;
  border-right: 1px solid var(--color-border);
  padding-right: 8px;
}

.trace__session {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.trace__session:hover {
  background: var(--color-surface-2);
}

.trace__session--active {
  background: var(--color-primary-weak);
}

.trace__session-title {
  font-size: 12px;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace__session-meta {
  font-size: 10px;
  color: var(--color-text-muted);
}

.trace__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  min-height: 0;
}

.trace__turns {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.trace__turn {
  padding: 3px 10px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 11px;
  cursor: pointer;
}

.trace__turn--active {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.trace__events {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.trace__event {
  border: 1px solid var(--color-border);
  border-radius: 9px;
  padding: 6px 9px;
  background: var(--color-surface);
}

.trace__event-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.trace__kind {
  flex: none;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-size: 10px;
}

.trace__kind--tool {
  background: var(--color-primary-weak);
  color: var(--color-primary);
}

.trace__kind--warn {
  color: #b08900;
}

.trace__kind--danger {
  color: var(--color-danger);
}

.trace__seq {
  flex: none;
  color: var(--color-text-muted);
  font-family: var(--font-mono, ui-monospace, monospace);
}

.trace__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text);
}

.trace__dur {
  flex: none;
  color: var(--color-text-muted);
}

.trace__time {
  flex: none;
  margin-left: auto;
  color: var(--color-text-muted);
}

.trace__toggle {
  flex: none;
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: 11px;
  cursor: pointer;
}

.trace__payload {
  margin: 6px 0 0;
  padding: 8px;
  border-radius: 7px;
  background: var(--color-surface-2);
  color: var(--color-text);
  font-size: 11px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow-y: auto;
}

.trace__empty {
  margin: 0;
  padding: 10px 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
