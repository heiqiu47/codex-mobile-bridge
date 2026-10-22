# 浏览器检查

本目录中的 `*.browser.js` 依赖真实 DOM、页面模块及隔离的网关夹具。它们由浏览器驱动加载并调用文件中声明的检查函数；Markdown 与公式脚本在加载后直接运行。各文件开头说明所需页面与前置状态。

仅使用合成会话和测试工作区。不要在真实用户会话中运行会发送消息、修改文件或操作 Git 的夹具。

这些脚本不会由 `npm run test:desktop` 执行。该命令只发现 `tests/` 和 `mobile/tests/` 下的 `*.test.js`、`*.test.cjs`、`*.test.mjs`；浏览器检查应单独记录实际执行与未执行情况。

## 启动恢复检查

运行 `python3 -B tests/browser/bootstrap-fixture.py`，在一个测试标签页访问它打印的 loopback 地址。用 `?case=success` 等参数选择场景，完整清单见夹具文件头。夹具提供生产 Web 资源与合成认证，不连接真实网关；每次导航重置故障计数，不能多页同时操作。

等待当前页面的 `window.__startupTest.scenario` 与所选场景一致，并等待启动区域隐藏或进入 `data-state="failed"`。把 `/__checks.js` 作为外部脚本加载后，调用并等待 `runBootstrapBrowserChecks()`；仅加载该脚本不会执行断言。`bootstrap-missing` 场景需等待兜底提示可见；`pair-unknown` 使用 `#pair=synthetic-test-token`，约 30 秒后检查只提交了一次合成配对。正常场景还检查执行顺序、脚本不重复执行和原生 load 时刻的剪贴板定义，`fast` 与 `slow` 分别检查遮罩不闪现及延迟显示。

基础样式回归使用 `shell-once`、`shell-twice` 与 `shell-fatal`：分别让 `/style.css` 首次、前两次、始终返回 503，核验自动恢复与包含初始 link 在内最多三次加载的限制。失败样式可能没有 `sheet`，也可能保留一个读取 `cssRules` 时抛出 `SecurityError` 的对象；Node 用例覆盖后者，浏览器用例验证实际请求链。Chromium 可能对初始 link 发起额外 HTTP 请求，次数上限按实际插入的 link 计数，同时保留服务端请求数；缺少基础 CSS 时的无样式 HTML 兜底不计作样式遮罩闪现。

在浏览器中模拟 `prefers-reduced-motion: reduce`，分别打开 `?case=fast&motion=reduce`、`?case=slow&motion=reduce` 和 `?case=bootstrap-missing&motion=reduce`，运行同一检查函数；查询参数只验证浏览器设置已生效，不代替模拟设置。慢启动与脚本缺失时等待至少 650 ms 再检查，避免只因提示尚未到显示时间而失败。宽屏与 390 px 窄屏均应检查。启动提示只延迟改变可见性，不产生位移、缩放或渐变；减少动态效果不应使提示永久隐藏。

`external-script` 场景模拟 Cloudflare 注入的外部统计脚本，断言 CSP 确实阻止它且工作台仍成功加载。资源下载与执行分开后仍须验证脚本顺序、运行时错误和依赖失败屏障。

夹具资源响应使用 `no-store`，这些故障测试不证明生产缓存命中或真实 BFCache 冻结恢复。需要分别记录浏览器模拟弱网、手机 WebView 实机和生产缓存的验证范围。

<a id="mermaid-checks"></a>

## Mermaid 定向检查

- `mermaid.browser.js` 在加载 Markdown 与图表卡片模块的页面中直接运行，使用替代渲染器核验围栏识别、原文复制、流式更新、源码选择、缓存复用与清理；通过这些断言不等于真实 Mermaid 图像已生成。
- `mermaid-viewer.browser.js` 需调用并等待 `runMermaidViewerTests()`，以合成 SVG 检查全屏、缩放、拖动、源码切换与关闭。它不能替代真实渲染器或手机输入事件验收。
- 打包验收应从实际安装的网关加载生产资源，确认中文 SVG 的 `naturalWidth > 0`，再检查源码、全屏、流式及缓存。保留完整页面 DOM，避免破坏 App 异步初始化；CDP 驱动需等待主框架导航完成并选用其默认执行上下文。iOS 必须使用带生产导航策略的完整 App，并验证失败基线与修复后的实际图像。
- `tests/test_mermaid_renderer_security.py` 覆盖固定资源、鉴权、CSP 与中继路径；`python3 scripts/test-ios-mermaid-navigation.py` 在有 Xcode/Swift 的 macOS 上编译真实 URL 判断，验证直连及中继精确路径与导航限制。后者只验证导航规则，不代替完整 App 的显示检查。

已完成的本轮检查见 [Mermaid 跨平台验收](../../VERIFICATION.md#mermaid-preview-acceptance)。
