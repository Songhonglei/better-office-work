# 本地日记

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

在 Chrome 或 Edge 打开 http://127.0.0.1:8000，选择放日记的本地目录。支持 Markdown 编辑、预览、搜索、自动保存和本地图片附件。渲染库随项目分发。

本地日记无需配置。AI 排版是可选功能，配置参考 `config.json.example`。带凭据的 `config.json` 只放在私有本地环境。云端同步需自己配置目标及权限。Notion 每次追加一份日记内容，保留目标页面原有内容。
