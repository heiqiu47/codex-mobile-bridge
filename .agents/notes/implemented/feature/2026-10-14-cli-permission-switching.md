# Agent Note: 已加入 CLI 聊天的权限切换

Status: implemented

## 问题

[CLI 会话控制](2026-10-14-cli-session-controls.md)仍不允许源自 CLI 的聊天修改权限。已加入的原生 CLI 守护进程接受逐线程权限更新，但现有 UI 使用更宽泛的 Desktop 配置能力作为门槛。打开该能力还会暴露重命名和无关操作。对于 SSH，网关电脑的桌面设置不能描述所选 CLI 运行时。

## 决策

CLI 聊天有活跃归属进程后，暴露独立的 `canChangePermissions` 能力。App 持有的聊天使用现有归属进程 IPC。已加入原生 CLI 的聊天从选定守护进程读取配置要求、配置档案和功能可用性，包括选定 SSH 主机。未知或受限选项保持禁用。完全访问仍要求既有显式确认标记。

原生适配器只通过 `thread/settings/update` 发送选定配置档案、批准策略和审核器。绝不修改 provider、认证、cwd 或全局配置。请求设置不会直接成为展示状态。有效 `thread/settings/updated` 通知更新状态，Bridge 仅在后续状态序列报告所请求模式后确认。附加时从 `thread/resume` 投影生效权限状态；断开和失效在重新连接前清除适配器状态。不支持的旧守护进程无法通过能力发现，未知写入不重放。原生 CLI 消息明确称为 CLI 运行时；Desktop 持有的权限消息保留既有措辞。

主权限对话框将选项和保存请求绑定到打开时的活跃运行时。聊天或运行时变化、连接断开会关闭对话框。可选请求字段 `expectedRuntime` 在会话操作锁内、写入设置前检查，防止延迟的原生对话框写入新附加的 Desktop 归属进程。旧客户端省略该字段时保留既有请求行为。

## 备选方案

启用 `canConfigure` 只需改一个门槛，但会暴露不支持的 CLI 重命名及其他 Desktop 控制。给原生及 SSH CLI 复用本地 Desktop 偏好文件，可能提供所选运行时禁止的模式。立即投影请求设置，会把 RPC 成功误认为权限生效证据，即使后续策略决定不同。

## 既有笔记审计

[CLI 会话控制](2026-10-14-cli-session-controls.md)只有权限限制部分被替代；模型、Skill、计划、Goal 和归属边界保留。更早的 [CLI 接入](2026-10-14-codex-cli-access.md)、[冷恢复](2026-10-14-codex-cli-resume.md)及[现有执行归属](../bug-fix/2026-10-14-cli-existing-owner.md)保留发现、生命周期和归属决定，权限限制由本决定替代。没有 proposed 或 rejected 笔记覆盖原生 CLI 权限切换。

## 影响

选定运行时和策略允许时，本地及 SSH 原生 CLI 聊天可切换 ask、auto-review 和 full-access。App 持有的 CLI 聊天保留 Desktop 归属校验。原生更新可能在生效设置事件到达前保持未确认；面板报告这一状态，不宣称成功。定向适配器、服务、能力和 UI 测试通过。基于套接字的 HTTP 夹具无法在该沙箱中绑定；真实守护进程和 SSH 行为需单独验收。

## 验证

`python -B -m unittest tests.test_codex_cli_session.CliSessionTests tests.test_cli_bridge_integration.CliBridgeTests` 的 61 项测试通过，包括重新连接状态和权限事件。`PYTHONPATH=tests:. python -B -m unittest test_linux_permissions.CapabilityTests test_linux_permissions.LinuxReviewerCompatibilityTests` 的 7 项策略测试通过。`node --test tests/cli-access-ui.test.cjs tests/linux-permissions-ui.test.cjs` 的 15 项 UI 检查通过，包括原生与 Desktop 措辞。笔记目录树、格式及归档校验通过。需绑定套接字的 HTTP 夹具无法在该沙箱运行。真实运行时及 SSH 验收与这些夹具检查分开。
