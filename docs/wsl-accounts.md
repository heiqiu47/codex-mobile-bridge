# WSL 账号与接入 / WSL accounts and access

## 中文

Windows 本机与 WSL 中的 Codex、Claude Code 可以使用不同账号和 API。即使手动填入相同凭据，它们仍是独立配置，不会自动同步。每个 WSL 发行版、Linux 用户和配置目录分别管理；Codex 与 Claude Code 也分别管理。

先在 **应用管理** 中登记并启用对应 WSL 入口，再打开 **账号管理**，选择该 WSL 环境。查看不会启动已停止的发行版或 CLI，也不会调用模型。

- **网关桌面端**：添加或编辑 API 接入、重命名、删除未使用的接入、保存当前原生接入。也可以选择本机已保存的同类 API，显式导入到所选 WSL。导入只是保存，切换需要另行确认；本机账号不变。
- **Web 和手机端**：查看所选环境、切换已保存接入、查看上游模型。新增或导入密钥请在网关桌面端完成。免密访问不允许切换账号。
- **官方登录**：在原 WSL CLI 完成。网关不复制 Desktop 的官方登录或系统钥匙串。支持的文件配置可以保存为“原始 WSL 登录”，以后恢复。

切换前请在原终端退出使用该配置的 CLI 或共享服务。仍运行的进程、该环境中排队或结果未确认的操作会阻止切换；网关不会替你结束进程、清空队列或重发消息。配置切换完成不代表 API 凭据已经通过上游认证，重新打开 CLI 后以原生登录结果为准。

第一次切换会保存原配置快照，恢复时按原文件内容恢复。若原配置随后被其他工具修改，网关会停止覆盖并提示使用原工具处理。Magpie、组织管理、系统凭据、复杂 profile、自定义认证路由和共享目录等不支持安全切换的配置，仍由原工具管理。

**切换后继续旧聊天**：标准 Codex Responses API 接入会保留当前 provider 标识，成对更新地址与密钥；使用该标识的已有聊天仍使用原会话 ID、历史和目录，重新打开 CLI 后可继续使用新接入，无需新建聊天。其他 provider 标识的历史不会自动迁移。多个提供商共用认证、环境变量或额外认证配置仍会阻止切换。旧聊天的模型不会自动更改；新 API 不支持该模型时，请在聊天模型设置中选择兼容模型。Claude Code 的标准 API 切换同样保留原配置目录和历史，退出原进程后重新打开以加载新接入。切换不会重发消息或修改草稿。

**查看上游模型**复用所选 API 的缓存，显示更新时间以及上游实际报告的名称和推理强度。未返回推理强度时显示“上游未提供”。手动刷新重新获取；缓存使用后按 12 小时安排后台更新，已停止或关闭的 WSL 不会被唤醒。不同网关、客户端、WSL 环境和 API 身份不共用模型缓存。原生官方登录的模型仍通过原 CLI 或已有聊天的模型设置查看。

导入地址保持原样：`localhost`、`127.0.0.1` 和 `::1` 指向所选 WSL 环境，不能据此假定它们能访问 Windows 上的服务。

## English

Windows and WSL Codex or Claude Code can use different accounts and APIs. Matching credentials do not make their settings shared or synchronized. Each distribution, Linux user, configuration directory and client has its own account selection.

Register and enable the WSL entry in **App management**, then select that environment in **Account management**. Viewing accounts does not start a stopped distribution or CLI, or call a model.

- **Gateway desktop app:** add, edit, rename or delete saved API profiles and save the original native configuration. Explicitly import a saved API from the same local client into the selected WSL environment. Import saves a profile; switching requires a separate confirmation and leaves the Windows account unchanged.
- **Web and mobile:** view the environment, switch saved profiles and inspect upstream models. Manage secrets in the gateway desktop app. Passwordless access cannot switch accounts.
- **Official sign-in:** complete it in the original WSL CLI. Desktop OAuth credentials and system keyrings are not copied. Supported file-based configurations can be saved and restored as the original WSL sign-in.

Exit the CLI or shared service using that configuration before switching. Running clients, queued operations and attributable unconfirmed results block switching. The gateway does not terminate processes, clear queues or resend messages. A completed configuration change does not verify credentials with the upstream service; reopen the CLI and check its native sign-in status.

The first switch saves an exact original-file snapshot. External edits stop a later overwrite or restore. Magpie, managed settings, system credentials, complex profiles, custom authentication routing and shared directories remain managed by their original tools when safe switching is unavailable.

**Continue existing chats after switching:** a standard Codex Responses API profile keeps the selected provider ID and updates its endpoint and key together. Chats using that provider retain their thread ID, history and directory; reopen the CLI to continue through the new access profile without creating another chat. History tied to other provider IDs is not automatically migrated. Multiple providers sharing authentication, environment overrides or additional authentication settings still block switching. Existing chat models are unchanged; select a compatible model in chat settings if the new API does not support the old one. Standard Claude Code API switching likewise retains its configuration directory and history; exit and reopen the original process to load the new profile. Switching never resends messages or changes drafts.

**Upstream models** reuses the selected API's cache and shows its update time, model names and reported reasoning levels. Missing levels are shown as “Not reported by upstream.” Manual refresh fetches again. Using a cache schedules a background refresh after 12 hours; it never wakes a stopped or disabled WSL environment. Cache identities are isolated by gateway, client, environment and API profile. Native sign-in models remain available through the original CLI or existing chat model settings.

Imported URLs are unchanged: `localhost`, `127.0.0.1` and `::1` refer to the selected WSL environment, not necessarily a Windows service.
