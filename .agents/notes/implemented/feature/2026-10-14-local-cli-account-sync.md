# Agent Note: 可选的本地 CLI 账号同步

Status: implemented

## 问题

Codex Desktop 与本地 Codex CLI 共享配置主目录。即使用户未选择 CLI 同步，Desktop 切换仍修改 CLI 文件，而已运行的 CLI 守护进程可能保留旧设置。Claude Desktop 官方 Cookie 不是 Claude Code CLI 凭据；API 配置只有在核验保存的 Desktop 配置后才能复制。

## 决策

Desktop 切换请求可显式选择本地 CLI 同步。Codex 告知共享配置事实；选中同步时，在 Desktop 验证后单独验证 CLI 账号/provider/配置。CLI 失败保留已验证的 Desktop 切换，报告部分失败。未选 CLI 同步时，UI 说明共享配置已改变，但 CLI 运行时尚未验证。

Desktop 停止时，仅 CLI 的 Codex 切换使用现有账号准备与原生凭据快照，应用到共享主目录，通过新的原生账号/配置 RPC 验证，失败则恢复快照。Desktop 运行时使用既有停止/应用/重启事务。已加入 CLI 会话、待处理任务和存活 CLI 控制守护进程均阻止切换。辅助程序不终止外部守护进程，也不触碰 SSH 配置。

Claude Desktop 同步只接受当前生效、指纹匹配的已保存 API 配置。在 Desktop 成功后创建并选择受管 Claude Code 配置。原生 OAuth/Cookie 配置保持独立，只读选择。Claude Code API 设置使用文档中的基础 URL、认证和模型环境变量。验证不调用模型。

Web、手机和网关桌面界面中，本地 CLI 接入控件位于各 provider 的账号管理视图。Codex 和 Claude Code 各有固定 provider 面板。已保存 API 接入可显式查询或测试上游模型列表端点，使用私有保存凭据，但不选择该接入、不发送聊天请求。测试只确认模型列表端点连通和授权；端点不可用时，仍可手动填写模型 ID。

## 备选方案

原记录明确区分 Desktop 切换成功与 CLI 运行时已验证，不能以共享文件已更新代替 CLI 验证；Claude Desktop 官方 Cookie 也不能当作 CLI 凭据直接同步。这些边界来自本篇的问题和决策记录。除此之外，原记录未保留独立方案比较；后续本地 Codex 统一账号决定见文末互链，不能倒写成最初已作出的决定。

## 影响

Desktop 与 CLI 可以产生不同验证结果，因此保留部分成功反馈；已确认的 Desktop 切换不因 CLI 验证失败而被描述为全部失败。共享主目录仍可能已改变，未验证运行时必须明确标注。活动会话、任务及活跃或未知守护进程状态会阻止切换；真实登录与运行时重载能力仍以各平台已记录的验收范围为限。Claude 同步保持可选，Codex 的后续规则由文末链接说明。

## 验证

定向 Python 夹具覆盖 Codex 回滚、活跃守护进程阻止、受管 Claude API 设置、Desktop API 导入，以及 Desktop/CLI 独立结果。UI 夹具覆盖主动勾选框提交。隔离原生 Codex 验收配合回环模型服务，确认新 CLI 轮次使用所选模型和端点，并阻止外部连接尝试；该夹具未执行账号切换。未运行真实账号变更、付费模型调用、现有守护进程重载或 SSH 配置变更。

## 跨平台账号保护的后续调整

仅 CLI 切换向 Codex CLI 会话层询问原生守护进程是否仍可能运行。不确定状态会阻止切换，账号层不再假设使用 Unix 套接字。原生验证同时检查选定 API provider URL、既有 Codex 聊天使用的 `openai_base_url` 路由及账号类型。Claude Code API 验证使用与启动路径相同的受管 provider 环境，并在选择配置前检查 `auth status --json` 返回的配置目录。导入 Claude 目录时，在解析之前拒绝所提供路径为符号链接的情况。

