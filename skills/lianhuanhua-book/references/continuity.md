# 逐页跟进

从分镜建立可看见、可复查的要求。挑出会跨页漂移的衣帽、道具和地点，以及单页容易画错的手、视线、天气或受力位置。每条只写本册真正需要检查的内容。

## 分镜记录

- 书级 `continuity` 用 ID 标识规则。`{"rule":"一把弯竹柄油纸伞。","pages":[0,2,3,10]}` 会自动加入这四页的提示和检查。少量动态场景也可用字符串规则，由内页 `track` 声明适用页。
- 页级 `track` 可补充该页表现，例如 `{"umbrella":"伞钩抵在左门框，伞尖落在湿青石。"}`。页级 `checks` 写只在本页出现的问题，例如 `{"gaze":"人物从侧背面看向书柜里的书。"}`。
- 书级 `samples` 是先出图评估的页码列表。优先选择能够覆盖道具、动作及场景逻辑的页；按故事实际规模选择数量。
- 新模板已启用 `continuity`。每页至少检查 `scene` 和 `composition`。旧故事可以沿用原审核方式；有针对性的续作可先在副本试用。添加或修改共享规则会刷新适用页的指纹，其余页仍按原检查结果使用。旧稿可重新导入同一原图并按新规则复审，画面确实已有正确细节时无需重新生成。

## 看图与记录

```bash
python pipeline/progress.py --slug <slug> checklist --page 2
python pipeline/progress.py --slug <slug> checklist --page 2 --version <id>
```

检查清单展示规则、已选版本、候选和在途任务。逐项看原图及邻页，写可辨认的证据。审核文件的键与 `rules` 完全一致，值使用以下格式：

```json
{
  "scene": {"status": "pass", "note": "阿绫撑伞护书，视线在巷中。"},
  "composition": {"status": "pass", "note": "店门与湿石巷的边界清楚，色调沿用封面。"},
  "umbrella": {"status": "pass", "note": "手下露出一个连续的弯竹钩，和封面同形。"}
}
```

```bash
python pipeline/progress.py --slug <slug> approve --page 2 --note "与分镜、邻页一致" --checks-file review-02.json
python pipeline/progress.py --slug <slug> approve --page 2 --version <candidate> --select --note "局部对照已通过" --checks-file review-02.json
```

审核不过时，用 `reject --page ... --note ... --checks-file ...` 记录已看到的 `pass`、`fail` 或 `unverified`；可留出尚未检查的项。成书验收读取当前选用版本，要求所有适用项通过。程序负责检查跟进记录与原图版本的对应，画面内容由实际看图判定。

## 修订与续作

用户指出跨页细节时，先把要求写回共用规则，再找出全部涉及页。稳定的构图上先标局部蒙版，使用 `comfyui_edit.py --check <id>` 把对应规则带入局部修订。画面关系需要整体调整时生成整页候选。模型输出只形成候选，检查通过后才选择。改图后重建成品，浏览器点开修订页并前后翻一页。 [ComfyUI 参数](comfyui.md)

旁白扩写走图文复核。若现有原图仍符合新文案，用原始生成文件建立新上下文版本，确认选用图片哈希一致后再审旧图。排版调整单独复测正文相对插图的位置、自然折行与窄屏阅读。
