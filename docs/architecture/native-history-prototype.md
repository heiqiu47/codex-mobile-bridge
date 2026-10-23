# 原生历史分页只读原型（2026-10-23）

状态：本地实验，不接入正式或 Test 网关，不是已经交付的跨平台功能。

分支 `prototype/native-history-pagination`，基于 `fbc291e`。只读探测脚本位于
`scripts/prototypes/`，没有修改网关的连接、发送、审批、认证或配置代码。

## 结论

Codex 安装包的原生 `thread/turns/list` 和 `thread/items/list` 可以分页读取真实历史，
不必 resume 会话。A/B 的完整隔离数据副本验证了这一点。
但当前 Desktop 的原 owner 跟随 IPC 没有暴露这些方法，首次订阅仍会发送整个已加载状态。
因此本轮证明了分页收益，**没有打通“沿用原 Desktop 连接且首次实时订阅不收大快照”**。

不能把独立原生读取进程的成功当成复用了原运行实例，也不能丢弃初始快照后直接应用
依赖该快照版本及位置的增量补丁。两者都会掩盖连接或状态一致性问题。

## A/B 实测

A/B 对应用户指定的两个长会话。完整 ID 与测量原始记录仅保存在本机 `.tmp`，
不把聊天内容、账户材料或历史副本加入 Git。

| 测量 | A | B |
| --- | ---: | ---: |
| 原 owner 首次订阅的 JSON 快照 | 1,520,151 B | 93,235,282 B |
| 订阅到快照解码完成 | 26.8 ms | 2,128.2 ms |
| 原 owner 接受 `thread/turns/list` | 否，`no-client-found` | 否，`no-client-found` |
| 原 owner 接受 `thread/items/list` | 否，`no-client-found` | 否，`no-client-found` |
| 隔离原生读取：最近 20 项响应 | 39,944 B | 58,231 B |
| 隔离原生读取：最近 20 项 RPC | 0.90 ms | 4.18 ms |
| 隔离原生读取：再往前 20 项响应 | 29,509 B | 71,623 B |

`no-client-found` 在这里表示该方法没有可处理的 IPC 接收端，不表示会话不存在：
同一原 owner 的发现、订阅和快照读取均成功，前后 owner 身份一致。

时间边界：

- IPC 测量发生在本机 Unix socket，包含从订阅到 Python 解码完成的时间。
  它不是手机公网的页面加载或渲染时间。
- 原生分页测量使用安装版本 `codex-cli 0.163.0-alpha.11`，在独立 stdio 读取进程中运行。
  上表取包含启动计时的最后一轮，先 B 后 A；均不代表磁盘冷缓存。
- 该独立进程初始化耗时 111.8 ms；B 的元信息、两条 turn 头和最近 20 项合计 135.1 ms。
  加初始化约 247 ms，不能把单次 4.18 ms 报成首屏总耗时。A 复用了该进程。
- 快照是整个已加载状态，分页是最近 20 个 item；两者有意包含不同数量的内容。
  B 的单页字节数约为快照的 0.063%，但不是完整历史读取速度提升的倍数。
- 两页没有重复 item，均有继续向前的游标；原生 `thread/loaded/list` 前后为空。

### 数据副本与失败实验

最初只复制 rollout 的试验不成立：A 返回空页，B 报 lineage 缺失。这不是分页能力的
有效结论。补齐 A/B 专属的 `state_5.sqlite`、`thread_history_1.sqlite` 行及 B 的历史来源
rollout 后，真实分页成功。副本共包含 159 个 turn、23,810 个 item 和三个相关 rollout。

原数据库以只读方式打开；副本使用独立 inode，路径改写仅发生在副本内。没有复制
`auth.json` 或原 `config.toml`，读取进程不继承 API key / provider 环境覆盖。
临时进程在读完后退出，历史数据副本在验收结束后清除，仅保留无正文的测量记录。
该复制方式只是隔离验证，不适合直接作为产品每次打开会话的读取方案。

## 原 Desktop 连接为什么还会有大快照

核对本机安装包中跟随处理器的行为：

1. 首次 `thread-stream-following-changed(following=true)` 会发送 `conversationState`。
   对已经订阅的客户端重复发送 follow，也会再发送快照。
2. `sendConversationSnapshot` 直接取整个已加载会话，没有历史窗口或游标参数。
3. `thread-follower-load-complete-history` 会取全历史并广播快照，不是分页入口。
4. 当前原生 app-server 使用独占 stdio；未发现可附着的原实例共享控制 socket。