跨平台账号夹具覆盖守护进程状态阻止、两条有效 Codex API 路由、Claude 报告的配置目录和符号链接导入拒绝。macOS 上已安装 Claude Code 2.1.287 对使用占位密钥的隔离临时配置分别返回 `authMethod=api_key` 和 `authMethod=oauth_token`；没有模型请求或真实账号变更。支持的环境键及 provider 路由覆盖已对照[官方 Claude Code 环境变量参考](https://code.claude.com/docs/en/env-vars)。仅这些 macOS 检查不能证明 Windows/Linux 行为；Linux Codex 验收如下。

在 Linux x86_64 服务器、Python 3.10.12、已安装 Codex CLI 0.160.0 上，`tests/acceptance/cli_sync_native.py` 从 `<test-root>/accounts` 运行通过，使用隔离 `CODEX_HOME`、两个独立回环 Responses API 服务及占位密钥。验证了原生 A 路由、注入 B 失败后恢复 A 文件并完成后续原生 A 轮次，以及成功切换 B 并完成原生 B 轮次。还通过已安装 CLI 的只读守护进程状态探测，阻止已加入 CLI 会话及临时 PID 材料产生的未知守护进程状态；本地模拟代理拒绝 25 次外部 CONNECT。未启动真实活跃守护进程、触碰日常账号目录、调用付费模型或验证 Claude Code 账号切换。已验证这些假 API 配置的 Linux 原生凭据行为及回滚；真实登录与活跃守护进程生命周期仍未测试。

Windows 10.0.19045 x64 上，已安装 Codex MSIX 包含版本 0.162.0-alpha.17.2 的 `app/resources/codex.exe`。SSH 会话可从 `WindowsApps` 读取但不能执行；按字节复制到 `<test-root>/accounts/codex.exe` 后无需安装即可运行。在 Python 3.11 下，以同一隔离夹具在该临时目录测试，原生 A/B 轮次到达各自回环端点，凭据占位值和模型匹配。注入 B 失败后恢复 A 并再次完成原生 A 轮次；已加入会话和未知守护进程保护阻止切换，23 次外部 CONNECT 被拒绝。这证明复制的原生二进制 app-server 路径及基于文件的 API 账号事务，不证明其属于受支持受管守护进程包，也不验证真实运行守护进程、桌面重启路径或真实凭据。

Windows Claude Code 2.1.168 的 `auth status --json` 省略 `configDirectory`，不同于 macOS/Ubuntu 2.1.287。选定临时 API 配置时，2.1.168 对相应假凭据报告 `api_key` 或 `oauth_token`；独立空临时配置报告 `loggedIn=false`、`authMethod=none`。账号验证器只有在第二次原生探测使用同一可执行文件及净化环境证明配置隔离后，才接受目录字段省略。目录字段存在时仍须精确匹配。回归拒绝空配置仍有环境登录、控制输出错误/超时、选定方法错误，以及存在但为 null 或不匹配的目录。

Ubuntu x86_64、Python 3.10.12 和限定的官方 Claude Code 2.1.287 二进制上，`tests/acceptance/claude_sync_native.py` 完全在 `<test-root>/accounts/` 下通过。原生 A/B 轮次到达独立回环端点，使用设置中的选定 x-api-key 或 bearer token 及默认模型，无 CLI 模型覆盖。注入 B 验证失败后精确恢复 A 设置并再次完成原生 A 轮次。原生切回恢复原设置，模拟的活跃网关持有 Claude 会话阻止预检。14 次外部 CONNECT 被拒绝。

将提交 `3c99462` 的原生 Windows 写入者保护整合到隔离源码后，同一夹具在 Windows 10.0.19045、Python 3.11、已安装 Claude Code 2.1.168 的 `<test-root>/accounts/claude` 下通过。原生 A/B 请求使用选定端点、假 x-api-key 或 bearer 凭据及默认模型；注入 B 失败恢复 A，并再次完成原生 A 轮次。已完成原生轮次的会话注册表不阻止后续切换，模拟活跃网关持有会话则阻止。13 次外部 CONNECT 被拒绝。Linux/Windows 运行均未改变日常配置或调用付费模型。该账号夹具未测试真实活跃外部写入者或真实凭据；平台保护有独立原生身份测试。

账号配置 JSON 和原生 Claude 认证输出显式以 UTF-8 读取，不受 Windows 系统代码页影响。旧版阴性对照探测保留同样编码，并要求原生退出码为 1 且 JSON 表示已退出登录。

[WSL 账号管理](2026-10-25-wsl-account-management.md)采用独立注册环境事务，不将原生本地账号同步扩展到 WSL，也不自动镜像 Windows 凭据。

Codex 主动选择同步的决定由[统一本地 Codex 账号](2026-10-26-unified-codex-accounts.md)替代。Claude 同步仍可选。
