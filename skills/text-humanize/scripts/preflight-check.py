#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
text-humanize / scripts/preflight-check.py

中文文本「机械检查层」。审计前跑一次定基线，改写后再跑一次做验收。

用法:
    python3 preflight-check.py draft.md
    python3 preflight-check.py draft.md --tier short|long|literary   # 默认 long
    python3 preflight-check.py draft.md --lyrical
    python3 preflight-check.py draft.md --para-max 70 --strict
    python3 preflight-check.py 定稿.md --cut '## 本轮改动'
    python3 preflight-check.py draft.md --json

结果分三级:
    FAIL  机器残留，必须归零（半角引号 / 编号小标题 / 标点空格 / 破折号形态）
    WARN  文风项，只报数字供判断（超长段 / 同位语密度 / 词库命中 / SS-CN8 节拍）
    INFO  仅记录（段落数、人称计数）

退出码: 0 = 无 FAIL; 1 = 有 FAIL。加 --strict 时 WARN 也计入。

基线核对（SS-CN7，双向自检）:
    中文稿的正常形态是**全角引号多、半角引号 0**。反过来（全角 0 / 半角 N）几乎只有一个成因：
    原文被写盘时把 “ ” 落成了 \" —— 也就是**转录污染**，不是原文缺陷。
    脚本会把「全角引号」数字一并打出，并在这种形态下额外提示，避免把 0 缺陷的原文
    误报成 N 处 FAIL，再顺着「修」出一批假改动。

SS-CN8（节拍化人味，仅 long / literary）:
    「人味标记太规律」是 2026-10 才补录的反向模式 —— 现有五类都在抓「太机器」，
    这条抓「太像人」。段尾俏皮句节拍化 / 每节必收束 / 招呼式称谓密度 / 同构三连排比。
    全部只报数字，不参与退出码：节拍是文风取舍，该不该砍由作者定。

语言护栏（--lang，默认 auto）:
    本脚本的标点层规则是**中文专属**的 —— 半角引号、`...`、`--` 在英文里本来就是正确写法，
    拿英文稿跑会得到一堆假 FAIL。所以 auto 模式下先算 CJK 占比（口径同 SKILL.md 的
    Language Auto-Detection：CJK > 50% 才算中文模式），不足 50% 就把标点层降级为 INFO、
    不参与退出码，并在开头打出警告。需要覆盖时显式传 --lang zh。
