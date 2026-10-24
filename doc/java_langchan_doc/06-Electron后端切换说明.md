# 06 · Electron 后端切换说明（Java / Python）

> 目标：Electron 可以在 Java（Spring Boot）与 Python（FastAPI）两套后端之间切换，
> **默认 Java**。切换方式有三种：配置文件、环境变量、命令行参数。

---

## 1. 文件与代码位置

| 文件 | 作用 |
| --- | --- |
| `backend.config.json` | 后端目标与启动命令模板（项目根目录；打包后进 resources） |
| `electron/src/shared/backend-config.ts` | 读取配置、合并环境变量、解析 Maven 命令 |
| `electron/src/shared/config.ts` | `BackendTarget` 类型、默认目标、健康检查路径 |
| `electron/src/main/backend.ts` | 按目标拉起 Java / Python 后端，心跳与健康检查 |
| `scripts/dev.mjs` | 一键开发启动器；同样支持目标切换 |
| `scripts/run-maven.mjs` | 用 Maven Wrapper 执行任意 Maven 命令 |
| `scripts/sync-java-backend.mjs` | 把 jar 同步到 `electron/resources/backend/` |
| `electron/electron-builder.yml` | 把 jar / 配置 / 可选 JRE 打进安装包 |

---

## 2. 配置文件

项目根目录的 `backend.config.json`：

```json
{
  "target": "java",
  "port": 8000,
  "java": {
    "devDir": "backend_java",
    "devCommand": "{mvnw} -f backend_java/pom.xml spring-boot:run -Dspring-boot.run.arguments=--server.port={port}",
    "jar": "backend-java.jar",
    "bundledJre": "jre",
    "startupTimeoutMs": 180000
  },
  "python": {
    "devDir": "backend",
    "devCommand": "uv run python run.py --port {port}",
    "exe": "app-backend.exe",
    "startupTimeoutMs": 30000
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `target` | `java` / `python`；默认 `java` |
| `port` | 后端端口；默认 8000 |
| `java.devCommand` | 开发态命令模板；`{mvnw}` 替换成 Wrapper 或 `mvn`，`{port}` 替换成端口 |
| `java.jar` | 打包态 jar 文件名（位于 `resources/backend/`） |
| `java.bundledJre` | 打包态可选 JRE 目录名（位于 `resources/backend/`） |
| `java.startupTimeoutMs` | Java 启动等待时间；首次 Maven 下载依赖较慢 |
| `python.devCommand` | Python 开发态命令模板 |
| `python.exe` | 打包态可执行文件名 |
| `python.startupTimeoutMs` | Python 启动等待时间 |

> 修改默认值时，记得同时改 `electron/src/shared/backend-config.ts` 与
> `scripts/dev.mjs` 里的 `DEFAULT_BACKEND_CONFIG` / `DEFAULT_*`，两处逻辑是等价的。

---

## 3. 环境变量

| 变量 | 说明 |
| --- | --- |
| `APP_BACKEND_TARGET` | `java` / `python`；优先级高于配置文件 |
| `BACKEND_TARGET` | 同上，兼容别名 |
| `APP_PORT` | 覆盖端口 |
| `JAVA_BACKEND_CMD` | 整体覆盖 Java 开发态命令 |
| `JAVA_BACKEND_JAR` | 打包态指定 jar 路径 |
| `JAVA_BACKEND_JAVA` | 指定运行 jar 的 `java` 可执行文件 |
| `PYTHON_BACKEND_CMD` | 整体覆盖 Python 开发态命令 |
| `PYTHON_BACKEND_EXE` | 打包态指定 Python 可执行文件 |
| `APP_PARENT_GUARD` | 由 Electron 自动注入 `1`，后端据此启用 stdin 父进程守护 |

示例（PowerShell）：

```powershell
# 本次改用 Python
$env:APP_BACKEND_TARGET = 'python'
pnpm run dev

# 本次改用 9000 端口
$env:APP_PORT = '9000'
pnpm run dev
```

---

## 4. 命令行参数（`scripts/dev.mjs`）

```bash
node scripts/dev.mjs                       # 按配置文件（默认 java）
node scripts/dev.mjs --backend=java        # 本次强制 Java
node scripts/dev.mjs --backend=python      # 本次强制 Python
node scripts/dev.mjs --port=9000           # 本次改端口
node scripts/dev.mjs --backend-only        # 只起后端
```

优先级：**命令行 > 环境变量 > 配置文件 > 默认值**。

对应的 pnpm 脚本：

```bash
pnpm run dev                 # 前端 + 后端 + Electron（默认 Java）
pnpm run dev:backend         # 只起后端（按配置）
pnpm run dev:backend:java    # 只起 Java 后端
pnpm run dev:backend:python  # 只起 Python 后端
```

---

## 5. 启动流程（代码视角）

```text
app.whenReady()
  → bootstrap()
      → startBackend({ projectRoot, resourcesPath, isPackaged })
          → loadBackendConfig(...)        读取 json + env
          → getBackendPort(config.port)   APP_PORT 覆盖
          → waitForHealth(port, 800)      已有后端就复用
          → target === 'java'
              ├─ isPackaged && jar 存在 → spawn java -jar ...
              ├─ 开发态                → spawn mvnw spring-boot:run ...
              └─ 打包态但 jar 缺失      → 打日志，等健康检查超时
          → target === 'python'
              ├─ exe 存在              → spawn app-backend(.exe)
              └─ 开发态                → spawn uv run python run.py ...
          → 心跳（stdin）+ 健康检查（最长 startupTimeoutMs）
      → createWindow()
