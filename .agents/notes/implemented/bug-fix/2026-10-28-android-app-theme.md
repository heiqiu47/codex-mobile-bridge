# Agent Note: 安卓 App 的统一主题与聊天状态保留

Status: implemented

## 问题

安卓手机设置的主题仅改变独立设置窗口。电脑连接页使用固定浅色，聊天 WebView 的浏览器偏好又与原生设置独立，导致系统深色、手机设置和聊天外观相互不一致。

## 决策

沿用 `bridge/settingsTheme` 的 `system/light/dark` 三个值，作为 Android App 的主题选择；不迁移或重置账号、通知和其他显示设置。原生连接页复用已有深色调色板，浅色保留现有颜色和布局。默认 `system` 根据 Activity 当前的 `UI_MODE_NIGHT_MASK` 解析，显式浅色/深色覆盖系统。

MainActivity 在创建 WebView 时提供对应的主题 Context，在页面可见、加载完成、偏好改变及系统配置改变时注入选择值和解析后的深浅状态。共享聊天页面仅在收到原生状态时应用该值；普通浏览器和 iOS 保持原来的本地外观行为。聊天中改变主题或恢复默认通过 Android 专属脚本回传，复用当前 WebView、随机 token、同源和窗口焦点校验，只接收三个允许值。没有新增 JavascriptInterface。

主题改变保留 WebView、聊天草稿、页面导航与工作台；不重建 Activity 或刷新网页。`BridgePresentation` 更新现有主题变量与外观控件，不覆盖强调色、字号、密度或内容显示开关。系统深色状态由原生提供，不依赖仍存活的 WebView 是否重新计算了 `prefers-color-scheme`。

[Android 电脑选项菜单](../feature/2026-10-28-android-gateway-options-menu.md)复用该主题 Context 作为页面颜色读取失败时的回退；主题切换关闭旧菜单，继续保留现有 WebView。

### 既有记录核对

- [安卓后台通知](../feature/2026-10-27-android-background-notifications.md)部分重叠：该篇原来仅设置页采用主题的范围被本篇取代；通知、权限和页面复用决定仍有效，双方互链。
- [启动资源恢复](2026-10-22-startup-resource-recovery.md)互补：浏览器启动仍读取已有偏好，原生在内容进入可见阶段同步；不改变资源重试。
- [账号 UI 与平台范围](2026-10-26-account-ui-and-platform-scope.md)仅共享既有颜色变量，本轮不改变表单结构。
- 检索活跃笔记未发现其他被完全吸收或应废弃的主题方案。

## 备选方案

使用 Activity 重建可统一 Android 资源解析，但会销毁正在使用的 WebView；现有聊天需要保留草稿与工作台，因此使用原生颜色更新和页面事件同步。

仅让网页跟随 `prefers-color-scheme` 改动较少，但 WebView 的浅深状态受宿主 `isLightTheme` 影响，且无法表达手机设置显式覆盖系统的选择。原生解析状态并同步既有网页调色板，避免强制算法反色。

## 影响

电脑连接、列表、聊天和设置使用一致的主题选择。代价是维护原生到网页及网页到原生的有限主题事件契约。App 的统一选择会覆盖各网关此前不同的主题选项，其他显示偏好不变；浏览器独立存储不受影响。

Chrome/WebKit 宽窄屏回归验证四种原生选择组合、反向事件、强调色与草稿保留。Android 35 隔离模拟器的真实 Activity/WebView 验证首次深色进入、两个入口同步、系统实时切换和同一 WebView/草稿保留。真机验收仍由用户安装本轮 APK 后进行；不把模拟器结果当作所有厂商 Android 的保证。

后续 [iOS 全局主题与前台通知](../feature/2026-10-28-ios-theme-and-foreground-notifications.md) 将统一主题契约扩展到 iOS，并共用主题回传脚本；本篇原有平台范围保留为当时决定，其他安卓行为不变。


后续 [DSH 双路线接入](../feature/2026-10-29-dsh-mobile-and-plugin-compatibility.md) 增加独立 Mobile 浏览容器与插件协议校验；本篇 Bridge 路径的既有约束保持。
