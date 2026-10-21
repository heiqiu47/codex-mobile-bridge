# Webhook 通知（待发布）

Webhook 将现有通知以 HTTP POST JSON 发到你配置的服务。无需安装额外插件；Mac、Windows、Linux 网关使用相同配置，Web、Android 与 iOS 可通过直连网关的“第三方通知 → Webhook”管理。电脑网关中的入口是“消息通知 → Webhook”。此功能尚未包含在已发布的 v2.1.2 安装包中。

## 配置与测试

1. 填写接收服务的完整 HTTPS 地址。签名或密钥查询参数会原样保留；普通 HTTP 仅允许本机测试地址。
2. 在“高级设置”按服务要求填写请求头，例如 `{"Authorization":"Bearer YOUR_TOKEN"}`。请求头必须是 JSON 字符串键值对象。
3. 调整 JSON 正文模板，保存配置，再点击测试。保存不会发送通知；测试只发送已保存配置，不使用表单中未保存的修改。
4. 接收服务确认测试后，启用 Webhook 并保存。聊天提醒继续由全局和单会话通知设置控制，网关入口与安全通知沿用各自开关。

默认模板：

```json
{
  "event": "{{event}}",
  "title": "{{title}}",
  "body": "{{body}}",
  "session_name": "{{session_name}}",
  "url": "{{url}}"
}
```

仅 JSON **字符串值**中的 `{{字段名}}` 会被替换，支持嵌套对象和数组。字段名、表达式或脚本不会执行。中文、引号和换行会正确编码为 JSON；正文最多 64 KiB，模板最多 16 KiB。

| 字段 | 内容 |
| --- | --- |
| `event` | `task.completed`、`approval.required`、`gateway.started`、`gateway.address_changed`、`security.ip_blocked` 或 `test`；已开启的账号提醒使用 `account.*` |
| `event_id` | 供接收端去重的事件标识；同次事件重试时保持一致 |
| `title` / `body` | 现有通知标题与摘要，不包含完整聊天或模型回复 |
| `session_name` | 聊天名称；仅在开启“包含会话名称”时提供 |
| `url` | 对应聊天或当前网关的访问链接；无链接时为空 |
| `client` / `host` | 事件来源；不适用时为空 |
| `count` | 合并通知或事件计数，以字符串替换 |

## 已保存配置与投递

完整地址可能包含密钥，因此保存后只显示服务 origin，请求头内容不回传页面。地址或请求头留空会保留已保存值；使用对应清除选项删除。更换地址会清除旧请求头，需要重新填写，避免向新服务转发旧凭据。请将认证信息放在地址或请求头中，不要写进可回读的正文模板。

Webhook 默认关闭，复用既有通知策略、去重记录与失败重试。新增通道不会补发已完成的聊天历史，关闭通道或更换接收目标会取消原目标的待发送重试。被动通知不会启动、接管或切换聊天。

接收端 HTTP 2xx 只表示请求被接受，仍需在下游确认是否收到。超时可能发生在接收端已经处理之后，因此不能保证严格只发送一次；接收端可按 `event_id` 去重。请求不会跟随重定向。需要动态签名或非 JSON 协议的服务，仍需由你自己的适配服务转换。

## English

**Unreleased:** configure **Push alerts → Webhook** on Web/mobile, or **Notifications → Webhook** in the desktop gateway. Settings are shared across macOS, Windows and Linux; Android/iOS use the gateway's Web interface. Shared-relay configuration permissions are unchanged.

Set an HTTPS endpoint, optional JSON string-to-string headers and a JSON body template. Save before testing: a test uses saved settings only, and saving does not send anything. Enable the channel after confirming receipt. Existing global/per-chat, gateway-entry, security and account notification preferences remain in control.

Use `{{event}}`, `{{event_id}}`, `{{title}}`, `{{body}}`, `{{session_name}}`, `{{url}}`, `{{client}}`, `{{host}}` and `{{count}}` inside JSON string values. No scripts, expressions or key substitution are supported. Templates are limited to 16 KiB and rendered bodies to 64 KiB. Chat names require the existing title opt-in; full conversations and model replies are not included.

Saved endpoint credentials and headers are not returned to the UI. Blank inputs retain them; explicit clear controls remove them. Changing the endpoint clears old headers unless replacements are supplied. Keep credentials out of the readable body template. HTTPS is required except for loopback HTTP tests, and redirects are rejected.

Delivery reuses existing policies, deduplication and retries. It does not activate chats or replay completed history. HTTP 2xx confirms receiver acceptance, not downstream delivery; use the stable `event_id` to deduplicate retries after ambiguous timeouts. Dynamic signatures and non-JSON protocols require a separate adapter.
