# Agent Note: 工作区菜单复制目标绝对路径

Status: implemented

## Problem

目录列表只携带相对路径，浏览器无法可靠判断 SSH、WSL 和 Windows 目标的绝对路径格式。

## Decision

现有 info 操作在目标执行 Workspace 边界检查后返回 absolutePath；文件和目录沿用同一无链接访问规则。菜单点击复用 BridgeClipboard 的异步用户手势、HTTP 选择复制和手动复制退化。下载链接及其行为保持原有实现。返回的绝对路径仅在展示层去除标准 Windows 扩展前缀：`\\?\D:\...` 显示为 `D:\...`，`\\?\UNC\server\share` 显示为普通 UNC；普通 UNC 和设备路径保持原样。底层验证、打开和链接检查继续使用原生规范路径，不把展示字符串回传给文件访问。已发布移动 App 通过已知复制按钮的旧 `message-copy` 标记复用现有可信点击桥，实际确认后显示成功提示。

## Existing-note audit

检索活跃文件预览和源码笔记，源码显示决定只部分相关，没有路径复制契约；保留其独立用途。

## Alternatives considered

- 浏览器拼接 cwd：无需请求，但网关操作系统不能代表目标系统，且无法重新验证边界。
- 新增路径 API：职责明确，但现有受验证 info 已提供所需元数据，无需扩大路由。

## Consequences

复制前会读取一次目标元数据；目标文件消失、链接或会话切换时失败，不返回猜测路径。目标执行模块继续独立支持本机、SSH、WSL 和其他客户端工作区。
