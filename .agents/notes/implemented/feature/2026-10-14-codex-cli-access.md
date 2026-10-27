# Agent Note: Codex CLI 发现与显式原生接入

Status: implemented

模型、Skill、计划和本地 Goal 限制由 [CLI 会话控制](2026-10-14-cli-session-controls.md)替代；权限限制由 [CLI 权限切换](2026-10-14-cli-permission-switching.md)替代。编辑/分叉、重命名和旁支聊天限制仍有效。

下述按来源排除 Desktop 的规则由[现有执行归属路由](../bug-fix/2026-10-14-cli-existing-owner.md)部分替代：CLI 来源只描述起源，已活跃的 Desktop 归属进程会被复用，不创建替代运行时。

下述仅连接已加载线程的决定由[显式 CLI 恢复](2026-10-14-codex-cli-resume.md)替代。发现和写入隔离决定仍有效。

## 问题

会话发现仅接受桌面 originator。用户可见的终端聊天具有 `originator=codex-tui`、`source=vscode`，却被排除。SSH 发现还遗漏了未被特定项目成员字段引用的已保存受管主机。仅扩大发现范围会让 CLI 来源聊天经过 Desktop 激活，可能改变执行归属。

## 决策

将保存历史发现与执行分开。SessionStore 接受已知 CLI originator 和旧来源元数据，仍排除内部子智能体。列表/详情/通知发现使用同一来源规则。AppHosts 列出已配置受管 SSH 主机；Desktop 关闭检查保留独立的仅 Desktop 主机集合。远程历史和 CLI 代理使用目标用户登录 shell，使 CODEX_HOME 选择遵循该环境。

CLI 来源读取不跟随 Desktop，也不恢复原生任务。显式连接以官方 `codex app-server proxy` 为字节传输，并对既有控制套接字执行 WebSocket 初始化，绝不启动替代守护进程。加入和操作前检查线程已加载，写入前再次校验 provider/cwd。原运行时保留认证/配置。同 ID 的 Desktop 快照不能接管 CLI 来源写入。恢复的排队提交必须在附加前加载权威来源元数据。

适配器将原生轮次和请求映射为既有 UI 契约。支持发送、排队、引导、中断、命令/文件/权限批准、输入问题和受支持的 MCP 信息请求。Desktop 专属配置、目标、编辑/分叉、重命名、Skills 及旁支聊天既被服务拒绝，也由 UI 限制。旧协议格式缺少 `access` 时保留 Desktop 展示兼容。

结果未知的写入失败不重放。批准 ID 在写入前被占用，结果未知后隔离至断开连接；再次点击不能重发响应。关闭查看器或网关只关闭代理，不关闭守护进程或原生任务。已认证诊断路由只导出汇总来源/读取状态，不含正文、标题、路径、主机别名、线程 ID 或凭据。

## 备选方案

本地已批准路线图还涵盖 Claude Code 和 IDE 专属接入。本实现仅覆盖 Codex CLI 和 SSH 发现，不把更大路线图标记为完成。将全部 CLI 历史加载进新 app-server，或以 Desktop 回退，会改变执行归属，因此被否决。仅做历史发现又不足以满足已接受的 CLI 交互范围。

## 影响

官方参考：https://learn.chatgpt.com/docs/app-server。Context7 因配额不可用，因而使用当前官方文档及已安装 0.162.1 帮助/协议。`proxy` 是原始 WebSocket 传输，不是逐行 JSON。`thread/read` 为被动读取；仅在显式连接和已加载检查后，通过 `thread/resume` 加入。

上游 API 没有原子的仅已加载恢复。线程若在校验与恢复之间卸载，同一现有守护进程可能冷加载它。代码和用户文档明确说明此限制，不将其描述为严格的失败即拒绝归属保证。订阅前产生的待批准事项受上游重放行为约束；不支持的请求留给原 CLI。Windows/Linux 和任意远程环境需在本次 macOS 运行之外做原生测试。

定向测试覆盖来源/schema 回退、严格 SSH 标记、WebSocket 消息定界/断开、原生映射及响应身份、被动服务/API 接入、恢复队列来源、能力限制、净化诊断和禁止重放。真实隔离 CLI 0.162.1 TUI 在 provider/model/cwd 不变时验证发送/流式输出/幂等。真实浏览器操作验证显式连接、发送、中断和诊断下载。用户提供的既有线程只读访问。测试项目的信任在隔离 CODEX_HOME 中得到明确授权；日常 CLI 信任配置未修改。最终回归/构建范围见 VERIFICATION.md。
