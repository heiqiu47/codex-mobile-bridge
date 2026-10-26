# Agent Note: Bridge 会话置顶与原生归档

Status: implemented

## Problem

手机与网页需要共享会话置顶，并在原执行环境归档和恢复聊天。置顶不能改变 Codex 自身的偏好；原生归档可以关闭原生任务和后代，不能仅依据历史记录判断空闲。

## Decision

Live writer ownership, definite rejection receipts and reversible provider support are refined in [native archive feedback](../../implemented/bug-fix/2026-10-26-native-session-archive-feedback.md).

`SessionPins` 在 Bridge 私有 `session-pins.json` 按执行环境与线程保存置顶，Web 与手机使用同一 HTTP 写入口。环境键保留 host、配置目录以及 WSL user。它不使用原生 isPinned RPC，也不写 Codex 数据库或 rollout。最近模式在只读索引查询的 LIMIT/OFFSET 前按 Bridge 置顶、最近交互时间排序；网页跨主机合并后仍按同样优先级截取。置顶和非置顶各自按最近交互排列。列表快照键包含 recent/project 模式，异步读取在同一 generation 内捕获该模式，离线或部分主机结果不能复用另一模式的分页集合。项目模式不传置顶优先级，保持现有项目与最近排序；没有置顶时保留原列表结构。

归档和取消归档使用 `thread/archive`、`thread/unarchive`。App 路径复用原 home、原本机/SSH 运行时的短期官方连接；本机 CLI 使用同一原 daemon，WSL 使用已有 distribution/user/home 的共享服务，均不 resume、不创建模型轮次，也不修改 provider、auth、cwd。显式归档可以沿现有显式操作路径启动已安装的原 daemon，WSL 使用同一 ensure_daemon 归属核验；启动控制服务不恢复线程。原生方法不支持、控制面不可用或状态无法确认时拒绝操作。

只读索引枚举根线程完整后代，不沿用界面 128 条上限。App 原 owner 与后代用即时 IPC discovery/follow 快照确认 idle；timeout、断连、错 owner、错 revision、审批或运行中均阻止。CLI 仅在 Desktop IPC connect 本身的 FileNotFoundError 证明该端点不存在时继续检查原 daemon；元数据错误不能使用该例外。本机 App 关闭时，只有同样的端点缺失证据加上即时核验的原 GUI 可执行文件确实无进程，才允许使用短期原生元数据操作；仍运行、进程可见性不足、路径未知或远端 App 均不使用此例外。其他连接错误不能当作无 owner。原 daemon 的 metadata-only `thread/read` 必须报告 idle/notLoaded，Bridge 保留的请求、队列、Goal 和消息写入 unknown/pending/sent 记录仍阻止归档。WSL 沿用 entry 写门，检查相同子树的原生状态及未确认回执。

`ArchiveCommands` 在发送归档前持久化 unknown 意图，成功后读取原生索引确认 archived 值。连接丢失、进程重启或新请求 ID 均不自动重放未知写入；只有目标原生状态已经确认时才消解回执。能够证明原生写入尚未发出的本机预检失败清除该意图，允许修正状态后重新操作。原生拒绝或传输失败发生在已尝试写入后则保守保留未知状态。

列表长按、右键和 Shift+F10 打开置顶、复制链接、归档/取消归档菜单。复制按钮的忙碌状态交由共享剪贴板处理，避免菜单预先禁用按钮导致复制被跳过。复制使用 issue74 的 `BridgeSessionLinks` 与共享剪贴板；该 helper 不支持的原生环境不伪造链接。详情复制入口由 issue74 提供。共享中继只扩展这两个准确的 POST 路径，登录与 CSRF 保持不变。

## Existing-note audit

- [列表首屏](../../implemented/bug-fix/2026-10-16-codex-list-first-paint.md) 部分重叠：保留逐主机加载与完整成功分页边界，在原合并点增加最近模式优先级。
- [WSL 统一接入](../../implemented/architecture/2026-10-24-codex-wsl-unified.md) 与 [WSL 账号隔离](../../implemented/feature/2026-10-25-wsl-account-management.md) 部分重叠：保留原环境、写门与未知结果不重放，本篇只增加会话管理。
- archive/归档关键词其余命中为文件下载、更新包、历史路径或 Claude 列表，与本决定无关。没有可吸收或废弃的既有置顶提案。

## Alternatives considered

- 原生置顶可跨 Codex 客户端共享，但用户明确要求仅 Bridge 生效。
- 在网页排序当前页实现简单，但旧置顶聊天可能永远进不了首屏。
- 直接修改原生数据库可立即显示归档，但绕过原生生命周期及任务保护，不能采用。
- 对归档使用 resume 能取得更多运行时数据，但会改变原执行归属及控制状态。只读原 owner 与原 daemon 的快照可以核验状态，未知时拒绝。

## Testing

Python 合成数据验证共享环境隔离、150 条旧置顶在分页前排序、项目原顺序、完整后代、运行/审批/未知状态拦截、未知回执跨重启核对且不重放、本机 CLI 原 home/daemon、WSL 原运行时双向归档、HTTP 登录/CSRF 与中继边界。Node 夹具实际执行列表和菜单函数，验证最近/项目排序、原 host、复制 helper、长按取消与点击抑制、取消归档。

macOS 安装的 CLI 0.162.1 在工作树 `.tmp/native-home` 的隔离空会话完成官方协议及生产 `archive_thread` 两轮归档/取消归档，索引确认 archived，cwd/provider 保持一致；没有 turn/start 或模型调用。该运行时 schema 含两种归档方法，参数均为 threadId；includeTurns:true 在该安装版本返回 list_turns unsupported，因此安全检查使用当前运行状态的 metadata-only read。真实用户 App 会话、真实 WSL/SSH 环境及移动设备没有在本分支操作。

## Consequences

置顶只影响 Bridge 最近列表，并可覆盖分页之外的旧聊天。归档是真正原生状态变化，恢复仍属于原环境。额外成本是有置顶时的排序与归档前原 owner/子树核验；归档结果未知时，用户需先在原客户端核对。原生协议没有跨 owner 的原子条件归档；即时核验与实际写入之间仍有外部客户端并发启动的窗口，不能宣称具备原子任务锁。Bridge 自身操作继续由现有账号/entry 写门串行化。

先等待网关写入再重绘的置顶交互已由 [本地优先会话置顶](2026-10-26-local-first-session-pins.md) 取代。本地待同步覆盖层与期望偏好重试不放宽上述任何原生归档约束。

## Confirmed stop before archive follow-up

[Confirmed disconnect and archive](../feature/2026-10-27-confirmed-disconnect-archive.md) partially supersedes the idle-only rule for explicit `disconnect:true` requests. Legacy requests and restore remain idle-only; original-owner, version, writer and uncertain-receipt restrictions remain. Loaded Codex App and unverified provider/platform limits are not removed by that follow-up.
