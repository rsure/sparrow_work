/**
 * services/command.ts 的单元测试 —— 斜杠命令的三个纯函数。
 *
 * 为什么要测：这三个函数决定了「输入框敲 `/` 之后弹什么、Enter 之后执行什么」。
 * 它们不碰网络、不碰 DOM，是这条链路上唯一可以精确断言的部分；
 * 一旦 parse 的边界（多空格、首尾空格、只有斜杠）判断错了，
 * 用户会看到面板该收的时候不收、或者参数被吞掉，而控制台里一句报错都没有。
 */
// Vitest：describe 分组、it 单个用例、expect 断言
import { describe, expect, it } from 'vitest'
// 被测函数：解析输入、按关键词筛选、来源标签；CommandInfo 用于构造测试数据
import {
  command_source_label,
  filter_commands,
  parse_slash_input,
  type CommandInfo,
} from '@/services/command'

/**
 * 造一条命令，只写用例关心的字段。
 *
 * @param name 命令名（不含斜杠）
 * @param description 说明文案，用于验证「说明里包含关键词」这一档排序
 * @param source 来源：builtin / skill
 * @returns 字段齐全的 CommandInfo
 */
function makeCommand(
  name: string,
  description = '',
  source = 'builtin',
): CommandInfo {
  return {
    name,
    description,
    // 参数提示在纯函数里不参与判断，给空串即可
    args_hint: '',
    source,
    // 动作同理：filter/parse 都不看它
    action: source === 'builtin' ? name : '',
  }
}

describe('parse_slash_input：从输入框文本解析命令名与参数', () => {
  it('不以斜杠开头时解析为空（普通提问不弹命令面板）', () => {
    expect(parse_slash_input('帮我看看这个文件')).toEqual({ name: '', args: '' })
    // 斜杠出现在中间也不算命令
    expect(parse_slash_input('路径是 a/b')).toEqual({ name: '', args: '' })
  })

  it('只敲了一个斜杠时名字为空（面板要弹出但不过滤）', () => {
    expect(parse_slash_input('/')).toEqual({ name: '', args: '' })
    // 斜杠后面只有空格，同样视为「还没敲名字」
    expect(parse_slash_input('/   ')).toEqual({ name: '', args: '' })
  })

  it('没有空格时整个斜杠后内容都是命令名', () => {
    expect(parse_slash_input('/mo')).toEqual({ name: 'mo', args: '' })
    // 用户可能先敲了空格再敲斜杠，前导空白要忽略
    expect(parse_slash_input('   /model')).toEqual({ name: 'model', args: '' })
  })

  it('出现空格后切分成命令名与参数，参数保留内部空格', () => {
    expect(parse_slash_input('/model gpt-4o')).toEqual({ name: 'model', args: 'gpt-4o' })
    // 多个连续空格不该让 args 多出前导空白
    expect(parse_slash_input('/doc   -l')).toEqual({ name: 'doc', args: '-l' })
    // 参数本身可以再带空格（技能命令的参数是原样传给后端的）
    expect(parse_slash_input('/summarize 这篇文章 的重点')).toEqual({
      name: 'summarize',
      args: '这篇文章 的重点',
    })
  })
})

describe('filter_commands：按关键词给命令排序', () => {
  // 四条用例数据：前三条专门覆盖三档命中（名字前缀 / 名字包含 / 仅说明包含），第四条从不命中
  const commands: CommandInfo[] = [
    makeCommand('model', '切换当前模型'),
    makeCommand('export', '导出当前会话'),
    makeCommand('help', '说明里写着 export 怎么用'),
    makeCommand('trace', '执行轨迹回放'),
  ]

  it('关键词为空时返回全部，并且是新数组（调用方改动不会污染原清单）', () => {
    const result = filter_commands(commands, '   ')

    expect(result).toHaveLength(4)
    // 只做副本，不共享引用：store 里拿到结果后可以放心再排序/截断
    expect(result).not.toBe(commands)
  })

  it('三档排序：名字前缀 → 名字包含 → 仅说明包含', () => {
    const result = filter_commands(commands, 'exp')

    // "export" 以 exp 开头（第 0 档）；"help" 只在说明里出现 exp（第 2 档）；model/trace 没命中
    expect(result.map((item) => item.name)).toEqual(['export', 'help'])
  })

  it('名字包含但非前缀时，排在前缀命中之后', () => {
    // "port" 不是任何命令的前缀，但出现在 export 名字里面；
    // help 的说明里同样有 "export"，所以它降级到第 2 档排在后面
    const result = filter_commands(commands, 'port')

    expect(result.map((item) => item.name)).toEqual(['export', 'help'])
  })

  it('大小写不敏感，且完全没命中时返回空数组', () => {
    // 命令名是小写的 export，输入大写也要能筛到
    expect(filter_commands(commands, 'EXPORT').map((item) => item.name)).toEqual([
      'export',
      'help',
    ])
    // 没命中就该空数组：面板据此显示"没有匹配的命令"
    expect(filter_commands(commands, 'zzz')).toEqual([])
  })
})

describe('command_source_label：来源标签', () => {
  it('内置与技能翻译成中文', () => {
    expect(command_source_label('builtin')).toBe('内置')
    expect(command_source_label('skill')).toBe('技能')
  })

  it('未知来源原样返回，便于发现后端新增来源却没同步前端', () => {
    expect(command_source_label('plugin')).toBe('plugin')
  })
})
