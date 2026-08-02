/**
 * scripts/install-hooks.mjs —— 把仓库自带的 git 钩子接到本地仓库（`pnpm run setup:hooks`）。
 *
 * 只改一项配置：core.hooksPath → .githooks。
 * 为什么用 hooksPath 而不是往 .git/hooks 里拷文件：
 *   拷贝出去的文件不在版本控制里，新人拉下来没有、改了也传不出去；
 *   hooksPath 指向仓库内的目录，钩子本身跟着代码走，改一处全队生效。
 *
 * 没有 .git（例如只解压了源码包）时只提示、不报错：钩子装不上不该挡住首次初始化。
 */

// Node 标准库：child_process.execFileSync 同步执行 git 命令（配置失败要立刻知道）
import { execFileSync } from 'node:child_process'
// Node 标准库：fs.existsSync 判断当前目录是不是 git 仓库
import { existsSync } from 'node:fs'

/** 钩子目录（相对仓库根）；与 .githooks/pre-commit 对应 */
const HOOKS_PATH = '.githooks'

/** 把 core.hooksPath 指向 .githooks；返回是否设置成功 */
function installHooks() {
  if (!existsSync('.git')) {
    console.log('[setup:hooks] 当前目录不是 git 仓库，跳过钩子安装')
    return false
  }
  // -C 用当前目录，避免脚本在别的目录被调用时改错仓库
  execFileSync('git', ['config', 'core.hooksPath', HOOKS_PATH], { stdio: 'inherit' })
  console.log(`[setup:hooks] 已启用 ${HOOKS_PATH}/pre-commit（提交前跑迁移漂移检查）`)
  console.log('[setup:hooks] 临时跳过：git commit --no-verify')
  return true
}

installHooks()