"""

import argparse
import json
import pathlib
import re
import sys

BQ = chr(96)                 # 反引号，避免在源码里写字面量三连反引号
FENCE = BQ + BQ + BQ

CLICHE_METAPHOR = ["信使", "信笺", "叹息", "诗篇", "守望者", "耳语", "序章", "独白", "回响"]
FILLER_ADJ = ["温柔", "沉默", "浪漫", "治愈", "漫长", "细碎"]

# ---------- SS-CN8：节拍化人味（长文反向模式）----------
# 下面三个词库不是「禁用词」，是**密度探针**：散文里出现一两次是好事，
# 以固定间隔复现才说明「人味被当成开关在用」。阈值故意放宽，只报数不判死。
GREET_WORDS = ["咱们", "大伙儿", "人家"]
SOFT_WORDS = ["确实", "自然", "实在", "其实", "恐怕", "大概"]
# 段尾短句：段落末句 CJK 不超过这个字数就算一记，**只报数不设阈值**（原因见 collect() 内注释）。
# 20 字是按真实稿子标定的读数口径：被判定「段尾节拍化」的《拿破仑》原稿 43% / 24 处，
# 未命中的《佛像》原稿 24% / 12 处 —— 数字能提示，但不足以自动判死。
TAIL_SENT_MAX = 20
# 同构三连排比：句内 2 个以上逗号/顿号、且整句不超过这个字数。
# 注意是**粗略**计数，会把「制作、供奉」这类顿号词组一起算进来（虚高约三成），所以限放 8。
TRIAD_SENT_MAX = 22
TRIAD_LIMIT = 8

# 「编号式小标题」：四种形态
#   1、/ 1. / 1) / 1）   —— 阿拉伯数字 + 分隔符
#   一、/ 二.            —— 汉字数字 + 分隔符
#   一 / 二（独占一行）    —— 裸汉字编号（v1.3.1 补，此前漏判）
#   01 xxx               —— 两位零前缀
HEADING_NUM_RE = re.compile(
    r"^[ \t]{0,6}(?:"
    r"[0-9]{1,2}[、.．)）]"
    r"|[一二三四五六七八九十]{1,3}[、.．]"
    r"|[一二三四五六七八九十]{1,3}[ \t\r]*$"
    r"|0[0-9][ \t]"
    r")",
    re.M,
)

FAIL, WARN, INFO = "FAIL", "WARN", "INFO"


def is_cjk(ch):
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF


def cjk_len(s):
    return sum(1 for c in s if is_cjk(c))


def cjk_ratio(text):
    """CJK 占「CJK + 拉丁字母」的比例；口径同 SKILL.md Language Auto-Detection。"""
    cjk = cjk_len(text)
    latin = len(re.findall(r"[A-Za-z]", text))
    total = cjk + latin
    return (cjk / total) if total else 0.0


def strip_code(text):
    """去掉围栏代码块与行内代码，代码不算中文文本。"""
    text = re.sub(re.escape(FENCE) + r".*?" + re.escape(FENCE), "", text, flags=re.S)
    text = re.sub(BQ + "[^" + BQ + "\n]*" + BQ, "", text)
    return text


def body_paragraphs(text):
    """正文段落：排除标题、引用、表格、列表、分隔线。"""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or s == "---" or s[0] in "#>|" or s[:2] in ("- ", "* "):
            continue
        out.append(s)
    return out


def strip_md_markers(text):
    """剥掉行首的 Markdown 标题标记与引用标记，供「行锚定」的检查使用。

    `## ` / `> ` 这些标记自带的空格不是「标点周边空格」，标题里的编号也不是正文编号。
    不剥掉会同时产生两种错（v1.3.1 修）：

      漏判 —— `## 01 xxx` 数不到（`^\\s{0,6}` 匹配不上 `## `），基线假报「0 / OK」；
      误判 —— `## “引言式标题”` 被判「标点周边空格」、`> ——来源` 被判「破折号前后带空格」。
    """
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", text, flags=re.M)
    text = re.sub(r"^[ \t]{0,3}>[ \t]?", "", text, flags=re.M)
    return text


def baseline_note(text):
    """SS-CN7 的**方向核对**：光有「半角引号 N 处」这个数，不足以判断是原文缺陷还是转录污染。

    中文稿的正常形态是全角引号多、半角引号 0。反过来的形态（全角 0 / 半角 N）几乎只有一个
    成因 —— 把原文写进草稿文件时，工具把 “ ” 落成了 "。此时报出 N 处 FAIL 是假 FAIL，
    照着「修」还会修出一批假改动（实测 2026-10《佛像》稿：原文标点层全 0，写盘后变成 12 处半角）。
    """
    half = text.count('"')
    curly = text.count("“") + text.count("”")
    if half and not curly:
        return ("基线核对（SS-CN7）：全文 0 个全角引号 / %d 个半角引号 —— 中文稿正常应相反。\n"
                "     先确认这是不是「写盘转录污染」：把成对的 \" 按出现顺序还原成 “ ”，再重跑。\n"
                "     不核对方向就当成 FAIL 去改，会把 0 缺陷的原文改成假修复。" % half)
    if half and curly:
        return ("基线核对（SS-CN7）：全角引号 %d 个、半角引号 %d 个并存。\n"
                "     半角那 %d 处才是真残留，全角那些不要动。" % (curly, half, half))
    return None


def collect(text, tier, para_max, lyrical):
    rows = []

    def add(level, scope, name, value, limit=None):
        rows.append({"level": level, "scope": scope, "name": name, "value": value, "limit": limit})

    # 行锚定的三项检查在「剥掉 Markdown 标记」的副本上跑，避免把 `## ` / `> ` 自带的空格
    # 当成标点违规、把标题里的编号当成正文编号。见 strip_md_markers()。
    text_nomark = strip_md_markers(text)

    # ---------- 标点层：FAIL ----------
    add(FAIL, "标点层", '半角双引号 "', text.count('"'), 0)
    add(FAIL, "标点层", "半角单引号 '", text.count("'"), 0)
    # 全角引号只报数，不设限。存在的意义是给「半角引号 N 处」一个**方向感**：
    # 中文稿应当全角多、半角 0；全角也是 0 而半角非 0，就是转录污染（见 baseline_note）。
    add(INFO, "标点层", "全角引号 “ ”", text.count("“") + text.count("”"))
    add(FAIL, "标点层", "中文后半角逗号/句点", len(re.findall(r"[\u4e00-\u9fff][,.]", text)), 0)
    add(FAIL, "标点层", "三点省略号 ...", text.count("..."), 0)
    # 注意左右负向断言：否则 markdown 的 --- 分隔线会被当成 -- 误报
    add(FAIL, "标点层", "非规范破折号 -- / 单 —",
        len(re.findall(r"(?<!-)--(?!-)", text)) + len(re.findall(r"(?<!—)—(?!—)", text)), 0)
    add(FAIL, "标点层", "破折号前后带空格", len(re.findall(r"[ \t]——|——[ \t]", text_nomark)), 0)
    add(FAIL, "标点层", "标点周边空格",
        len(re.findall(r"[，。！？；：、）】”’][ \t]|[ \t][（【“‘]", text_nomark)), 0)

    # ---------- 标点层：INFO ----------
    em = text.count("——")
    add(INFO, "标点层", "标准破折号 ——(总量)", em)
    add(INFO, "标点层", "中文省略号 ……", text.count("……"))
    if tier == "short":
        add(FAIL, "标点层", "破折号 [短文本应删]", em, 0)

    # ---------- 排版 ----------
    add(FAIL, "排版", "编号式小标题", len(HEADING_NUM_RE.findall(text_nomark)), 0)

    paras = body_paragraphs(text)
    lens = [cjk_len(p) for p in paras] or [0]
    add(WARN, "排版", "超 %d 字段落数" % para_max, sum(1 for n in lens if n > para_max), 0)
    add(INFO, "排版", "最长段落(字)", max(lens))
    add(INFO, "排版", "段落总数", len(paras))

    # ---------- 人称 ----------
    add(INFO, "人称", "「我们」", text.count("我们"))
    add(INFO, "人称", "「我」(不含我们)", len(re.findall(r"我(?!们)", text)))

    # ---------- R 类（抒情 / 文学）----------
    if lyrical or tier == "literary":
        sents = [s for s in re.split(r"[。！？!?\n]", text) if cjk_len(s) >= 4]
        appo = run = longest = 0
        for s in sents:
            if re.search(r"[，,][^，。！？；：\n]{2,14}的[^，。！？；：\n]{2,10}", s):
                appo += 1
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        add(INFO, "R类", "同位语形态 X，Y的Z(粗计)", appo)
        add(WARN, "R类", "同位语最长连续句数", longest, 2)
        add(WARN, "R类", "陈腐喻体词库命中", sum(text.count(w) for w in CLICHE_METAPHOR), 0)
        add(WARN, "R类", "万能形容词词库命中", sum(text.count(w) for w in FILLER_ADJ), 2)
        detail = {w: text.count(w) for w in CLICHE_METAPHOR + FILLER_ADJ if text.count(w)}
        if detail:
            add(INFO, "R类", "词库命中明细", detail)

    # ---------- SS-CN8：节拍化人味（仅 long / literary）----------
    # 短文本不适用：评论 / 即刻 / 微博本来就该塞语气词，「节拍」无从谈起（见 SKILL.md Genre Gate）。
    # 全部只报数字、不设 FAIL —— 节拍是文风取舍，砍不砍由作者定（阈值故意放宽）。
    #
    # 本块只实现**能可靠计数**的三项（8c 密度探针 / 8d 同构排比，以及 8a 的原始数字）。
    # SS-CN8 的另两条（段尾俏皮句节拍化、每节必收束）靠人工读，判据写在 references/ai-smells-cn.md。
    # 为什么不给 8a 设 WARN 阈值：实测标不出来。20 字这个宽限会把「布袋和尚这条线，跟中国十世纪
    # 的一位僧人有关」这种普通中句一起算进去，于是「改得更好」的稿子占比反而从 24% 涨到 35%。
    # 阈值造出来的只会是假精确，所以 8a 只手报数字 + 正文里那句人工判据。
    if tier in ("long", "literary"):
        # 8a 段尾短句：段落末句 ≤20 字，供人工看「是不是每段都在抖包袱」
        tail = 0
        for p in paras:
            ps = [s for s in re.split(r"[。！？!?]", p) if cjk_len(s) >= 2]
            if ps and cjk_len(ps[-1]) <= TAIL_SENT_MAX:
                tail += 1
        add(INFO, "SS-CN8", "段尾短句(≤%d字) / 段落数" % TAIL_SENT_MAX,
            "%d / %d" % (tail, len(paras)))
        add(INFO, "SS-CN8", "段尾短句占比%(仅供人工参考)",
            round(tail * 100.0 / len(paras)) if paras else 0)

        # 8c 招呼式称谓 / 模糊限定词密度
        add(WARN, "SS-CN8", "招呼式称谓(咱们/大伙儿/人家)",
            sum(text.count(w) for w in GREET_WORDS), 5)
        add(WARN, "SS-CN8", "模糊限定词(确实/自然/实在/其实/恐怕/大概)",
            sum(text.count(w) for w in SOFT_WORDS), 8)

        # 8d 同构三连排比（粗略计数，见常量注释）
        ss = [s for s in re.split(r"[。！？!?\n]", text) if cjk_len(s) >= 2]
        triad = sum(1 for s in ss
                    if (s.count("，") + s.count("、")) >= 2 and cjk_len(s) <= TRIAD_SENT_MAX)
        add(WARN, "SS-CN8", "同构三连排比(粗略)", triad, TRIAD_LIMIT)

        # 结构背景：只报节数，节末是否「必收束」交人工（见上）
        add(INFO, "SS-CN8", "小标题节数",
            len(re.findall(r"^[ \t]{0,3}#{1,6}[ \t]+", text, flags=re.M)))

    return rows


def demote_punctuation(rows):
    """非中文模式：标点层规则不适用，FAIL 降级为 INFO（保留数字，不参与退出码）。"""
    for r in rows:
        if r["scope"] == "标点层":
            r["level"] = INFO
            r["limit"] = None
    return rows


def grade(row):
    """返回 OK / FAIL / warn / ok / - ，以及是否算失败。"""
    lv, val, lim = row["level"], row["value"], row["limit"]
    if lv == INFO or lim is None:
        return "-", False
    if isinstance(val, dict):
        return "-", False
    bad = val != lim if lim == 0 else val > lim
    if lv == FAIL:
        return ("FAIL" if bad else "OK"), bad
    return ("warn" if bad else "ok"), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--tier", choices=["short", "long", "literary"], default="long")
    ap.add_argument("--lyrical", action="store_true")
    ap.add_argument("--para-max", type=int, default=70)
    ap.add_argument("--strict", action="store_true", help="WARN 也计入退出码")
    ap.add_argument("--cut", default=None, help="在此标记处截断（丢弃尾注），只测正文")
    ap.add_argument("--lang", choices=["auto", "zh", "en"], default="auto",
                    help="auto（默认）按 CJK 占比判定；zh 强制按中文模式；en 强制不判标点层")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    raw = pathlib.Path(a.path).read_text(encoding="utf-8")
    if a.cut and a.cut in raw:
        raw = raw.split(a.cut)[0]
    text = strip_code(raw)

    ratio = cjk_ratio(text)
    if a.lang == "zh":
        zh_mode = True
    elif a.lang == "en":
        zh_mode = False
    else:
        zh_mode = ratio >= 0.5

    rows = collect(text, a.tier, a.para_max, a.lyrical)
    if not zh_mode:
        rows = demote_punctuation(rows)
    graded = [(r, *grade(r)) for r in rows]
    fails = [r for r, mark, bad in graded if mark == "FAIL"]
    warns = [r for r, mark, bad in graded if mark == "warn"]

    lang_note = None
    if not zh_mode:
        lang_note = ("非中文文本（中文占比 %.0f%% < 50%%），标点层规则不适用，已降级为 INFO。"
                     "本脚本只覆盖中文文本；确需强制判定请传 --lang zh。" % (ratio * 100))

    base_note = baseline_note(text) if zh_mode else None

    if a.json:
        out = {
            "file": a.path, "tier": a.tier, "cjk": cjk_len(text),
            "cjk_ratio": round(ratio, 3), "zh_mode": zh_mode,
            "rows": [{"level": r["level"], "scope": r["scope"], "name": r["name"],
                      "value": r["value"], "limit": r["limit"], "mark": m} for r, m, _ in graded],
            "fail": len(fails), "warn": len(warns),
        }
        if lang_note:
            out["lang_note"] = lang_note
        if base_note:
            out["baseline_note"] = base_note
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if (fails or (a.strict and warns)) else 0

    print("文件: %s" % a.path)
    print("档位: %s    中文字数: %d" % (a.tier, cjk_len(text)))
    if lang_note:
        print("!! %s" % lang_note)
    if base_note:
        print("!! %s" % base_note)
    print("-" * 66)
    scope = None
    for r, mark, bad in graded:
        if r["scope"] != scope:
            print("[%s]" % r["scope"])
            scope = r["scope"]
        val = r["value"] if not isinstance(r["value"], dict) else json.dumps(r["value"], ensure_ascii=False)
        lim = "" if r["level"] == INFO or r["limit"] is None else "  (限 %s)" % r["limit"]
        print("  %-4s %-28s %8s%s" % (mark, r["name"], val, lim))
    print("-" * 66)
    if fails:
        print("结论: FAIL %d 项 -> 修完重跑，不归零不交付" % len(fails))
        for r in fails:
            print("   x %s = %s (限 %s)" % (r["name"], r["value"], r["limit"]))
    elif warns:
        print("结论: 无 FAIL，WARN %d 项（文风取舍，交作者判断）" % len(warns))
    else:
        print("结论: 全部达标")
    return 1 if (fails or (a.strict and warns)) else 0


if __name__ == "__main__":
    sys.exit(main())
