# 微信公众号链接提取

Python 3.9 或更高版本。支持常见的 `/s/短码` 和 `/s?__biz=...` 两种文章链接，结果会去重，也会过滤其他域名。

```bash
python3 wechat_grabber.py --input messages.txt --output links.txt
python3 wechat_grabber.py --clipboard --output links.txt
```

剪贴板方式可在微信中先手动复制消息，再运行命令。macOS 上可用 `--wechat` 尝试读取文件传输助手，需打开微信并授予终端辅助功能权限，窗口行为随客户端版本而异。结果默认保存在本地 `output/`。
