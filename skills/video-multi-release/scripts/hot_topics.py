#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取抖音热榜，按与视频描述的相关度筛选热点话题。

用法:
  python3 hot_topics.py --desc "视频描述文本" [--keywords "历史,国学"] [--top 30] [--pick 2] [--json]

逻辑:
  1. 拉抖音热榜 (iesdouyin 公开接口，无需鉴权)
  2. 与描述分词 / 显式关键词做字符级 bigram 重合匹配（中文无空格分词的近似方案）
  3. 输出相关度最高的 pick 个热榜词（含热度），供发布脚本作为附加话题
"""
import argparse
import json
import sys
import urllib.request

HOT_URL = "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/"

STOP = set("的了是在和有就都不也都还又被把从对让向往等比但是然后因此所以因为如果虽然而且并且以及或者一个这个那个什么怎么如何可以可能我们会你们他们自己它们这样那样".split())

# 泛词 bigram：出现在任何描述里都不能说明相关性（否则「热点话题」会命中所有带「热点」的热榜词）
GENERIC = set("""
热点 话题 内容 视频 分享 今天 我们 大家 来看 一起 这个 那个 什么 怎么 如何
可以 一个 就是 不是 没有 还是 已经 现在 时候 大家 朋友 记得 关注 点赞 评论
""".split())


def bigrams(text):
    """中文按字滑窗取 bigram，过滤停用词与泛词组成的对。"""
    s = "".join(ch for ch in text if ch not in "，。！？、；：·「」『』（）()《》\"' \n\t#")
    return {s[i:i + 2] for i in range(len(s) - 1)} - {""} - GENERIC


def score(word, desc_bi, kw_bi):
    w = bigrams(word)
    if not w:
        return 0.0
    hit_desc = len(w & desc_bi)
    hit_kw = len(w & kw_bi)
    # 至少要命中 2 个描述 bigram，或命中 1 个关键词 bigram——单个巧合不足以算相关
    if hit_kw == 0 and hit_desc < 2:
        return 0.0
    return hit_desc * 2.0 + hit_kw * 3.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desc", required=True, help="视频描述文本（相关度依据）")
    ap.add_argument("--keywords", default="", help="显式关键词，逗号分隔，权重更高")
    ap.add_argument("--top", type=int, default=30, help="只在前 N 个热榜词里筛")
    ap.add_argument("--pick", type=int, default=2, help="最多返回几个热点话题")
    ap.add_argument("--min-score", type=float, default=2.0, help="相关度门槛，低于则不推荐")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    req = urllib.request.Request(HOT_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print("热榜拉取失败: %s" % exc, file=sys.stderr)
        # 拿不到热榜不算错误（热点是加分项，不是必选项），退出码 0 让调用方静默跳过
        print("[]" if args.json else "（热榜不可用，跳过）")
        return
    words = data.get("word_list") or []
    if not words:
        print("热榜拉取失败", file=sys.stderr)
        sys.exit(1)

    desc_bi = bigrams(args.desc)
    kw_bi = bigrams(args.keywords)

    scored = []
    for item in words[:args.top]:
        w = item.get("word", "")
        s = score(w, desc_bi, kw_bi)
        if s >= args.min_score:
            scored.append({"word": w, "hot": item.get("hot_value", 0), "score": round(s, 1)})
    scored.sort(key=lambda x: -x["score"])
    picked = scored[:args.pick]

    if args.json:
        print(json.dumps(picked, ensure_ascii=False))
    else:
        if not picked:
            print("（无相关热点，跳过）")
        for p in picked:
            print("%s\t热度%s\t相关度%s" % (p["word"], p["hot"], p["score"]))


if __name__ == "__main__":
    main()
