# 从项目初始化到交付

## 目录

```text
stories/<slug>.json
styles/<style>.txt
assets/images/<slug>/
  cast/                        人物定妆照
  _raw/                        旧编号输入（00-封面.png 等）
  prompts/NN.txt               当前提示词
  progress.json                 页级状态、细节审核、选中版本、ComfyUI 任务与时间
  edit-inputs/<job-id>/        局部裁图、蒙版、输入工作流、模型输出
  versions/NNN/<version-id>/
    original.image             原始生成文件（原字节）
    render.jpg                 输出成品
    prompt.txt                 对应提示词
  NNN.jpg                      当前选中成品
pipeline/                      可复用脚本
templates/                     阅读器
site/                          仅构建产物
```

## 命令

```bash
python pipeline/make_prompts.py --slug my-book
python pipeline/make_prompts.py --slug my-book --page 3
python pipeline/post_process.py --slug my-book
python pipeline/progress.py --slug my-book import --page 3 --file candidate.png --backend imagegen
python pipeline/progress.py --slug my-book status
python pipeline/progress.py --slug my-book checklist --page 3
python pipeline/progress.py --slug my-book versions --page 3
python pipeline/progress.py --slug my-book reject --page 3 --note "视线错误"
python pipeline/progress.py --slug my-book rollback --page 3 --version VERSION
python pipeline/progress.py --slug my-book approve --page 3 --note "逐项核对通过" --checks-file review-03.json
python pipeline/verify.py --slug my-book --require-approved
python pipeline/build_site.py --require-approved
./serve.sh 8788
```

## 进度恢复

状态：missing、untracked、generating、pending、approved、rejected、stale、missing_or_changed。状态从指纹与选中图片实时判断，脚本退出和重启后保留记录。回退不会删除历史；过时版本仍是 stale。手工导入图片的提示词对应关系由导入者确认，历史输入来源记为 legacy-import。已有成品无版本记录时，重新导入原图、视觉审核后才能交付。原始图片保留，不在原文件上裁剪。

重复相同原始页码会在写入前报错。ComfyUI 每次推理一张图，等待时可以审完工页。用命令行操作进度和版本目录，保持系统写入协调。ComfyUI 超时后按任务 ID 续作，服务器明确不再运行该任务时才使用 `forget-job`。

## 验收、预览、发布

`verify.py` 严格校验分镜、图片尺寸、实际解码、体积、缺图、多余页、状态。省略 --require-approved 仅供程序预览，不能宣称视觉验收通过。建站前完整预检所有作品，并重新生成到独立目录，替换旧站，避免旧资源污染。构建失败保留上次成功站点。CSS/JS/图片 URL 使用内容哈希。

把 site/ 目录作为静态站部署，部署前使用 --require-approved，不自动发布。页面使用 0 封面、连续正文、深链接 #p12。网站不复制原图、定妆照、工作流或版本记录。

## 迁移

- 方图画册重制为原生横版时，保留旧项目，在新目录复制分镜及角色参考。把生成与交付设为同宽高比，启用 `output.fit: "strict"`，再跑横版样张和逐页审图。导入会检查旧方图的比例。

- v1.0 原始素材与图片目录可保留；重新从 raw 导入建立版本记录。
- 文件名 NN-页名.txt 改为 NN.txt，避免标题改名导致旧文件误用。
- --cut/--quality 参数迁移至 story.output，保证处理和验收共享同一规格。
- 页数含封面，12–20 页；允许分镜尚未完成时拼 prompt 和导入，但验收/建站要求整本完整。
- 所有生成物放项目目录；预览不用上传，正式发布须取得用户许可。