原型没有启用新的监听端口、重启 Desktop、修改其程序文件，或启动替代会话来绕过这些条件。
没有调用 complete-history、resume、turn/start 或任何发送/审批方法。

要真正消除这段源头传输，需要原 owner 提供有界历史读取与独立的轻量实时状态，
或者已经存在且能确认属于原实例的只读原生通道。当前没有验证到这两个条件。
后续实现须继续保留原 owner/provider/auth/cwd，不能因读历史而恢复或接管会话。

## 其他客户端

| 接入 | 当前开销来源 | 原型与证据 | 尚未完成 |
| --- | --- | --- | --- |
| Codex CLI | `refresh()` 用 `thread/read(includeTurns=true)` | 复用同一套有界原生读取参数与测试；原生 binary 已在 A/B 副本上验证 | 在原 CLI daemon 上读取和实时合并；不能用新 runtime 替代原 daemon |
| Claude Desktop Code | 连接器只暴露完整 `getTranscript`；进度查询也是读完再截取 | 本机安装包确认有 `getTranscriptTail` / `getTranscriptPage`；原型按 tail → UUID 分页，契约测试通过 | 未修改或重载真实连接器；部分页会由 Claude 内部回退到全量读取，不能承诺源头磁盘开销有界 |
| Claude Desktop Cowork | 使用另一套 LocalAgentModeSessions transcript API | 明确保持 capability 不支持，不套用 Code 的接口 | 未验证可用原生分页方法 |
| DSH | 已有 `sessionController.page`，适配器却循环最多 100 页取完 | 原型每次只读一页，固定 `throughSeq`，游标隔离与前进检查通过 | 未安装插件或改变真实 DSH 连接；当前为既有接口契约和模拟测试 |
| Claude Code CLI | 整份读取 JSONL，当前路径还有 20 MB 限制 | 新只读原型反向分块读取，带字节预算、文件身份及变更检查；真实项目日志两页无重叠 | 分支、压缩、工具配对与活动状态语义合并；不是可直接替换产品完整时间线的原始事件列表 |

Claude Code CLI 的真实样本为本项目已有的 482,639 B 日志，只有 17 条符合条件的主线
user/assistant 事件。默认 20 条会读到文件开头，所以没有在这个样本上节省扫描。
显式每页 5 条时，首屏扫描 65,536 B、响应 7,225 B、耗时 0.38 ms；第二页扫描
393,216 B、响应 5,948 B、耗时 2.42 ms。其他事件可能稀疏地夹在消息之间，字节预算
与条数限制必须同时存在。原型超预算会显式失败，不回退到整文件读取。

所有原型的游标都绑定来源/会话；历史页不能作为发送、停止或审批的权威实时状态。
未来产品接入还须把电脑、账号/配置、客户端和原 runtime 身份纳入可信的缓存命名空间，
处理活动事件与历史页的去重及变更。当前原型使用调用者提供的 scope 验证隔离契约。

## 验证与保护范围

运行：

```sh
python3 -B -m unittest discover -s tests -p test_native_history_prototype.py -v
node --test tests/history-prototype.test.mjs
```

10 项 Python、4 项 Node 检查通过，包括禁止写入/恢复、拒绝全量回退、页边界、
中文 UTF-8、游标来源隔离、文件变化失效与不前进游标。实际 A/B 和 Claude Code 文件
读取发生在 macOS。未在 Windows、Linux、Android、iOS 运行这个新原型，也未构建安装包；
因此不把上一轮 Test 的跨平台验收算到本轮。

前后保护核对通过：正式版文件和进程、正式版与 8788 Test 配置、配对文件、认证身份、
原有效登录会话保留；Codex 账号配置及 A/B 的 provider、cwd、来源身份一致。
原型的所有应用请求都在只读白名单内，无新增模型调用、聊天发送或会话恢复。
当前正在进行的聊天会自然追加历史，不要求其日志字节数静止。

本轮没有修改原安装包、原数据、网关运行代码或手机端；没有推送 GitHub。
记录位于本机 `.tmp/native-history-prototype-20261023/`，不随代码提交。

官方 API 说明：[List thread turns](https://learn.chatgpt.com/docs/app-server#list-thread-turns)。
此文档描述 app-server 的能力，不等于 Desktop 跟随 IPC 已提供同名入口；本轮实测专门区分了两者。