```

开发态优先用 Maven/uv，**即使本地有 jar 也不用**，保证改代码后立即生效。
打包态只认 jar/exe，不再尝试开发命令。

> **数据库位置**：打包态 Java 后端由 Electron 自动注入
> `APP_DB_PATH` 与 `APP_CHECKPOINT_DB_PATH`，默认指向
> `app.getPath('userData')/app.db`，避免安装目录（如 Program Files）不可写。
> 用户显式设置这两个环境变量时，以用户值为准。

---

## 6. 打包

### 6.1 Java

```bash
pnpm run build:backend:java
# = mvn -DskipTests package
#   + 复制 backend_java/target/backend-java.jar
#     到 electron/resources/backend/backend-java.jar
```

然后：

```bash
pnpm run dist:win
```

安装包内：

```text
resources/
├─ backend/
│  ├─ backend-java.jar
│  └─ jre/                （可选，精简 JRE）
├─ backend.config.json
└─ renderer/
```

### 6.2 Python（保留）

```bash
pnpm run build:backend
pnpm run dist:win
```

两套产物可以同时放在 `resources/backend/`，由 `backend.config.json` 的 `target` 决定用哪个。

### 6.3 精简 JRE

```bash
jlink --add-modules java.base,java.logging,java.sql,java.naming,java.desktop \
      --output electron/resources/backend/jre
```

- 模块集合按运行时报错逐步补；
- 目录名要与 `backend.config.json` 的 `java.bundledJre` 一致；
- `electron/src/main/backend.ts` 会优先使用
  `resources/backend/jre/bin/java(.exe)`，找不到才退回系统 `java`。

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 启动日志 `UnsupportedClassVersionError` | 系统 `java` 是 8 | 设置 `JAVA_HOME` 到 17+，或设置 `JAVA_BACKEND_JAVA` |
| `mvnw.cmd` 找不到 | 文件被删或权限问题 | 重新生成：`mvn -N wrapper:wrapper -Dmaven=3.9.11` |
| Maven 首次启动超时 | 正在下载依赖 | 先跑 `pnpm run setup:java`，或调大 `startupTimeoutMs` |
| 打包后报“未找到 backend-java.jar” | 没执行 build:backend:java | 先构建再 `dist` |
| 打包后 Java 启动失败但开发态正常 | 安装包内没有 JRE，且用户没装 JDK 17 | 放 `resources/backend/jre/`，或在安装说明要求 JDK 17 |
| Electron 复用了错误的后端 | 8000 端口已有旧进程 | 关掉旧进程；主进程会先探活复用 |
| 健康检查一直失败 | 端口不一致 / 后端启动报错 | 看 `[backend:java]` 日志；确认 `APP_PORT` 与 `VITE_BACKEND_PROXY` 一致 |
| 中文日志乱码 | Windows 控制台 GBK | jar 启动已加 `-Dfile.encoding=UTF-8`；开发态可在 `JAVA_BACKEND_CMD` 里加 |

---

## 8. 设计说明：为什么不用一个 `backend.ts` 写死

- **配置与代码分离**：切换目标不需要改 TypeScript；
- **环境变量优先**：CI / 临时调试不用改文件；
- **开发/打包分离**：开发态用源码启动，打包态用产物，避免“改了代码但跑的是旧 jar”；
- **失败可见**：找不到 jar/exe 时打日志并让健康检查超时，而不是静默回退到另一种语言；
- **父进程守护**：Java/Python 都读 stdin，Electron 被强杀时管道关闭，后端自退，避免孤儿进程。

---

## 9. 一页速查

```bash
# 默认 Java
pnpm run dev

# 临时 Python
pnpm run dev -- --backend=python
# 或者
APP_BACKEND_TARGET=python pnpm run dev

# 只起 Java 后端
pnpm run dev:backend:java

# 构建 Java jar 并同步
pnpm run build:backend:java

# 跑 Java 测试
pnpm run test:backend:java
```
