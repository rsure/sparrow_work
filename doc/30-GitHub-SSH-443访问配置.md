# GitHub 访问改走 SSH over 443（`fetch` / `push` 不再依赖代理）

> **起因**：`git pull` 反复失败，报
> `unable to access 'https://github.com/rsure/sparrow_work.git/': Failed to connect to github.com port 443 after 21115 ms: Couldn't connect to server`，
> 换个时段又变成 `Recv failure: Connection was reset`。
> 根因是**本机直连 GitHub 的 HTTPS 443 在 TLS 阶段被干扰**，而本机代理软件
> （`KuaijiasuCore`，监听 `127.0.0.1:7892`）并不是每次开机都启动；
> 一旦 `git config` 里把代理写死，代理没开时 git 又会去连一个不存在的本地端口。
>
> 解决办法：**让 git 根本不走 HTTPS，改走 SSH over 443**。`ssh.github.com:443` 在同样网络下可以直连通过，
> 这样无论代理开不开都不影响。本文记录判断依据、一键脚本、手动步骤与回退方式。
>
> **状态**：✅ 已在开发机（`leade@WangShuo`，Windows 11 / OpenSSH 9.5p1）落地并实测通过，见 §6。

---

## 0. 另一台电脑怎么用（先看这节）

本文档的目标是「新机器读到就能配好」。按你手上有谁执行，选一条：

**A. 直接跑脚本（推荐，一条命令）**

```powershell
# 在仓库根目录执行
node scripts/setup-github-ssh.mjs --switch-remote
```

脚本是幂等的，做完会告诉你**唯一剩下的人工步骤**：把打印出来的公钥粘贴到
<https://github.com/settings/ssh/new>。粘贴完再跑一次同一条命令即可收尾。

**B. 把文档交给 AI 代理执行**

把下面这段原样发给它：

```
请阅读 doc/30-GitHub-SSH-443访问配置.md，按第 3 节执行 scripts/setup-github-ssh.mjs --switch-remote。
如果脚本以退出码 3 结束，说明公钥还没注册到 GitHub：把脚本打印的公钥原文给我，
并告诉我需要去 https://github.com/settings/ssh/new 粘贴。
如果以退出码 2 结束，把第 7 节的手动配置片段应用后再重跑。
其它退出码请把完整输出贴给我，不要自行回退 origin。
```

**C. 不想跑脚本**：按 §4 手动配置，5 分钟。

---

## 1. 现象与根因

### 1.1 实测对比（2026-10-30，本机）

| 路径 | 结果 | 说明 |
| --- | --- | --- |
| 直连 `https://github.com`（不走代理） | ❌ 20 秒超时，收到 0 字节 | TLS 握手阶段被重置 |
| HTTPS 经 `127.0.0.1:7892` 代理 | ✅ HTTP 200 | 能用，但**依赖代理软件在跑** |
| 直连 `ssh.github.com:443`（TCP） | ✅ 连通 | SSH 通道没被干扰 |
| 直连 `github.com:22`（TCP） | ✅ 连通 | 但主机密钥校验有历史残留，不采用 |
| `ssh -T git@github.com`（配置后） | ✅ `Hi rsure!` | 认证通过，无需代理 |

### 1.2 为什么「配了代理还是时好时坏」

`git` **不读 Windows 系统的 WinINET 代理设置**（设置里那个 `127.0.0.1:7892` 它看不见），
它只认 `http.proxy` 配置项或 `HTTPS_PROXY` 环境变量。
所以一旦把 `http.https://github.com.proxy` 写死成 `127.0.0.1:7892`：

- 代理开着 → 正常；
- 代理没开 → 报 `Failed to connect to 127.0.0.1 port 7892`，比原来的报错更难懂。

**结论：写死代理只是把问题挪了个位置，不是解法。** 只有让 git 不依赖代理才根治。

---

## 2. 为什么选 SSH over 443

| 方案 | 结论 | 理由 |
| --- | --- | --- |
| **SSH over 443**（采用） | ✅ | 实测直连可达；不依赖任何代理软件；一次配置长期有效 |
| 写死 HTTPS 代理 | ❌ | 代理不开就失败，只是个转移问题的补丁 |
| 脚本自动探测代理端口再决定 | ⚠️ 备选 | 不改 GitHub 设置，但只对终端里手敲的命令生效；IDEA / VSCode 内置 git 不认，且代理没开时该慢还是慢 |
| 镜像站 / ghproxy 类加速 | ❌ | 第三方稳定性不可控，且推送要额外认证，不适合作为仓库长期 remote |

GitHub 官方支持的 SSH over 443 入口是 `ssh.github.com:443`
（[官方文档](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)），
行为与标准 22 端口完全一致，只是换了个端口穿墙。

---

## 3. 一键脚本 `scripts/setup-github-ssh.mjs`

