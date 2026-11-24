# HTML 转 macOS 屏保和壁纸

需要 macOS 和 Xcode Command Line Tools。屏保打包还需要 Python 3。

```bash
./scripts/build_saver.sh /path/to/index.html MySaver --build-only
./scripts/apply_wallpaper.sh /path/to/index.html --no-apply
./scripts/build_dynamic_wallpaper.sh /path/to/index.html MyWallpaper --no-apply
```

屏保会打包入口 HTML 同一层的 Web 资源。生成的 `.saver` 可在本机安装，去掉 `--build-only` 则会安装到用户屏保目录。

动态壁纸需要可执行的 [wallpapper](https://github.com/mczachurski/wallpapper)。安装到 PATH 或用 `WALLPAPPER` 指定路径。页面可以读取 `window.__FORCE_HOUR__`，分别呈现凌晨、清晨、正午和傍晚的画面。壁纸命令保留 `--no-apply` 即只生成文件。
