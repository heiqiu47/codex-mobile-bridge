# 回复中的审查与引用

Web 和手机 App 共用回复渲染与编辑区。Codex 的桌面、CLI、SSH 和 WSL 接入，以及 Claude、DSH，均使用当前会话的账号与工作区范围。

## 审查意见与后续操作

完整的 `::code-comment{…}` 标记会展示为审查卡片，包含优先级、标题、说明、文件和行号。代码块中的示例和尚未输出完整的标记仍显示源码。卡片提供复制批注源码入口。

文件已获当前会话授权时，点击文件位置可选择“查看代码位置”，在文件标签中查看并高亮对应代码。项目之外或不可访问的文件只显示位置文字，不扩大文件访问范围。

`:codex-followup[…]` 显示为操作按钮。点击后，提示内容追加到当前编辑区；已有输入和引用保留。检查、修改内容后，仍需点击发送。

`codex://review` 链接保留完整目标，可复制链接或在 Codex Desktop 打开。链接包含可识别的 GitHub PR 时，同时提供 PR 网页入口；Desktop 专属审查状态不会被当作普通文件读取。

## 选中片段引用

在回复中用鼠标或手机长按选中文字，再点编辑区上方的“引用所选文字”。引用片段可展开查看、单独移除，已有文字不被覆盖。手机的系统复制和选择菜单保持可用。

引用和输入文字一起保存在当前设备的草稿中，按电脑、账号、应用、主机和会话区分。返回列表或切换会话后，再次进入会恢复对应草稿。引用只在主动发送时转换为普通引用文本；选择或添加引用不会发起模型请求。

Mermaid 图表继续支持预览、源码复制和全屏缩放。

---

# Reviews and quotes in replies

The web client and mobile apps share reply rendering and the composer. Codex Desktop, CLI, SSH and WSL connections, Claude and DSH retain the current chat's account and workspace scope.

Complete `::code-comment{…}` directives appear as review cards with priority, title, explanation, file and line numbers. Code examples and incomplete directives remain readable source. Review source can be copied.

Authorized file links offer **View code location** in a file tab. Files outside the chat's permitted workspace remain plain location text. Review cards do not grant additional file access.

`:codex-followup[…]` actions append their prompt to the editable draft, preserving existing text and quotes. Sending remains a separate action.

`codex://review` links retain their full target for copying or opening in Codex Desktop. Recognized GitHub pull requests also offer a web link. Desktop-only review state is not exposed as an arbitrary file.

Select part of a reply and choose **Quote selected text** above the composer. Each quote can be expanded or removed. Native mobile selection and copy menus remain available. Quotes persist with the draft, scoped by gateway, account, application, host and chat. They are converted to ordinary quoted text only when you explicitly send.

Mermaid preview, source copying and full-screen zoom remain available.
