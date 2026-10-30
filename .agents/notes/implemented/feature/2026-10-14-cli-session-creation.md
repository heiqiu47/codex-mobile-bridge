# Agent Note: 从已知项目目录创建 Codex CLI 聊天

Status: implemented

## 问题

新聊天对话框只能从已保存 App 项目创建 Codex App 聊天。仅由 Codex CLI 使用的目录，例如既有终端项目，无法用于新建手机聊天。

## 决策

将 Codex App 和 Codex CLI 暴露为明确的聊天类型。CLI 目录选项来自选定本地或 SSH 主机上的已保存 CLI 来源聊天元数据；列出选项只读取元数据。CLI 创建请求以类型、主机、目录和请求 ID 为键。只有用户提交表单后才连接既有原生 CLI 守护进程，按选定 cwd 和 CLI 来源创建持久线程，再命名和读取线程。不启动轮次或打开桌面 App。原生 CLI 连接使用独立身份 `codex-mobile-bridge-cli`；网关重启后，该精确 originator 被分类为 CLI。已安装 0.162.1 守护进程接受 `threadSource: cli`，却持久化 `source: vscode`，因此发现需要 originator。既有 `codex-mobile-bridge` 行不归类为 CLI。运行时为选定 cwd 选择 provider 和认证。

## 验证

源码测试覆盖显式 `thread/start` 调用、已知目录选择、重复请求，以及保持不变的 App 创建。隔离 Codex CLI 0.162.1 回环夹具通过已认证 HTTP API 创建 CLI 聊天；重新读取存储确认 CLI 来源及选定 cwd/provider，并通过原生守护进程完成发送。夹具发出输出项事件后，保存记录包含用户和助手消息。原生实时 `thread/read` 夹具返回空项列表，因此已连接实时视图未展示助手项；该夹具限制不影响保存历史发现。

## 备选方案

每次新聊天都打开 App 可复用既有路径，但不能创建 CLI 持有聊天。任意自由输入目录会将项目选择扩大到已知配置之外。明确聊天类型与发现的 CLI 目录保留用户所选执行环境。

## 影响

省略 kind 时，旧桌面创建 API 仍兼容。CLI 创建结果未知时保留回执，不另建线程。真实 390px 英文 UI 验收完成 CLI 聊天创建、消息发送和回复展示，无横向溢出。
