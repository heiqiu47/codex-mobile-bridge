# Agent Note: SSH Claude Code CLI 会话

Status: implemented

## 问题

Claude CLI 适配器只读取本机原生历史。手机无法使用所选 SSH 主机上的 Claude 安装、账号、配置、历史和项目目录。

## 决策

复用 App 信任的 SSH 主机别名及严格的非交互 SSH 传输，在远程登录 shell 中运行独立的标准库工作程序。被动列表/详情读取主机自身 Claude 配置和 JSONL 历史，不激活会话。网关 ID 绑定主机 ID、配置来源和原生会话 UUID。显式恢复重新检查配置、历史、认证、cwd、模型、权限模式和原生会话注册表，再以 Claude stream-json 进程替换工作程序。模型、权限、Skill、批准和中断控制使用该进程。SSH 丢失时，不确定写入保持未确认；Bridge 不自动重放。

上传 ID 仍受 Bridge 台账作用域限制。远程发送时，经过验证的字节通过选定 SSH 别名传输到该远程 Claude 配置下的私有不可变文件。只有生成的远程路径进入模型消息。绝不把本地网关上传路径当成远程文件引用。后续操作要求远程配置和 SSH 别名保持不变。不向主机复制本地 Claude 设置或凭据。

## 原生进程身份

只读检查已安装 Claude Code 2.1.287，发现注册表 `procStart` 由 `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` 生成。Linux 的 `pidDomain` 为 `darwin:<machine-id>:<pid namespace link>`，macOS 为 `darwin`。工作程序在恢复前检查 PID、进程启动时间和域，证据缺失或不匹配时拒绝。对现有限定 Linux SSH 主机的只读探测确认，`/etc/machine-id`、`/proc/self/ns/pid` 及 UTC/C `ps` 可用且格式符合预期。这不构成原生 Linux Claude 轮次测试。

## 备选方案

原记录明确禁止将本地网关上传路径作为远程文件引用，也不把本地 Claude 设置或凭据复制到目标；远程主机自己的配置和经过传输的远程文件才是执行依据。记录没有提供其他远程运行架构的比较过程，不补写未记录的候选或否决理由。

## 影响

手机可沿选定 SSH 主机继续其原生会话，并保留主机、配置与会话身份边界。文件发送增加目标端私有文件传输；后续操作要求主机别名和配置不变。直接 SSH 子进程的生命周期依赖网关连接，断线后的不确定写入不能自动恢复或重放，用户需先检查历史再显式继续。下述回环验收不替代任意 Linux 主机或真实付费模型验收。

## 验证与限制

定向 Python 测试覆盖独立配置/历史、不可变上传、主机/配置 ID、PID 复用/域不匹配、部分主机失败、后台列表延迟、账号变化及未知 SSH 写入不重放。原生验收夹具以已安装 Claude Code 2.1.287 和临时配置创建原始保存会话，再通过一次性 OpenSSH 与 localhost API 模拟服务验证恢复、原 cwd/model/permission/auth、原生模型/权限控制、Skill 展开、远程文件字节/路径、批准、中断，以及一次写入后 SSH 流被切断时报告未知。原生用户消息重放 UUID 在验收前确认发送。由于本地测试 sshd 的 `SetEnv` 未传播临时 `CLAUDE_CONFIG_DIR`，夹具显式注入它。Node 测试覆盖既有上传和会话 UI。未使用付费 Claude 请求、生产远程配置写入或原生 Linux Claude 执行。直接 SSH 子进程生命周期跟随当前网关连接；连接丢失后，用户必须检查历史并显式恢复，不自动重试。
