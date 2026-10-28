# Agent Note: 网关会话 Cookie 按实例隔离

Status: implemented

## 问题

两个本地网关可以使用同一 IP 的不同端口，但浏览器和 WebView 的 Cookie 不按端口隔离。固定的 `codex_mobile_session` 名称会让后登录的网关覆盖前一个网关的登录状态。

## 决策

网关在自己的 `auth-sessions.json` 中持久保存随机 `cookieName`。它与每次启动变化的 `instanceId` 分离，也不随密码策略修改而变化。新登录只签发该名称；请求优先使用该名称，即使其值无效，也不回退到旧名称。只有旧 Cookie 的令牌仍在本机网关会话表中有效时才接受并通过下一次成功响应迁移。注销仅清除本机名称；另一个网关可能占有旧名称。

`/api/auth` 返回 `cookieName` 供原生客户端按保存的连接地址选择 Cookie。Android 和 iOS 在认证成功后记录名称；旧网关和路径隔离的中继仍使用旧名称。通知、下载、连接发现和移除流程沿用该地址的名称，不把进程临时 ID 当作持久身份。

## 备选方案

直接把随机 `instanceId` 放入 Cookie 名称能立即区分并发进程，但网关重启就要求手机重新配对，违反持久登录。按端口设置 Cookie 不可行，因为 Cookie 协议不隔离端口。

## 影响

同一主机的不同网关可以并存并保留各自登录；旧令牌在有效期内有条件迁移。新增公开的 Cookie 名称不是认证秘密。原生客户端必须维护按连接地址的名称映射，且真实设备的 Cookie 存储行为仍需平台构建验证。


后续 [DSH 双路线接入](../feature/2026-10-29-dsh-mobile-and-plugin-compatibility.md) 增加独立 Mobile 浏览容器与插件协议校验；本篇 Bridge 路径的既有约束保持。