### 3.1 前置条件

| 依赖 | 检查命令 | 没有的话 |
| --- | --- | --- |
| Node.js（项目已有） | `node -v` | 先装项目依赖环境 |
| `ssh` / `ssh-keygen` | `ssh -V` | Windows 设置 → 系统 → 可选功能 → 添加「OpenSSH 客户端」 |
| 在仓库目录内执行 | `git rev-parse --show-toplevel` | `cd` 到仓库根目录 |

### 3.2 用法

```powershell
# 只检查并修好 SSH 通道（不动 origin）
node scripts/setup-github-ssh.mjs

# 检查 + 验证 + 把 origin 切成 SSH（推荐，新机器用这个）
node scripts/setup-github-ssh.mjs --switch-remote

# 出问题时一键切回 HTTPS
node scripts/setup-github-ssh.mjs --fallback-https
```

也可以用 pnpm 快捷键：`pnpm run setup:gh-ssh -- --switch-remote`。

### 3.3 脚本做什么、不做什么

做（全部幂等，重复跑不会重复写配置、不会覆盖已有私钥）：

1. 检查 `~/.ssh/config`，缺 `github.com` 的 SSH over 443 段才追加；
2. 检查私钥：有 `id_ed25519` 用它，否则复用 `id_rsa`，都没有才用 `ssh-keygen` 生成 ed25519；
3. `ssh -T git@github.com` 实测认证；
4. **认证通过后**才把 `origin` 切成 `git@github.com:rsure/sparrow_work.git`；
5. 最后跑一次真实 `git fetch` 做端到端验证。

不做：

- 不碰任何业务代码、不改 `~/.ssh/config` 里已有的其它 `Host` 段；
- 不会替你往 GitHub 加公钥（需要账号操作，只能人来）；
- 不会在认证失败时切换 `origin`——避免造成「SSH 连不上、HTTPS 也被绕过」的死局。

### 3.4 退出码含义

| 退出码 | 含义 | 下一步 |
| --- | --- | --- |
| `0` | 成功 | 完事 |
| `1` | 生成私钥失败 / 切换 `origin` 失败 | 看报错，多半是 `ssh-keygen` 不在 PATH |
| `2` | 已存在 `Host github.com` 但指向别处，脚本拒绝自动改 | 按 §7.2 手工处理 |
| `3` | 通道通了，但 GitHub 不认这把公钥 | 把脚本打印的公钥加到 GitHub 再重跑 |
| `4` | 认证通过但 `git fetch` 失败 | 检查 `origin` 是否为 `git@` 形式 |

---

## 4. 手动配置步骤（不跑脚本时）

### 4.1 写 `~/.ssh/config`

文件路径 `C:\Users\<你的用户名>\.ssh\config`（Linux/macOS 为 `~/.ssh/config`），内容：

```sshconfig
Host github.com
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile C:/Users/<你的用户名>/.ssh/id_rsa
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

逐项为什么这么写：

| 配置 | 作用 |
| --- | --- |
| `HostName ssh.github.com` + `Port 443` | 让 `github.com` 的连接实际打到官方 SSH over 443 入口 |
| `User git` | GitHub 的 SSH 登录名固定是 `git`，不是你的账号名 |
| `IdentityFile` | 指定私钥；用正斜杠，Windows 与 POSIX 都能识别 |
| `IdentitiesOnly yes` | 只试这一把 key，不在一堆 key 里逐个试，握手更快也不会连锁失败 |
| `StrictHostKeyChecking accept-new` | 首次自动记录主机密钥（TOFU），**之后密钥变化仍会拒绝**；只为让脚本不卡在交互确认 |
| `ServerAliveInterval` / `CountMax` | 每 30 秒保活，避免长连接被 NAT / 防火墙静默切断 |

### 4.2 确认私钥存在

```powershell
# 有输出说明已有 key，跳 4.4
Test-Path "$env:USERPROFILE\.ssh\id_rsa" -or Test-Path "$env:USERPROFILE\.ssh\id_ed25519"
```

没有就生成一把（`-N ''` 表示不设口令；`-C` 是给人看的备注）：

```powershell
ssh-keygen -t ed25519 -C "$env:USERNAME@$env:COMPUTERNAME" -f "$env:USERPROFILE\.ssh\id_ed25519" -N ''
```

### 4.3 把公钥注册到 GitHub

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"   # 或 id_rsa.pub
```

复制整行，打开 <https://github.com/settings/ssh/new>：
`Title` 随意（建议带机器名）、`Key type` 选 `Authentication Key`、粘贴后 `Add SSH key`。

### 4.4 验证认证

```powershell
ssh -T git@github.com
```

期望输出（GitHub 不给 shell，所以这句话是成功标志）：

```
Hi <你的GitHub用户名>! You've successfully authenticated, but GitHub does not provide shell access.
```

