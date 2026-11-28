#!/usr/bin/env python3
"""按 story.json 拼出每一页的完整出图 prompt，落到 prompts/NN.txt。

用法：
    python3 pipeline/make_prompts.py --slug liaozhai-laoshan-daoshi
    python3 pipeline/make_prompts.py --slug liaozhai-laoshan-daoshi --page 7

每页会先做一次「同框角色」体检：
  - 页面写了 `who`（角色名数组）→ 逐个校验是否在 cast 里，缺一个就报错退出；
  - 没写 `who` → 按 cast 名字在 scene 里做子串匹配，若匹配到的锚点少于 2 个、
    而 scene 里又出现「道徒 / 师兄 / 妻 / 众人」这类人物称谓，就打印提醒。
    这类漏配是「配角穿主角衣冠、长主角的脸」的根因，宁可吵一声也不要静默通过。
"""
import argparse
import json
import pathlib
import re
import sys
from common import atomic_bytes, detail_rules, get_page, load_story, output_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORIES = ROOT / "stories"
STYLES = ROOT / "styles"
IMAGES = ROOT / "assets" / "images"
CAST_STYLE = re.compile(r"\[\[cast\]\](.*?)\[\[/cast\]\]", re.DOTALL)

# 场景里常见、但不一定被写进 cast 的人物称谓。命中即提醒，不代表一定出错。
ROLE_HINTS = (
    "众人", "众徒", "徒弟", "道徒", "师兄", "师弟", "门人", "弟子",
    "老道", "道士", "书生", "妻子", "丈夫", "母亲", "父亲", "孩子",
    "仆人", "侍女", "官吏", "路人", "客", "妇", "翁", "僧",
)


def neg_line(story: dict, *, landscape=False) -> str:
    direction = ("景物、时代与道具严格按本页场景执行。" if landscape
                 else "人物服饰、时代与道具严格按本页场景及人物设定执行。")
    return direction + "画面不添加无关文字或装饰。" + story.get("negative", "")


def pick_names(story: dict, page: dict) -> list:
    """决定这一页要拼进哪些人物锚点，顺带体检。"""
    cast = story.get("cast") or []
    cast_names = [c["name"] for c in cast]
    scene = page.get("scene", "")

    declared = page.get("who")
    if declared is not None:
        if not isinstance(declared, list):
            raise SystemExit(f"第 {page.get('no')} 页：who 必须是数组")
        missing = [n for n in declared if n not in cast_names]
        if missing:
            raise SystemExit(
                f"第 {page.get('no')} 页：who 里的 {missing} 在 cast 里没有同名锚点。"
                f"现有锚点：{cast_names}"
            )
        return list(declared)

    names = [n for n in cast_names if n in scene]
    if len(names) < 2:
        hits = [
            w for w in ROLE_HINTS
            if w in scene and not any(w in n for n in cast_names)
        ]
        if hits:
            print(
                f"  ⚠️  第 {page.get('no'):02d} 页「{page.get('title')}」："
                f"scene 里出现了 {hits[:3]}，但只匹配到 {len(names)} 个锚点。"
                f"配角会被画成主角的同款衣冠与同一张脸——要么补 cast 锚点，要么用 who 显式指定。",
                file=sys.stderr,
            )
    return names


def build(story: dict, page: dict, suffix: str) -> str:
    names = pick_names(story, page)
    anchors = [f"{c['name']}：{c['anchor']}" for c in story["cast"] if c["name"] in names]
    landscape = page.get("who") == []
    style = CAST_STYLE.sub("" if landscape else r"\1", suffix)
    parts = [
        page["scene"],
        "本页为无人景物画面，不出现人物。" if landscape else "",
        ("人物设定（严格照此描绘，逐项对齐）：" + "；".join(anchors) + "。") if anchors else "",
        page.get("era_anchor", story.get("era_anchor", "")),
        neg_line(story, landscape=landscape),
        style.strip(),
    ]
    if len(anchors) > 1:
        parts.insert(3, "不同角色的脸型、年龄及衣着按设定区分，不画成同一张脸。")
    details = detail_rules(story, page)
    if details:
        parts.insert(1, "本页连续性与动作细节：\n" + "\n".join(f"- {rule}" for rule in details.values()))
    layout = output_settings(story)
    if layout.get("fit") == "strict" and layout["width"] > layout["height"]:
        parts.insert(0, "横幅连环画插图。采用满幅横向构图，场景与光影自然延伸至左右画边。")
    return "\n\n".join(p for p in parts if p)


def render_page(story, page):
    suffix = (STYLES / f"{story['style']}.txt").read_text(encoding="utf-8")
    return build(story, page, suffix)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--page", type=int, default=None, help="只输出某一页")
    args = ap.parse_args()

    story = load_story(args.slug, complete=False)

    out_dir = IMAGES / args.slug / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = story["pages"]
    if args.page is not None:
        pages = [p for p in pages if p["no"] == args.page]
        if not pages:
            print(f"第 {args.page} 页不存在", file=sys.stderr)
            return 1

    for page in pages:
        text = render_page(story, page)
        path = out_dir / f"{page['no']:02d}.txt"
        atomic_bytes(path, text.encode("utf-8"))
        print(f"--- {path.name} ({len(text)} 字) ---")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
