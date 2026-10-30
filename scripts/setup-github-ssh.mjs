/**
 * 模块说明：把本机 git 访问 GitHub 的方式切换到「SSH over 443」。
 *
 * 解决什么问题
 * ------------
 * 国内网络下访问 `https://github.com` 的 443 端口，经常在 TLS 握手阶段被重置，
 * git 会报 `Recv failure: Connection was reset` 或
 * `Failed to connect to github.com port 443 after 21115 ms: Couldn't connect to server`。
 * 而 `ssh.github.com:443` 的 SSH 通道通常可以直连通过。
 * 把 remote 切成 SSH、并让 `github.com` 解析到 `ssh.github.com:443` 之后，
 * git 就不再依赖 Clash / 快家速 这类本地代理软件是否开启。
 *
 * 脚本做的四件事（幂等，可重复执行，不会覆盖已有私钥与已有配置）
 * ------------------------------------------------------------
 *   1. 检查 `~/.ssh/config`，缺少 `github.com` 的 SSH over 443 段才追加
 *   2. 检查私钥，`id_ed25519` / `id_rsa` 都没有时用 `ssh-keygen` 生成 ed25519
 *   3. 用 `ssh -T` 实测认证，通过后才允许把 origin 切成 SSH
 *   4. 打印公钥，并明确告诉人还剩哪一步要在 GitHub 网页上做
 *
 * 用法
 * ----
 *   node scripts/setup-github-ssh.mjs                  只把 SSH 通道修好并验证
 *   node scripts/setup-github-ssh.mjs --switch-remote  同时把 origin 切成 SSH
 *   node scripts/setup-github-ssh.mjs --fallback-https 一键切回 HTTPS（回退用）
 *
 * 注意：本脚本只改「本机 SSH 配置」和「当前仓库的 origin」，不动任何业务代码。
 */

// Node 内置：取用户主目录，用于定位 ~/.ssh（Windows 是 C:\Users\xxx，Linux/macOS 是 /home/xxx）
import { homedir } from 'node:os'
// Node 内置：跨平台拼接路径，避免手写反斜杠在 POSIX 上出错
import path from 'node:path'
// Node 内置：读写 ~/.ssh/config、判断私钥文件是否存在
import fs from 'node:fs'
// Node 内置：同步执行 ssh / ssh-keygen / git，并拿到退出码与输出
import { spawnSync } from 'node:child_process'

/** 用户主目录，SSH 相关文件都放在它下面的 .ssh 里 */
const HOME = homedir()
/** ~/.ssh 目录绝对路径，SSH 配置与私钥都在这里 */
const SSH_DIR = path.join(HOME, '.ssh')
/** SSH 客户端配置文件路径（~/.ssh/config） */
const SSH_CONFIG = path.join(SSH_DIR, 'config')
/** 优先使用的私钥文件名：新机器生成 ed25519，算法更现代、握手更快 */
const PREFERRED_KEY_NAME = 'id_ed25519'
/** 兼容已有机器：之前用 RSA 生成的私钥文件名 */
const LEGACY_KEY_NAME = 'id_rsa'
/** GitHub 官方的 SSH over 443 入口主机名（走标准 22 端口被拦时的替代入口） */
const SSH_HOST = 'ssh.github.com'
/** SSH over 443 使用的端口号，字符串形式便于直接写进 config 与命令行 */
const SSH_PORT = '443'
/** 本仓库在 GitHub 上的所有者账号 */
const REPO_OWNER = 'rsure'
/** 本仓库在 GitHub 上的仓库名 */
const REPO_NAME = 'sparrow_work'
/** 已配置过 SSH over 443 的标记：config 里出现这一行就认为无需再写 */
const CONFIG_MARKER = `HostName ${SSH_HOST}`

/**
 * 统一格式的进度输出，让每一步的结论一眼可辨。
 * @param {string} icon 状态符号，例如 '✓' / '✗' / '·' / '!'
 * @param {string} message 要打印的中文说明
 */
function log(icon, message) {
  console.log(`${icon} ${message}`)
}

/**
 * 解析命令行参数，得到本次运行要做哪些动作。
 * @param {string[]} argv `process.argv.slice(2)` 传进来的原始参数数组
 * @returns {{switchRemote: boolean, fallbackHttps: boolean}} 两个开关：是否切到 SSH、是否切回 HTTPS
 */
function parseArgs(argv) {
  return {
    switchRemote: argv.includes('--switch-remote'),
    fallbackHttps: argv.includes('--fallback-https'),
  }
}

/**
 * 找本机已有的私钥；都没有则返回首选路径（由调用方决定是否生成）。
 * @returns {{path: string, exists: boolean, reused: boolean}} 私钥路径、是否存在、是否复用了遗留的 RSA 私钥
 */
