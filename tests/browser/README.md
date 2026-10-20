# 浏览器检查

本目录中的 `*.browser.js` 依赖真实 DOM、页面模块及隔离的网关夹具。它们由浏览器驱动加载并调用文件中声明的检查函数；Markdown 与公式脚本在加载后直接运行。各文件开头说明所需页面与前置状态。

仅使用合成会话和测试工作区。不要在真实用户会话中运行会发送消息、修改文件或操作 Git 的夹具。

这些脚本不会由 `npm run test:desktop` 执行。该命令只发现 `tests/` 和 `mobile/tests/` 下的 `*.test.js`、`*.test.cjs`、`*.test.mjs`；浏览器检查应单独记录实际执行与未执行情况。

<a id="mermaid-checks"></a>

## Mermaid 定向检查

- `mermaid.browser.js` 在加载 Markdown 与图表卡片模块的页面中直接运行，使用替代渲染器核验围栏识别、原文复制、流式更新、源码选择、缓存复用与清理；通过这些断言不等于真实 Mermaid 图像已生成。
- `mermaid-viewer.browser.js` 需调用并等待 `runMermaidViewerTests()`，以合成 SVG 检查全屏、缩放、拖动、源码切换与关闭。它不能替代真实渲染器或手机输入事件验收。
- 打包验收应从实际安装的网关加载生产资源，确认中文 SVG 的 `naturalWidth > 0`，再检查源码、全屏、流式及缓存。保留完整页面 DOM，避免破坏 App 异步初始化；CDP 驱动需等待主框架导航完成并选用其默认执行上下文。iOS 必须使用带生产导航策略的完整 App，并验证失败基线与修复后的实际图像。
- `tests/test_mermaid_renderer_security.py` 覆盖固定资源、鉴权、CSP 与中继路径；`python3 scripts/test-ios-mermaid-navigation.py` 在有 Xcode/Swift 的 macOS 上编译真实 URL 判断，验证直连及中继精确路径与导航限制。后者只验证导航规则，不代替完整 App 的显示检查。

已完成的本轮检查见 [Mermaid 跨平台验收](../../VERIFICATION.md#mermaid-preview-acceptance)。
