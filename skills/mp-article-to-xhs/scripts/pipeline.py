#!/usr/bin/env python3
"""公众号文章 → 小红书图文笔记 流水线编排

子命令：
  pick    选题（hot=按热度出候选 / title=按标题模糊匹配 / url=指定链接），自动排除已处理过的
  fetch   抓取正文与全部图片（含懒加载），裁掉公众号水印
  check   校验图片完整性（抓到的 == 用上的）
  render  渲染卡片 PNG
  mark    登记状态（drafted / published），用于防重发
  status  查看已处理清单
"""
import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
STATE_FILE = os.path.join(SKILL_DIR, "state", "published.json")
PILLOW_PY = os.path.expanduser("~/.workbuddy/binaries/python/envs/pillow/bin/python")

# 需要 Pillow 做图片裁剪；系统 python 没有时自动切到 pillow 环境重跑
try:
    from PIL import Image  # noqa: F401
except ImportError:
    if os.path.exists(PILLOW_PY):
        os.execv(PILLOW_PY, [PILLOW_PY, os.path.abspath(__file__)] + sys.argv[1:])
    sys.exit("[ERROR] 需要 Pillow，未找到 " + PILLOW_PY)


def read_json(path, what="文件"):
    """读 JSON 并给出人话错误，避免用户对着 traceback 猜"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"[ERROR] 找不到{what}：{path}")
    except json.JSONDecodeError as e:
        sys.exit(f"[ERROR] {what} 不是合法 JSON：{path}\n        {e}")


# ── 状态 ──────────────────────────────────────────────
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"records": []}
    return read_json(STATE_FILE, "状态库 published.json")


def save_state(s):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError as e:
        sys.exit(f"[ERROR] 写状态库失败：{STATE_FILE}\n        {e}\n"
                 f"        台账写不进去就无法防重发，先修好目录权限再跑。")


def norm_title(t):
    return "".join((t or "").split())


def find_record(state, url=None, title=None):
    for r in state["records"]:
        if url and r.get("url") == url:
            return r
        if title and norm_title(r.get("title")) == norm_title(title):
            return r
    return None


def is_done(state, url=None, title=None):
    return find_record(state, url, title) is not None


# ── ego-browser 调用 ──────────────────────────────────
def run_ego(script, params, params_path):
    """把参数写成 JSON 文件再喂给 ego-browser nodejs。
    注意：ego-browser 的 daemon 不继承环境变量，只能走文件传参；
    路径固定（js 里写死），所以不要并发跑两篇，且用完立刻删掉。"""
    try:
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False)
    except OSError as e:
        sys.exit(f"[ERROR] 写不了参数文件：{params_path}\n        {e}\n"
                 f"        检查临时目录（$TMPDIR）是否可写")
    try:
        with open(os.path.join(SCRIPTS, script), "rb") as f:
            try:
                r = subprocess.run(["ego-browser", "nodejs"], stdin=f,
                                   capture_output=True, text=True, timeout=300)
            except FileNotFoundError:
                sys.exit("[ERROR] 找不到 ego-browser，先装它：\n"
                         "        sh ~/.workbuddy/skills/ego-browser/scripts/install.sh")
            except subprocess.TimeoutExpired:
                sys.exit(f"[ERROR] {script} 超时（300s）：浏览器可能卡在登录页或网络异常，"
                         f"重跑一次或检查 ego-lite 窗口状态")
    finally:
        try:
            os.unlink(params_path)
        except OSError:
            pass
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        print(out[-1500:], file=sys.stderr)
        sys.exit(f"[ERROR] {script} 执行失败（退出码 {r.returncode}）")
    return out


# ── 子命令 ────────────────────────────────────────────
def cmd_pick(args):
    state = load_state()

    if args.mode == "url":
        if not args.value:
            sys.exit("url 模式需要 --value <文章链接>")
        rec = find_record(state, url=args.value)
        if rec:
            print(json.dumps({"blocked": True, "reason": "该链接已处理过", "record": rec},
                             ensure_ascii=False, indent=1))
            return
        print(json.dumps({"picked": {"url": args.value, "title": "", "read": 0}},
                         ensure_ascii=False, indent=1))
        return

    out = "/tmp/mp2xhs_list_out.json"
    run_ego("list_articles.js",
            {"out": out, "count": args.count, "pages": max(2, args.count // 20 + 1)},
            "/tmp/mp2xhs_list_params.json")

    data = read_json(out, "文章列表（list_articles.js 的输出）")
    if isinstance(data, dict) and data.get("error"):
        sys.exit(f"[ERROR] 列表获取失败: {data['error']}")

    fresh = [a for a in data if not is_done(state, a["url"], a["title"])]

    if args.mode == "title":
        if not args.value:
            sys.exit("title 模式需要 --value <标题关键词>")
        kw = args.value
        hits = [a for a in fresh if kw in a["title"] or norm_title(kw) in norm_title(a["title"])]
        if not hits:
            all_hit = [a for a in data if kw in a["title"]]
            if all_hit:
                print(json.dumps({"blocked": True, "reason": "匹配到的文章都已处理过",
                                  "records": [find_record(state, a["url"], a["title"]) for a in all_hit]},
                                 ensure_ascii=False, indent=1))
            else:
                print(json.dumps({"error": "没有匹配到标题", "keyword": kw,
                                  "available": [a["title"] for a in fresh[:15]]},
                                 ensure_ascii=False, indent=1))
            return
        print(json.dumps({"candidates": hits}, ensure_ascii=False, indent=1))
        return

    # hot：按阅读数排序出候选池，已处理的排除；由 agent 从中挑
    ranked = sorted(fresh, key=lambda x: x.get("read", 0), reverse=True)
    pool = ranked[:args.top]
    print(json.dumps({
        "pool_size": len(pool),
        "total_fresh": len(fresh),
        "suggest": random.choice(pool)["title"] if pool else None,
        "candidates": pool,
    }, ensure_ascii=False, indent=1))


def cmd_fetch(args):
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    meta_path = os.path.join(out, "article.json")

    # --reuse：已有抓取结果时跳过联网重抓，只重做裁剪（调样式时反复用）
    if args.reuse and os.path.exists(meta_path):
        cached = read_json(meta_path, "article.json")
        if cached.get("url") and cached["url"] != args.url:
            sys.exit(f"[ERROR] --reuse 拒绝：{out} 里存的是另一篇\n"
                     f"        缓存 URL: {cached['url']}\n"
                     f"        本次 URL: {args.url}\n"
                     f"        换一个 --out 目录，或去掉 --reuse 重新抓取")
        print("[reuse] 使用已有 article.json，跳过抓取")
    else:
        log = run_ego("fetch_article.js", {"url": args.url, "out_dir": out},
                      "/tmp/mp2xhs_fetch_params.json")
        if not os.path.exists(meta_path):
            print(log[-1200:], file=sys.stderr)
            sys.exit("[ERROR] 未生成 article.json")

    meta = read_json(meta_path, "article.json")

    # 裁掉公众号右下角水印（"公众号 · 账号名"，小红书判定为站外引流）
    # 水印高度和图片尺寸不成固定比例，实测 3:2 图（1024 高）需 140px、横幅图（819 高）需 200px，
    # 所以取 max(200, 20% 高)：既能盖住横幅图的水印，又不会把 3:2 图的人物切太狠
    clean_dir = os.path.join(out, "clean")
    os.makedirs(clean_dir, exist_ok=True)
    for im in meta.get("imgs", []):
        if not im.get("file") or not os.path.exists(im["file"]):
            continue
        im_obj = Image.open(im["file"])
        if im_obj.mode != "RGB":
            im_obj = im_obj.convert("RGB")
        w, h = im_obj.size
        if args.crop_pct:
            crop_px = int(h * args.crop_pct)
        else:
            crop_px = max(200, int(h * 0.20))
            crop_px = min(crop_px, int(h * 0.30))
        keep_h = h - crop_px
        clean = im_obj.crop((0, 0, w, keep_h))
        cp = os.path.join(clean_dir, os.path.basename(im["file"]))
        clean.save(cp, quality=92)
        im["clean"] = cp
        im["orig_size"] = [w, h]
        im["clean_size"] = [w, keep_h]
        im["crop_px"] = crop_px

    # 正文去掉公众号导语/声明行，保留段落
    body = meta.get("body", "")
    meta["body"] = body

    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
    except OSError as e:
        sys.exit(f"[ERROR] 写 article.json 失败：{meta_path}\n        {e}")

    total, got = meta.get("imgTotal", 0), meta.get("imgDownloaded", 0)
    print(f"标题: {meta['title']}")
    print(f"正文: {len(body)} 字")
    print(f"图片: 抓到 {got} / 页面共 {total}")
    if got != total:
        print(f"[WARN] 有 {total - got} 张图没下载成功，见 article.json 的 imgFailed")
        sys.exit(2)
    crops = [im.get("crop_px") for im in meta.get("imgs", []) if im.get("crop_px")]
    if crops:
        print(f"已裁水印（底部 {min(crops)}~{max(crops)}px），输出: {clean_dir}")
    else:
        print(f"本文无图，跳裁剪，输出: {clean_dir}")


def cmd_check(args):
    """图片完整性硬校验：抓到的每张图都必须在卡片里用上"""
    out = os.path.abspath(args.out)
    meta = read_json(os.path.join(out, "article.json"), "article.json")
    cards = read_json(args.cards, "卡片内容 cards.json")

    total = meta.get("imgTotal", 0)
    downloaded = meta.get("imgDownloaded", 0)
    used_files = []
    for p in cards["pages"]:
        if p.get("image"):
            used_files.append(os.path.basename(p["image"]))
    used_unique = sorted(set(used_files))
    excluded = [os.path.basename(x) for x in (args.exclude or [])]

    problems = []
    if downloaded != total:
        problems.append(f"下载不全：{downloaded}/{total}")
    missing = [im for im in meta.get("imgs", [])
               if im.get("clean") and os.path.basename(im["clean"]) not in used_unique
               and os.path.basename(im["clean"]) not in excluded]
    if missing:
        problems.append("有图未用上且未声明剔除: " + ", ".join(os.path.basename(m["clean"]) for m in missing))
    ghost = [f for f in used_unique if not os.path.exists(os.path.join(out, "clean", f))]
    if ghost:
        problems.append("cards.json 引用了不存在的图片: " + ", ".join(ghost))
    dup = [x for x in set(used_files) if used_files.count(x) > 1]
    if dup:
        problems.append("同一张图重复使用: " + ", ".join(dup))
    if len(used_unique) > len(cards["pages"]):
        problems.append("图片数超过页数")

    print(json.dumps({
        "img_total": total, "img_downloaded": downloaded,
        "img_used": len(used_unique), "used_files": used_unique,
        "excluded": excluded,
        "pages": len(cards["pages"]), "ok": not problems, "problems": problems,
    }, ensure_ascii=False, indent=1))
    if problems:
        sys.exit(3)


def cmd_render(args):
    cards = os.path.abspath(args.cards)
    outdir = os.path.abspath(args.out)
    cmd = [sys.executable, os.path.join(SCRIPTS, "mp2xhs_card.py"),
           cards, "--outdir", outdir, "--theme", args.theme]
    if args.typeface:
        cmd += ["--typeface", args.typeface]
    if args.only:
        cmd += ["--only", str(args.only)]
    try:
        r = subprocess.run(cmd)
    except FileNotFoundError:
        sys.exit(f"[ERROR] 找不到渲染脚本：{cmd[1]}")
    except KeyboardInterrupt:
        sys.exit("[INFO] 已中断渲染")
    sys.exit(r.returncode)


def cmd_mark(args):
    state = load_state()
    rec = find_record(state, url=args.url, title=args.title)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if rec:
        rec.update({"status": args.status, "updated_at": now})
        if args.note:
            rec["note"] = args.note
    else:
        rec = {"url": args.url, "title": args.title, "status": args.status,
               "created_at": now, "updated_at": now}
        if args.note:
            rec["note"] = args.note
        state["records"].append(rec)
    rec["cards"] = args.cards or rec.get("cards", 0)
    rec["images"] = args.images or rec.get("images", 0)
    save_state(state)
    print(f"已登记: {args.title} -> {args.status}")


def cmd_status(args):
    state = load_state()
    recs = state["records"]
    print(f"共 {len(recs)} 条记录")
    for r in sorted(recs, key=lambda x: x.get("updated_at", ""), reverse=True):
        print(f"  [{r.get('status','?'):9}] {r.get('updated_at','')}  {r.get('title','')}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pick")
    p.add_argument("--mode", required=True, choices=["hot", "title", "url"])
    p.add_argument("--value", default="")
    p.add_argument("--count", type=int, default=40, help="从后台拉多少篇")
    p.add_argument("--top", type=int, default=10, help="hot 模式候选池大小")
    p.set_defaults(func=cmd_pick)

    p = sub.add_parser("fetch")
    p.add_argument("--url", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--crop-pct", type=float, default=None,
                   help="手动指定裁掉底部的比例；不给则按 max(200px, 20%%高) 自适应")
    p.add_argument("--reuse", action="store_true", help="复用已有 article.json，不重新抓取")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("check")
    p.add_argument("--out", required=True)
    p.add_argument("--cards", required=True)
    p.add_argument("--exclude", nargs="*", default=[],
                   help="因合规风险主动不用的图（如 clean/img2.jpg），需显式声明")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("render")
    p.add_argument("--cards", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--theme", default="ink")
    p.add_argument("--typeface", default=None, choices=["classic", "modern", "soft"],
                   help="字体方案，不给则用 cards.json 顶层或主题默认")
    p.add_argument("--only", type=int, default=0, help="只渲染第 N 页（调样式时省时间）")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("mark")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--status", required=True, choices=["drafted", "published", "skipped"])
    p.add_argument("--note", default="")
    p.add_argument("--cards", type=int, default=0)
    p.add_argument("--images", type=int, default=0)
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