function resolveKey() {
  // 先看 ed25519，新机器生成的都在这里
  const preferred = path.join(SSH_DIR, PREFERRED_KEY_NAME)
  if (fs.existsSync(preferred)) {
    return { path: preferred, exists: true, reused: false }
  }
  // 再看历史遗留的 RSA 私钥，有就直接复用，不强迫人重新去 GitHub 注册新公钥
  const legacy = path.join(SSH_DIR, LEGACY_KEY_NAME)
  if (fs.existsSync(legacy)) {
    return { path: legacy, exists: true, reused: true }
  }
  return { path: preferred, exists: false, reused: false }
}

/**
 * 幂等地写好 ~/.ssh/config 里的 github.com 段。
 * 已存在 SSH over 443 配置时不动；已存在 `Host github.com` 但指向别处时只警告、不覆盖。
 * @param {string} keyPath 本次实际使用的私钥绝对路径，写进 IdentityFile
 * @returns {boolean} true 表示配置已就绪（原本就有或本次写入成功）
 */
function ensureSshConfig(keyPath) {
  // config 目录可能不存在（全新机器第一次配 SSH）
  fs.mkdirSync(SSH_DIR, { recursive: true })

  // 用正斜杠写 IdentityFile，Windows OpenSSH 与 POSIX 都能直接识别
  const keyForConfig = keyPath.replace(/\\/g, '/')

  // 要追加进 config 的整段内容，逐行都带「为什么这么配」的注释
  const block = [
    '',
    '# ===== GitHub 走 SSH over 443 =====',
    '# 本机直连 github.com:443 时 TLS 连接常被重置，而 ssh.github.com:443 的 SSH 通道可直连通过，',
    '# 因此统一用 SSH 访问 GitHub，不再依赖本地代理软件是否开启。',
    'Host github.com',
    `    HostName ${SSH_HOST}`,
    `    Port ${SSH_PORT}`,
    '    User git',
    `    IdentityFile ${keyForConfig}`,
    '    IdentitiesOnly yes',
    '    StrictHostKeyChecking accept-new',
    '    ServerAliveInterval 30',
    '    ServerAliveCountMax 3',
    '',
  ].join('\n')

  // 文件不存在：直接创建
  if (!fs.existsSync(SSH_CONFIG)) {
    fs.writeFileSync(SSH_CONFIG, block, 'utf8')
    log('✓', `已创建 ${SSH_CONFIG}`)
    return true
  }

  const current = fs.readFileSync(SSH_CONFIG, 'utf8')

  // 已经配过 SSH over 443：幂等跳过，避免把文件越写越乱
  if (current.includes(CONFIG_MARKER)) {
    log('✓', '~/.ssh/config 已包含 GitHub SSH over 443 配置，跳过写入')
    return true
  }

  // 已有 Host github.com 段但没指向 443：可能指向公司 GitLab 等，不能擅自改
  if (/^\s*Host\s+github\.com\b/m.test(current)) {
    log('!', '~/.ssh/config 里已存在 `Host github.com` 但未走 SSH over 443')
    log('!', '为避免破坏你原有的配置，本次不自动修改。请手工在对应段里补上：')
    console.log(`      HostName ${SSH_HOST}\n      Port ${SSH_PORT}\n      User git\n      IdentityFile ${keyForConfig}`)
    return false
  }

  // 全新配置：追加到文件末尾
  fs.appendFileSync(SSH_CONFIG, block, 'utf8')
  log('✓', `已向 ${SSH_CONFIG} 追加 GitHub SSH over 443 配置`)
  return true
}

/**
 * 确保本机有可用的私钥；没有就现场生成一把 ed25519，不做任何交互。
 * @param {{path: string, exists: boolean, reused: boolean}} key resolveKey() 的返回值
 * @returns {{path: string, exists: boolean, reused: boolean}} 生成后的私钥信息
 */
function ensureKey(key) {
  if (key.exists) {
    log('✓', `复用已有私钥 ${key.path}${key.reused ? '（RSA，已兼容）' : ''}`)
    return key
  }

  // 全新机器上连 ~/.ssh 目录都不存在，必须先建出来，
  // 否则 ssh-keygen 会报 `Saving key ... failed: No such file or directory`
  fs.mkdirSync(SSH_DIR, { recursive: true })

  // -t ed25519：算法现代、密钥短、握手快
  // -N ''：不设口令，避免每次 fetch 都弹交互（个人开发机上的常规取舍）
  // -C：注释取「用户名@主机名」，方便在 GitHub 上认出是哪台机器
  const comment = `${process.env.USERNAME || process.env.USER || 'dev'}@${process.env.COMPUTERNAME || 'host'}`
  const res = spawnSync(
    'ssh-keygen',
    ['-t', 'ed25519', '-N', '', '-C', comment, '-f', key.path],
    { stdio: 'inherit' },
  )

  if (res.status !== 0) {
    log('✗', `生成私钥失败（退出码 ${res.status}）。请确认 ssh-keygen 在 PATH 中，且 ${SSH_DIR} 可写`)
    process.exit(1)
  }
  log('✓', `已生成新私钥 ${key.path}`)
  return { path: key.path, exists: true, reused: false }
}

