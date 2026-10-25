# WSL 账号与接入 / WSL accounts and access

## 中文

**实验性功能**：当前仅支持可安全识别和交接的配置，不保证所有账号、提供商或 CLI 版本兼容。尚未完成真实多账号全流程验证；配置保存、切换及模型列表不代表上游认证或实际任务验证通过。

Windows 本机与 WSL 中的 Codex、Claude Code 可以使用不同账号和 API。即使手动填入相同凭据，它们仍是独立配置，不会自动同步。每个 WSL 发行版、Linux 用户和配置目录分别管理；Codex 与 Claude Code 也分别管理。

先在 **应用管理** 中登记并启用对应 WSL 入口，再打开 **账号管理**，选择该 WSL 环境。查看不会启动已停止的发行版或 CLI，也不会调用模型。

- **网关桌面、已登录的 Web 和手机端**：添加 API 接入、编辑未使用的接入、重命名、删除未使用的接入、保存当前原生接入。也可以选择本机已保存的同类 API，显式导入到所选 WSL。导入只是保存，切换需要另行确认；本机账号不变。正在使用的接入只允许重命名；修改地址或密钥前先切换到其他接入。
- **免密访问**：只能查看环境和模型，不能新增、导入、修改、删除或切换账号。密钥写入后不会在账号列表中返回。
- **官方登录**：在原 WSL CLI 完成。网关不复制 Desktop 的官方登录或系统钥匙串。支持的文件配置可以保存为“原始 WSL 登录”，以后恢复。

切换需要单独确认，并即时检查所选 WSL 配置的任务、审批和操作记录。排队、运行中或结果未确认的操作会阻止切换；网关不会清空队列或重发消息。Claude Code 仅正常释放本网关创建的空闲执行器，其他终端仍在使用该配置时请先退出。Codex 的共享服务需要在全部空闲后正常重启，以重新载入地址和凭据；原终端连接可能需要重连。无法核验状态、进程身份不符或正常退出超时都会停止切换，不会强制杀进程。配置切换完成不代表 API 凭据已经通过上游认证，真实接入以原生登录或实际请求结果为准。

第一次切换会保存原配置快照，恢复时按原文件内容恢复。若原配置随后被其他工具修改，网关会停止覆盖并提示使用原工具处理。Magpie、组织管理、系统凭据、复杂 profile、自定义认证路由和共享目录等不支持安全切换的配置，仍由原工具管理。

**切换后继续旧聊天**：标准 Codex Responses API 接入会保留当前 provider 标识，成对更新地址与密钥；使用该标识的已有聊天仍使用原会话 ID、历史和目录，共享服务重启并核验后可继续使用新接入，无需新建聊天。其他 provider 标识的历史不会自动迁移。多个提供商共用认证、环境变量或额外认证配置仍会阻止切换。旧聊天的模型不会自动更改；新 API 不支持该模型时，请在聊天模型设置中选择兼容模型。Claude Code 的标准 API 切换同样保留原配置目录和历史，本网关的下一次显式操作重新加载新接入。明确切换后，网关保留原会话标识，并将其未发送草稿关联到新账号；已有新账号草稿不会被覆盖，未确认发送记录不会迁移或重发。外部工具修改账号不触发此草稿续接。

**查看上游模型**复用所选 API 的缓存，显示更新时间以及上游实际报告的名称和推理强度。未返回推理强度时显示“上游未提供”。手动刷新重新获取；缓存使用后按 12 小时安排后台更新，已停止或关闭的 WSL 不会被唤醒。不同网关、客户端、WSL 环境和 API 身份不共用模型缓存。原生官方登录的模型仍通过原 CLI 或已有聊天的模型设置查看。

导入地址保持原样：`localhost`、`127.0.0.1` 和 `::1` 指向所选 WSL 环境，不能据此假定它们能访问 Windows 上的服务。

## English

**Experimental:** only configurations that can be identified and handed off safely are supported. Account/provider/CLI compatibility is not guaranteed. Real multi-account end-to-end validation remains incomplete; saved configurations, successful switches and model lists do not establish upstream authentication or task execution.

Windows and WSL Codex or Claude Code can use different accounts and APIs. Matching credentials do not make their settings shared or synchronized. Each distribution, Linux user, configuration directory and client has its own account selection.

Register and enable the WSL entry in **App management**, then select that environment in **Account management**. Viewing accounts does not start a stopped distribution or CLI, or call a model.

- **Gateway desktop app and authenticated Web/mobile clients:** add API profiles, edit inactive profiles, rename or delete inactive profiles, and save the original native configuration. Explicitly import a saved API from the same local client into the selected WSL environment. Import saves a profile; switching requires a separate confirmation and leaves the Windows account unchanged. An active profile can only be renamed; switch away before editing its endpoint or key.
- **Passwordless access:** view environments and models only. Adding, importing, editing, deleting or switching accounts requires authentication. Saved keys are never returned in the account list.
- **Official sign-in:** complete it in the original WSL CLI. Desktop OAuth credentials and system keyrings are not copied. Supported file-based configurations can be saved and restored as the original WSL sign-in.

Switching requires explicit confirmation and fresh checks of tasks, approvals and operation records for the selected WSL configuration. Running or queued work and unconfirmed results block switching; no queue is cleared or message resent. Claude Code releases only idle executors created by this gateway; exit other terminals using the configuration first. Codex must normally restart its shared service after all work is idle, so that both endpoint and credentials reload. Original terminal connections may need to reconnect. Unverifiable state, changed process identity or a normal-exit timeout stops the switch without a forced kill. A completed configuration change does not verify the credentials with the upstream service; native sign-in or an actual request provides that verification.

The first switch saves an exact original-file snapshot. External edits stop a later overwrite or restore. Magpie, managed settings, system credentials, complex profiles, custom authentication routing and shared directories remain managed by their original tools when safe switching is unavailable.

**Continue existing chats after switching:** a standard Codex Responses API profile keeps the selected provider ID and updates its endpoint and key together. Chats using that provider retain their thread ID, history and directory; continue through the new access profile after the shared service has restarted and been checked, without creating another chat. History tied to other provider IDs is not automatically migrated. Multiple providers sharing authentication, environment overrides or additional authentication settings still block switching. Existing chat models are unchanged; select a compatible model in chat settings if the new API does not support the old one. Standard Claude Code API switching likewise retains its configuration directory and history; the next explicit gateway operation loads the new profile. After an explicit switch, the gateway retains the original session ID and carries its unsent draft into the new account scope. Existing drafts in the destination scope are not overwritten, and unconfirmed sends are neither migrated nor resent. External account changes do not authorize this draft continuation.

**Upstream models** reuses the selected API's cache and shows its update time, model names and reported reasoning levels. Missing levels are shown as “Not reported by upstream.” Manual refresh fetches again. Using a cache schedules a background refresh after 12 hours; it never wakes a stopped or disabled WSL environment. Cache identities are isolated by gateway, client, environment and API profile. Native sign-in models remain available through the original CLI or existing chat model settings.

Imported URLs are unchanged: `localhost`, `127.0.0.1` and `::1` refer to the selected WSL environment, not necessarily a Windows service.