> 注意退出码：**成功时是 1，不是 0**。脚本靠「等于 1」判断成功，不要被这个反直觉的行为误导。

### 4.5 切换 remote

```powershell
git remote set-url origin git@github.com:rsure/sparrow_work.git
git remote -v
git fetch origin
```

---

## 5. 验证清单

按顺序跑，全绿才算配好：

```powershell
# 1) 配置是否被解析成 443
ssh -G github.com | Select-String -Pattern '^(hostname|port|identityfile) '
#   期望：hostname ssh.github.com / port 443 / identityfile 指向你的私钥

# 2) 认证是否通过
ssh -T git@github.com
#   期望：Hi rsure! You've successfully authenticated...

# 3) remote 是否是 SSH 形式
git remote -v
#   期望：origin  git@github.com:rsure/sparrow_work.git

# 4) 端到端（重点：先把代理环境变量清掉，证明真的不依赖代理）
Remove-Item Env:HTTPS_PROXY,Env:HTTP_PROXY -ErrorAction SilentlyContinue
git fetch origin
```

---

## 6. 本机实测记录（2026-10-30）

| 项 | 结果 |
| --- | --- |
| 环境 | Windows 11，OpenSSH_for_Windows_9.5p1，Git 自带 curl |
| 私钥 | 复用已有 `C:\Users\leade\.ssh\id_rsa`（3072 位 RSA，`SHA256:3vYRxJ…AkbQ`） |
| `ssh -T git@github.com` | ✅ `Hi rsure!` |
| 清空全部代理环境变量后 `git fetch origin` | ✅ **4.5 秒** |
| `git push --dry-run origin main` | ✅ `Everything up-to-date` |
| 代理软件状态 | 测试时**未依赖**；`http.https://github.com.proxy` 保留作为备用通道，与 SSH 不冲突 |

---

## 7. 常见问题

### 7.1 代理软件开着 / 关着，有影响吗？

没有。SSH 走的是 `HostName ssh.github.com` + `Port 443` 的独立 TCP 连接，**完全不经过 `http.proxy`**。
之前为 HTTPS 配的那条 `http.https://github.com.proxy` 可以留着当备用，两者互不干扰。

### 7.2 报「已存在 `Host github.com` 但未走 SSH over 443」（退出码 2）

说明 `~/.ssh/config` 里早有一段 `Host github.com` 指向别处（可能被公司 GitLab 或别的工具占用）。
脚本为了不破坏你的配置不会强改，请手工在该段里补：

```sshconfig
    HostName ssh.github.com
    Port 443
    User git
```

如果那段是给别的服务用的，改用**别名**更安全：

```sshconfig
# 给 GitHub 单独的别名，不影响已有的 Host github.com
Host github-work
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile C:/Users/<用户名>/.ssh/id_rsa
    IdentitiesOnly yes
```

然后 remote 用别名：`git remote set-url origin git@github-work:rsure/sparrow_work.git`。

### 7.3 公司网络把 SSH 也拦了怎么办

先验证到底是哪一层断的：

```powershell
Test-NetConnection ssh.github.com -Port 443
# TcpTestSucceeded = True  → TCP 通，问题在认证或公司代理拦截 SSH 协议
# TcpTestSucceeded = False → 连 443 都出不去，需要走公司代理/跳板
```

TCP 不通时回退 HTTPS + 代理：

```powershell
node scripts/setup-github-ssh.mjs --fallback-https
git config --global "http.https://github.com.proxy" "http://127.0.0.1:<代理端口>"
```

### 7.4 为什么不要用 `github.com:22`

本机实测 22 端口 TCP 也通，但 `known_hosts` 里有历史残留导致 `Host key verification failed`，
而 443 入口是 GitHub 官方为「22 被拦」准备的等价通道，更稳。真要修 22 的主机密钥：

```powershell
ssh-keygen -R github.com     # 删掉旧记录
ssh -T git@github.com        # 重新确认（会打印新指纹）
```

### 7.5 想在另一台机器测试但不想动真实配置

`ssh` 在 Windows 上**不认 `USERPROFILE` 环境变量**（它走 `GetUserProfileDirectory` 拿真实用户目录），
所以「临时改 `USERPROFILE` 来模拟新机器」是**无效的**——`ssh -G github.com` 仍会读真实 `~/.ssh/config`。
要在隔离环境验证，用 `ssh -F <配置文件> -i <私钥>` 显式指定，别指望环境变量。

---

## 8. 回退

一条命令切回 HTTPS：

```powershell
node scripts/setup-github-ssh.mjs --fallback-https
```

或者手工：

```powershell
git remote set-url origin https://github.com/rsure/sparrow_work.git
```

`~/.ssh/config` 里的 `Host github.com` 段留着无害（SSH 用不到时不会被读取），
确认要删再手工移除。
