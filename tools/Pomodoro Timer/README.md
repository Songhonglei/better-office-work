# Pomodoro Timer · 星环番茄钟

一款沉浸式番茄钟：星空（暗色）/ 破晓（浅色）双主题、横向艺术椭圆进度环、Canvas 流水瀑布背景、可拖拽缩放、暂停打断追踪，以及完成时刻的星光彩蛋。

## 使用方式

| 形态 | 说明 |
|---|---|
| [GitHub Pages 在线版](https://songhonglei.github.io/better-office-work/) | 打开即用，无需安装 |
| `dist/番茄钟.app` | 原生 macOS 应用（深色/浅色主题均已适配），拷贝到「应用程序」即可 |
| `dist/index.html` | 单文件网页版，任意浏览器打开（Safari 可「添加到 Dock」成为独立窗口应用） |

## 功能

- ⏱ 专注 25 / 短休 5 / 长休 15 三种模式，椭圆环进度
- 🌗 双主题：暗色 = 闪烁星空 + 流星；浅色 = 破晓晨光 + 流云
- 🌊 椭圆下方动态瀑布背景（彩蛋时刻水帘逆流）
- ✋ 暂停 / 恢复，自动记录「被打断次数 / 被打断分钟」
- 🎆 完成时刻星光迸发 + 光环涟漪 + 椭圆脉冲
- 📏 拖拽右端手柄缩放椭圆（紧凑模式自动缩小字号），设置本地持久化

## 构建

```bash
./build.sh
```

产物输出到 `dist/`（standalone HTML + 番茄钟.app）。需要 macOS 与 Xcode Command Line Tools。

> 修改 `index.html`、`main.swift`、`Info.plist` 或 `build.sh` 并推送 main 后，GitHub Actions（`.github/workflows/pomodoro-build.yml`）会在 macOS 运行器上自动重建产物、同步 Pages 并回提交，无需手动构建。

## 源码结构

```
index.html   # 完整单文件应用（零依赖，无外部资源）
main.swift   # macOS 壳（WKWebView）
Info.plist   # 应用清单
build.sh     # 构建脚本：注入 standalone 补丁 + 绘制图标 + 编译 App
icon.png     # 应用图标源图（构建时重新生成 icns）
dist/        # 构建产物
```

> 本工具同时作为 Kimi Work 看板 Widget 运行；看板内运行时由宿主负责圆角裁剪，standalone 补丁（`viewport-fit=cover` + 全出血渲染）仅注入到导出的 `dist/` 产物，消除独立窗口下的圆角毛边。
