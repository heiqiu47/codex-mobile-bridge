# Agent Note: 恢复 Claude CLI 时忽略合成事件的模型标记

Status: implemented

## 问题

Claude Code 可能保存 `message.model` 为 `<synthetic>` 的助手事件。该值不是可选模型。本地 CLI 适配器此前选择最后一个助手模型时未排除这一哨兵值。Windows 上安装的 npm `claude.cmd` 通过原始 `%*` 转发参数；`--model <synthetic>` 会被 CMD 解释为重定向，原生 CLI 在确认 `initialize` 前就退出。

## 决策

保存历史的模型选择现在跳过 `<synthetic>`。若更早存在真实助手模型，恢复时保留该模型。如果历史只有合成助手事件，恢复时省略 `--model`，由原 Claude 配置和项目设置选择原生默认值。原配置、cwd、权限模式、设置来源和写入者保护保持不变。结果不确定的恢复回执不自动重放。

## 备选方案

原记录对照的是旧的“直接选择最后一个助手模型”路径和当前跳过合成标记的路径。旧路径无需区分事件类型，但会将不可选的合成标记传给 CMD，产生下述已复现的初始化失败。记录未保留其他候选方案的比较过程，不据此补写额外选型历史。

## 影响

真实历史模型仍保留；只有合成事件时，将模型选择交还原配置和项目默认值。恢复因此依赖原生配置，而非由 Bridge 指定替代模型。原写入者、权限和不确定回执保护不变；下述无轮次恢复验收不等同于模型推理验收。

## 验证

原已关闭的 Windows 会话只有一个助手模型事件 `<synthetic>`，没有更早的真实模型。沿用原 `.cmd` 启动路径时，修改前无轮次恢复等待 `initialize` 达 30.000 秒，没有收到控制响应，启动器以代码 1 退出；隔离 stderr 符合 Windows CMD 语法错误类别。修改后，同一会话在 1.219 秒内返回 `initialize` 成功，恢复于 3.641 秒就绪。探测未发送用户或模型消息，并关闭了自己持有的进程；重新读取原生注册表确认没有存活写入者。保存账号、cwd 和权限预检通过。未重放任何已有未知回执。

单元回归覆盖真实模型之后出现合成事件，以及仅含合成事件时不强制 `--model`。`python -B -m unittest tests.test_claude_cli tests.test_claude_reconnect` 的 59 项测试通过；`git diff --check` 通过。

隔离的 Windows 元数据探测脚本为 `F:/cmb-package-20261014/.tmp/claude-reconnect-probe/probe.py`，同目录包含源码 ZIP `current-bridge.zip`。它导入 ZIP，而非已安装 Test 网关运行时，因此本身不能验证新安装包。现有已安装 Test 网关的 HTTP 验收入口是 `F:/cmb-package-20261014/windows_test_http.py`（`TestHTTP`、`base`、`data`）；安装后，经该网关执行无轮次原生恢复仍需要新的显式测试请求和写入者已关闭检查。

随后安装的 `a175fac` Windows Test 包通过了该 HTTP 验收：一次显式恢复在 3.828 秒内就绪，详情端点确认就绪，原 cwd、权限模式和网关设置保留。未发送模型消息。恢复后的空闲连接保持可用，供用户手动测试。
