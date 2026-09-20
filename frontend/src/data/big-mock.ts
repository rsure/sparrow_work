/**
 * 大数据集假数据（big-mock）
 * ========== 1000 条确定性生成的大数据集 ==========
 * 用于测试大列表渲染、排序、筛选等场景下的性能与正确性。
 * 全部数据用固定种子生成，因此每次运行结果完全一致，便于对比性能。
 */
import type { FileEntry, FileKind } from '@/services/file' // 只用类型：生成出来的每条记录必须满足 FileEntry 的结构

/** 每个文件大类对应的候选扩展名：生成文件名时按类别随机挑一个，保证 kind 与后缀自洽 */
const EXT_BY_KIND: Readonly<Record<FileKind, readonly string[]>> = {
  document: ['pdf', 'docx', 'txt', 'md'],
  image: ['png', 'jpg', 'webp', 'gif'],
  video: ['mp4', 'mkv', 'mov'],
  audio: ['mp3', 'wav', 'flac'],
  archive: ['zip', 'rar', '7z'],
  code: ['ts', 'js', 'py', 'vue', 'json'],
  other: ['bin', 'dat', 'log'],
}

/** 可生成的全部文件大类（有序），生成时从它里面等概率抽取 */
const KINDS: readonly FileKind[] = [
  'document',
  'image',
  'video',
  'audio',
  'archive',
  'code',
  'other',
]

/** 候选目录（Windows 绝对路径风格），用来拼出看起来真实的 path */
const DIRS = [
  'C:\\Users\\leade\\Documents',
  'C:\\Users\\leade\\Downloads',
  'C:\\Users\\leade\\Pictures',
  'C:\\Users\\leade\\Videos',
  'C:\\Users\\leade\\Music',
  'C:\\Users\\leade\\Desktop',
  'C:\\Users\\leade\\Projects\\frontend\\src',
  'C:\\Users\\leade\\Archive\\2025',
]

/** 文件名前缀词库（中英混合），与序号/扩展名拼成最终文件名 */
const NAME_PARTS = [
  '报告',
  '合同',
  '笔记',
  '截图',
  '素材',
  '备份',
  '方案',
  '周报',
  '录屏',
  '草稿',
  'draft',
  'summary',
  'export',
  'backup',
  'notes',
]

/** 固定种子的线性同余生成器，保证每次运行结果一致 */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * 生成 count 条假的文件记录，用于压测大列表的渲染与筛选排序。
 * 所有随机取值都来自固定种子，因此同参数多次调用结果完全一致。
 *
 * @param count 要生成多少条记录
 * @returns 只读的文件条目数组，可直接喂给列表组件
 */
function buildBigMock(count: number): readonly FileEntry[] {
  const rand = mulberry32(20261002) // 固定种子：保证每次运行（含 CI）数据都相同
  const pick = <T>(arr: readonly T[]): T => arr[Math.floor(rand() * arr.length)]! // 从数组里等概率取一个元素
  const seenPaths = new Set<string>() // 记录已用过的路径，保证 path 全局唯一
  const entries: FileEntry[] = []

  for (let i = 0; i < count; i++) {
    const kind = pick(KINDS)
    const ext = pick(EXT_BY_KIND[kind])
    const dir = pick(DIRS)
    const namePart = pick(NAME_PARTS)
    const isDirectory = rand() < 0.05 // 约 5% 的条目是文件夹
    const name = isDirectory ? `${namePart}_${i}` : `${namePart}_${i}.${ext}`
    let path = `${dir}\\${name}`
    // 撞名时追加一个随机数字后缀重试，直到路径唯一
    while (seenPaths.has(path)) {
      path = `${dir}\\${name}_${Math.floor(rand() * 100000)}`
    }
    seenPaths.add(path)

    const fileSize = isDirectory ? 0 : Math.floor(rand() * 500_000_000) + 512 // 文件夹恒为 0；文件 512B ~ 500MB
    const daysAgo = Math.floor(rand() * 365) // 修改时间落在最近一年内
    const modifiedAt = new Date(Date.UTC(2026, 9, 1) - daysAgo * 86_400_000).toISOString()

    entries.push({
      path,
      name,
      fileSize,
      kind,
      isDirectory,
      modifiedAt,
      indexed: rand() < 0.7, // 约 70% 标记为「已入库」，方便测两种状态的展示
    })
  }

  return entries
}

/** 应用里共用的大数据集实例：模块加载时生成 2000 条并冻结类型（只读数组） */
export const BIG_MOCK: readonly FileEntry[] = buildBigMock(2000)