/**
 * 用 `ssh -T` 实测 GitHub 认证是否打通。
 * GitHub 不提供 shell，认证成功时退出码是 1，失败（如公钥未注册）是 255，据此判断。
 * @returns {boolean} true 表示认证通过，说明 GitHub 账号已接受本机公钥
 */
function testAuth() {
  const res = spawnSync(
    'ssh',
    ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', '-T', 'git@github.com'],
    { encoding: 'utf8' },
  )
  // 把 ssh 的原始输出显示出来，成功失败都能看到 GitHub 的原文提示
  const output = `${res.stdout || ''}${res.stderr || ''}`.trim()
  if (output) {
    // 每行加两个空格缩进，和脚本自己的输出区分开
    console.log(output.split('\n').map((line) => `    ${line}`).join('\n'))
  }
  return res.status === 1
}

/**
 * 读取并返回公钥文本，供人复制到 GitHub。
 * @param {string} keyPath 私钥路径，同目录下的同名 .pub 就是公钥
 * @returns {string} 单行公钥内容；读取失败返回空字符串
 */
function readPublicKey(keyPath) {
  try {
    return fs.readFileSync(`${keyPath}.pub`, 'utf8').trim()
  } catch {
    return ''
  }
}

/**
 * 读取当前仓库 origin 的 URL。
 * @returns {string} origin 地址；取不到时返回空字符串
 */
function getOriginUrl() {
  const res = spawnSync('git', ['remote', 'get-url', 'origin'], { encoding: 'utf8' })
  return res.status === 0 ? res.stdout.trim() : ''
}

/**
 * 把 origin 改成指定的 URL。
 * @param {string} url 新的 origin 地址
 * @returns {boolean} true 表示改写成功
 */
function setOriginUrl(url) {
  const res = spawnSync('git', ['remote', 'set-url', 'origin', url], { stdio: 'inherit' })
  return res.status === 0
}

/**
 * 主流程：依次完成配置检查、密钥准备、认证验证，并按参数决定是否切 remote。
 */
function main() {
  const { switchRemote, fallbackHttps } = parseArgs(process.argv.slice(2))

  console.log('\n=== GitHub SSH over 443 一键配置 ===\n')

  // 回退分支：只把 origin 切回 HTTPS，其余一律不动
  if (fallbackHttps) {
    const httpsUrl = `https://github.com/${REPO_OWNER}/${REPO_NAME}.git`
    if (setOriginUrl(httpsUrl)) {
      log('✓', `origin 已切回 HTTPS：${httpsUrl}`)
    } else {
      log('✗', '切回 HTTPS 失败，请确认当前目录是 git 仓库')
      process.exit(1)
    }
    return
  }

  const key = ensureKey(resolveKey())

  if (!ensureSshConfig(key.path)) {
    log('!', '配置未能自动完成，请按上面的提示手工补全后重新运行本脚本')
    process.exit(2)
  }

  log('·', '正在实测 SSH 认证…')
  const authed = testAuth()

  const publicKey = readPublicKey(key.path)

  if (!authed) {
    log('✗', 'SSH 认证未通过 —— 通道已连通，但 GitHub 账号还不认识这把公钥')
    if (publicKey) {
      console.log('\n请把下面这行公钥整段复制，粘贴到 https://github.com/settings/ssh/new\n')
      console.log(`  ${publicKey}\n`)
      console.log('添加后再运行一次本脚本即可。')
    }
    process.exit(3)
  }

  log('✓', 'SSH 认证通过，GitHub 已认可本机公钥')

  // 认证通过后才动 remote：否则会把仓库搞成「SSH 连不上、HTTPS 也被绕过」的死局
  if (switchRemote) {
    const url = getOriginUrl()
    if (url.startsWith('git@')) {
      log('✓', `origin 已经是 SSH：${url}`)
    } else {
      const sshUrl = `git@github.com:${REPO_OWNER}/${REPO_NAME}.git`
      if (setOriginUrl(sshUrl)) {
        log('✓', `origin 已切到 SSH：${sshUrl}`)
      } else {
        log('✗', '切换 origin 失败，请确认当前目录是 git 仓库')
        process.exit(1)
      }
    }
  } else {
    log('·', '未加 --switch-remote，origin 保持不变（如需切换请带该参数重跑）')
  }

  // 最后做一次真实网络操作，确认整条链路可用
  log('·', '正在用 git fetch 验证端到端连通性…')
  const fetch = spawnSync('git', ['fetch', 'origin'], { stdio: 'inherit' })
  if (fetch.status === 0) {
    log('✓', 'git fetch 成功，以后 pull / push 不再依赖本地代理软件')
  } else {
    log('✗', 'git fetch 失败，请检查 origin 地址是否为 SSH 形式')
    process.exit(4)
  }
}

main()
