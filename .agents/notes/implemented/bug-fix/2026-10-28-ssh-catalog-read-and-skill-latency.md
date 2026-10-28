# Agent Note: SSH 目录读取与 Skill 等待

Status: implemented

## 问题

Issue #90 由本仓库用户 try2love 提交，来自本机 Codex App 的 SSH 接入；模型目录提示 SSH 读取失败，Skill 打开较慢。用户明确当前接入是可用于复测的真实环境，不应把隔离夹具当作全部验收。

隔离夹具复现三个独立问题：仅安装 App 管理运行时而无 PATH 安装时，目录读取错误选择不存在的 `.local/bin/codex`；模型与 Skill 网络请求共用锁；已有过期 Skill 列表等待同步强制刷新。真实 88server 同时有 PATH 与 standalone 运行时，缺失 PATH 的夹具不能直接解释本次故障。原实现使用任一路径，完整目录查询均在 `account/read` 等待；独立配置、模型列表与 Skill 读取为约 0.3–0.6 秒，认证模式查询约 0.32 秒且未返回令牌。早期把堆栈位置误判为 config/read，按生成源行号与分项请求更正为 account/read。

## 决策

复用 SSH 原生 CLI 已有的受管运行时定位规则，放入现有 Catalog 类供两处调用，保留远端 home、cwd、provider 与认证。SSH 短时目录辅助进程仅用原运行时的 `getAuthStatus` 区分认证模式，明确 `includeToken=false` 与 `refreshToken=false`，转换为目录选择和 Fast 能力所需的类型与 requiresOpenaiAuth；不读取完整工作区路由，不伪造身份。未知类型失败，API 接入仍只使用当前上游，失败不回退原生无关模型。本地目录及已加入 CLI 的环境核验路径保留原契约。模型与 Skill 使用各自请求锁；过期 Skill 先返回现有缓存，通过后台只读刷新更新结果，失败保留缓存。手动刷新与发送前 Skill 校验维持原契约。

与[SSH CLI 上游模型目录](../feature/2026-10-18-ssh-cli-model-catalog.md)部分重叠，只共享运行时选择，不改变守护进程环境核验；与[原有 CLI owner](2026-10-14-cli-existing-owner.md)互补，被动目录查询不恢复聊天、不执行消息或切换账号。没有取代既有身份边界的决定。

## 备选方案

只提高超时不会消除错误路径和共享锁；在网页隐藏失败提示会掩盖目录不可用，因此排除。新建独立运行时查找模块会增加远端打包资源，本次沿用现有 Catalog 文件，避免复制多份路径选择逻辑。

## 影响与验证

隔离运行时执行真实生成的 SSH 源码，模型和 Skill 均返回，确认完整流程无 account/read，Fast 能力继续核验；现有新旧受管布局、PATH 和 `.local/bin` 回退保留。慢模型不阻塞 Skill；过期列表在刷新完成前可读，失败保留列表。模型身份、原生 CLI、独立 SSH 源资源、Fast 与模块边界回归通过，共 147 项；其中 Fast 的 HTTP/Unix socket 七项首次被沙箱阻止，允许隔离监听后整组 15 项通过，未视为产品失败或跳过。真实 88server、原有 `/data2/sp/jev` 与 openai provider 读取 8 个模型，强制刷新约 5.69 秒、缓存 0.32 秒；132 项 Skill 强制刷新 1.00 秒、同实例缓存小于 0.01 秒。没有发送消息或修改远端源码/配置，仅沿用目录读取的原生缓存。证据在 `.tmp/issue90-20261028/`，不提交。

Mac Test 已编译、签名验证并覆盖安装，版本 `2.1.6-test.20261028.7ec401e3b574`；原登录、连接配置与草稿保留，正式版及原生客户端进程不变，370 个打包网页资源与源码一致。启动后 Codex、Claude、DSH 均在界面确认已连接，其中 Claude 沿用用户已批准的初始化流程恢复。通过现有局域网入口登录安装后的 Test，读取同一真实 SSH 会话目录并退出本次登录：8 个模型强制刷新 1.10 秒、缓存读取 0.36 秒，132 项 Skill 强制刷新 0.99 秒、缓存读取 0.02 秒。与此前源码辅助进程的冷读耗时分开记录；保留本机网页访问关闭设置，不将其 403 当作目录故障。安装与接口证据分别为上述目录下的 `install-result.json`、`installed-api-result.json`。

## 风险

首次无缓存的 Skill 扫描仍受原生运行时耗时影响。已有目录结果仅用于显示，不能替代发送时校验。首次模型强制刷新仍受原生目录加载耗时影响，不宣称所有查询均为亚秒。

协议依据：[原生认证模式处理](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/account_processor.rs)、[account/read 的工作区路由发现](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/account_processor/workspace_routing.rs)。文档说明与真实分项结果共同支持定位；不声称单凭当前主分支源码解释远端所有内部等待。
