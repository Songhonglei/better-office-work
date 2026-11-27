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
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORIES = ROOT / "stories"
STYLES = ROOT / "styles"
IMAGES = ROOT / "assets" / "images"

# 场景里常见、但不一定被写进 cast 的人物称谓。命中即提醒，不代表一定出错。
ROLE_HINTS = (
    "众人", "众徒", "徒弟", "道徒", "师兄", "师弟", "门人", "弟子",
    "老道", "道士", "书生", "妻子", "丈夫", "母亲", "父亲", "孩子",
    "仆人", "侍女", "官吏", "路人", "客", "妇", "翁", "僧",
)


def neg_line(story: dict) -> str:
    """服色红线跟着主角走，不写死某本书的主角名。"""
    cast = story.get("cast") or []
    hero = cast[0]["name"] if cast else "主角"
    return (
        "不出现尸体、血腥、裸露、施暴动作。"
        "墙面、门楣、匾额、书页、书脊、卷轴、旗帜、器物表面一律空白，不题任何字。"
        "画面里不要出现任何现代物件。"
        f"主角{hero}的服色与冠帽严格按「人物设定」一节执行，不得改色、不得换成深色或黑色衣袍。"
    )


def pick_names(story: dict, page: dict) -> list:
    """决定这一页要拼进哪些人物锚点，顺带体检。"""
    cast = story.get("cast") or []
    cast_names = [c["name"] for c in cast]
    scene = page.get("scene", "")

    declared = page.get("who")
    if declared is not None:
        if not isinstance(declared, list) or not declared:
            raise SystemExit(f"第 {page.get('no')} 页：who 必须是非空数组")
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
    anchors = [c["anchor"] for c in story["cast"] if c["name"] in names]
    prefix = f"{story['title']}图{page['no']:02d}·{page['title']}。"
    parts = [
        prefix,
        page["scene"],
        ("人物设定（严格照此描绘，逐项对齐）：" + "；".join(anchors) + "。") if anchors else "",
        story.get("era_anchor", ""),
        neg_line(story),
        suffix.strip(),
    ]
    if len(anchors) > 1:
        parts.insert(3, "画面里所有人的脸型轮廓差异极大，绝不相同，不得画成同一张脸。")
    return "\n\n".join(p for p in parts if p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--page", type=int, default=None, help="只输出某一页")
    args = ap.parse_args()

    story_file = STORIES / f"{args.slug}.json"
    if not story_file.exists():
        print(f"缺分镜文件：{story_file}", file=sys.stderr)
        return 1
    story = json.loads(story_file.read_text(encoding="utf-8"))

    style_file = STYLES / f"{story['style']}.txt"
    if not style_file.exists():
        print(f"缺风格后缀文件：{style_file}", file=sys.stderr)
        return 1
    suffix = style_file.read_text(encoding="utf-8")

    out_dir = IMAGES / args.slug / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = story["pages"]
    if args.page is not None:
        pages = [p for p in pages if p["no"] == args.page]
        if not pages:
            print(f"第 {args.page} 页不存在", file=sys.stderr)
            return 1

    for page in pages:
        text = build(story, page, suffix)
        path = out_dir / f"{page['no']:02d}-{page['title']}.txt"
        path.write_text(text, encoding="utf-8")
        print(f"--- {path.name} ({len(text)} 字) ---")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
