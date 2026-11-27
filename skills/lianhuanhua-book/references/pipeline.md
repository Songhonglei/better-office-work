# 流水线与命令

## 目录约定

```
<项目根>/
  stories/<slug>.json          分镜与文案（一本书一个）
  stories/_series.json         系列配置：title / subtitle / note / footer / planned
  styles/<style>.txt           风格后缀（唯一真源，勿复制到别处）
  styles/style-note.md         实测经验
  assets/images/<slug>/
    _raw/00-封面.png …         原始出图，文件名「序号-页名.png」，序号两位
    cast/*.png                 人物定妆照
    _drafts/                   过程版本（superseded/ 存废弃版）
    prompts/NN-页名.txt         拼好的 prompt（make_prompts 生成，可以直接喂模型）
    000.jpg …                  成品（post_process 生成）
    配图说明.md                 每页画面与来源版本
  pipeline/                    五个脚本
  templates/                   index.html / read.html / style.css / reader.js
  site/                        构建产物，可直接部署
  serve.sh                     本地预览
```

`assets/images/<slug>/` 下 `_raw` 的序号决定成品编号：`05-晚课.png` → `005.jpg`。封面固定 `00-封面.png`，构建时不裁底。

## 五个脚本

```bash
# 1. 拼 prompt：把 story.json 的 scene + 人物锚点 + 朝代约束 + 负面 + 风格后缀拼成整段
python3 pipeline/make_prompts.py --slug <slug>          # 全部
python3 pipeline/make_prompts.py --slug <slug> --page 5 # 单页

# 2. 裁水印 + 转 Web JPEG（封面 00 不裁底，其余裁底部 80px）
python3 pipeline/post_process.py --slug <slug>
python3 pipeline/post_process.py --slug <slug> --cut 90 --quality 80

# 3. 校验：页数、尺寸、体积
python3 pipeline/verify.py --slug <slug>

# 4. 建站：复制图片、生成缩略图、写阅读页与书架
python3 pipeline/build_site.py
python3 pipeline/build_site.py --clean

# 5. 本地预览（Cache-Control: no-cache，改完刷新即见）
./serve.sh 8788
```

依赖：`Pillow`。本机解释器：`~/.workbuddy/binaries/python/envs/pillow/bin/python`。

## 出图这一段的实际顺序

1. `make_prompts.py` 生成 `prompts/`（先看一遍文案与场景，改 `stories/*.json` 后重跑）
2. **定妆照**：每个主要角色一张白底正面半身，存 `cast/`。配角可选，但同框 ≥2 人时强烈建议
3. 逐页出图：`image1` = 主角定妆照，`image2` = 配角定妆照或从既有页裁的衣着参考
4. 出图文件落到 `_raw/`，按「序号-页名.png」改名（序号两位）
5. `post_process.py` → `verify.py` → `build_site.py`
6. 每页目视三查：水印、脚/衣摆、同框角色是否撞脸撞衫

## 尺寸与体积

| 项 | 值 |
|---|---|
| 生成尺寸 | 1536×1024 |
| 内页成品 | 1536×944（裁底部 80px 去水印） |
| 封面成品 | 1536×1024（不裁底，水印局部清除） |
| 压缩 | JPEG q82，单页目标 ≤450KB，超了降 q80 |

## 本地预览与发布

```bash
./serve.sh 8788
# → http://127.0.0.1:8788/
# → http://127.0.0.1:8788/read/<slug>/
```

发布静态站：把 `site/` 目录交给「发布为应用」（`workbuddy_sites_deploy`，`language: "static"`）。
改图后要重新 `build_site.py` 再发布——`site/assets/` 是复制件，不是软链。

## 缓存

- 图片 URL 带指纹 `?v=<mtime>x<size>`，`build_site.py` 自动加
- CSS/JS 带 `?v=__VER__`（两文件大小之和）
- `serve.py` 发 `Cache-Control: no-cache`

改了前端却没反应，先怀疑缓存，再看指纹是否变了。
