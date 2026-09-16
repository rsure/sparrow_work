/**
 * 自动更新（OPS-4）的共享类型：主进程、preload、渲染进程三处都要用同一份形状。
 *
 * 为什么单独一个文件：
 *   主进程（updater.ts）产生状态，preload 通过 IPC 转给页面，页面（AboutView）负责展示。
 *   这三处如果各自手写一遍类型，改一个字段就要三处一起改，很容易漏。
 */

/** 自动更新当前处于哪个阶段 */
export type UpdateStatus =
  /** 还没检查过 */
  | 'idle'
  /** 当前环境不支持自动更新（开发态，或没打包） */
  | 'disabled'
  /** 正在检查（请求已发出，还没结果） */
  | 'checking'
  /** 有新版本，等待用户决定是否下载 */
  | 'available'
  /** 正在下载新版本 */
  | 'downloading'
  /** 下载完成，重启即可安装 */
  | 'downloaded'
  /** 已是最新版本 */
  | 'not-available'
  /** 检查或下载失败 */
  | 'error'

/**
 * 一次更新动作的状态快照，通过 IPC 在三个进程间传递。
 * 全部字段都是可序列化的简单类型（IPC 只认结构化克隆，不能传 Error 之类的对象）。
 */
export interface UpdateState {
  /** 当前阶段 */
  status: UpdateStatus
  /** 新版本号（status 为 available/downloading/downloaded 时有值），其余为 null */
  version: string | null
  /** 下载进度百分比（0~100，仅 downloading 时有意义），其余为 0 */
  percent: number
  /** 面向用户的一句话说明（失败原因 / 已是最新 / 开发态提示等），可为空串 */
  message: string
  /** 最近一次检查完成的时间（ISO 8601），从未检查过时为 null */
  checked_at: string | null
}
