# Agent Note: 复制原生会话身份

Status: implemented

## 问题

分享聊天需要原客户端身份，不应激活或克隆会话。

## 决策

无副作用的 BridgeSessionLinks.text 辅助函数返回带原生 SSH hostId 的 Codex 线程 URL，或原始 Harness Session ID。对不支持的 provider、无效 Codex ID 和 WSL 端点摘要返回 null。详情操作使用 BridgeClipboard，包括 HTTP 和手动复制回退。Codex 标题详情将复制操作放在执行主机旁，与消息管理和重命名分开。Harness 详情暴露原始原生 Session ID。

已知复制控件保留旧 `message-copy` 类：已发布 iOS/Android 注入脚本只接受 `message-copy` 或 `code-copy` 上的可信点击，且每次点击只消费一次。它们覆盖 `BridgeClipboard.copy`，因此只改新手机包无法修复既有 App。共享 `copyWithFeedback` 适配器调用该覆盖实现，只有浏览器确认，或旧原生钩子已请求文本、未报告失败并设置其确认成功标签后才提示。绝不把旧成功标签或静默拒绝的点击视为新确认。浏览器手动复制回退只在后续重试成功后提示。原生拒绝仍使用现有可见错误事件；令牌、frame、origin、前台和可信点击检查不变。

## 备选方案

把每个 Bridge host 都作为 Desktop hostId，会让 WSL 链接看似有效，实际端点却是内部注册表摘要，因此辅助函数拒绝该身份。启动 Desktop URL 会打开会话，而非复制。

## 影响

复制不激活或修改会话。原生 WSL Desktop 映射仍不支持。tests/session-links.test.cjs 验证原生身份和不支持情况；既有剪贴板测试覆盖复制回退。`tests/mobile-copy-compat.test.cjs` 在真实链接、文件/目录和 Harness 操作上，对 iOS/Android 执行不可变的 v2.1.5 共享注入夹具（与 v2.1.4 字节一致），包括原生拒绝和过期标签。按剪贴板、深度链接和会话身份检索活跃笔记，未发现既有链接决定；WSL 统一架构在身份边界上部分重叠，保持不变。
