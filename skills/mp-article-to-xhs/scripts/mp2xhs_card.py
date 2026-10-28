#!/usr/bin/env python3
"""公众号文章 → 小红书知识卡片生成器（支持图文混排）

用法:
    python3 mp2xhs_card.py content.json --outdir ./v3 --theme ink

content.json 结构:
{
  "account": "@雨夜心灯",
  "tag": "历史冷知识",
  "seal": "夜",
  "pages": [
    {"kicker": "", "title": ["行1","行2"], "note": ["说明1","说明2"],
     "image": "imgs/clean/img1.jpg", "pic_h": 640}
  ]
}
image 可省略（纯文字页），pic_h 默认 640。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

W, H = 1080, 1440

# 字体方案 ──────────────────────────────────────────
# 字体栈一律写全跨平台 fallback：macOS 优先，其次 Linux（Noto/思源），最后 Windows（雅黑/宋体）。
# 本机只有 Songti / Hiragino / STHeiti，Linux/Windows 机器靠后面的 fallback 兜底。
SERIF_STACK = ("'Songti SC','STSong','Source Han Serif SC','Noto Serif CJK SC',"
               "'Noto Serif SC','SimSun',serif")
SANS_STACK = ("'PingFang SC','Hiragino Sans GB','Source Han Sans SC','Noto Sans CJK SC',"
              "'Microsoft YaHei','WenQuanYi Micro Hei',sans-serif")
MONO_STACK = ("'IBM Plex Mono','SF Mono',Menlo,Consolas,monospace")

# 有性格的中文字体走本地缓存：首次渲染时下载一次存到 ~/.cache/mp2xhs/fonts，
# 之后每个页面直接引用本地文件（file://），既快又能离线渲染。
# CDN 只是首次下载来源；字体均为 OFL 授权，可随 skill 一起分发使用。
FONT_DIR = os.path.join(os.path.expanduser("~"), ".cache", "mp2xhs", "fonts")
FONT_SOURCES = {
    "MaShanZheng-Regular.ttf": (
        "Ma Shan Zheng", "400",
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/mashanzheng/MaShanZheng-Regular.ttf",
    ),
    "ZCOOLXiaoWei-Regular.ttf": (
        "ZCOOL XiaoWei", "400",
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/zcoolxiaowei/ZCOOLXiaoWei-Regular.ttf",
    ),
    "ZCOOLQingKeHuangYou-Regular.ttf": (
        "ZCOOL QingKe HuangYou", "400",
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/zcoolqingkehuangyou/ZCOOLQingKeHuangYou-Regular.ttf",
    ),
}

# 其余字体（思源宋、Playfair、IBM Plex Mono）字重多、体积大，走 CDN 按需子集
# fonts.font.im 是国内可达的 Google Fonts 镜像。
CSS_XIAOWEI = "https://fonts.font.im/css2?family=ZCOOL+XiaoWei&display=swap"
CSS_BRUSH = "https://fonts.font.im/css2?family=Ma+Shan+Zheng&display=swap"
CSS_MAGS = ("https://fonts.font.im/css2?family=Playfair+Display:wght@600;700"
            "&family=Noto+Serif+SC:wght@300;700&display=swap")
CSS_MONO = "https://fonts.font.im/css2?family=IBM+Plex+Mono:wght@400;500&display=swap"
CSS_QINGKE = "https://fonts.font.im/css2?family=ZCOOL+QingKe+HuangYou&display=swap"
CSS_DOSSIER = ("https://fonts.font.im/css2?family=Noto+Serif+SC:wght@700"
               "&family=IBM+Plex+Mono:wght@400;500&display=swap")


def ensure_local_font(filename, quiet=False):
    """确保字体文件在本地缓存里；返回绝对路径，失败返回 None。

    下载后按 Content-Length 校验字节数：实测 jsDelivr 会中途截断（庆科黄油
    下到 6.1MB 就断，完整是 8.3MB），截断文件 Pillow 仍能加载、渲染看似正常，
    但部分字形会错——所以必须比对长度，不能只判 size > 100KB。
    """
    path = os.path.join(FONT_DIR, filename)
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return path
    fam, weight, url = FONT_SOURCES[filename]
    os.makedirs(FONT_DIR, exist_ok=True)
    try:
        import urllib.request
        if not quiet:
            print(f"↓ 首次下载字体 {fam} …", flush=True)
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310
            expected = r.headers.get("Content-Length")
            got = 0
            with open(path + ".part", "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
        if expected and got != int(expected):
            raise OSError(f"下载不完整：{got} / {expected} 字节")
        os.replace(path + ".part", path)
        if not quiet:
            print(f"✅ 字体已缓存：{path}", flush=True)
        return path
    except Exception as e:  # noqa: BLE001
        if not quiet:
            print(f"⚠️  字体下载失败（{e}），改用 CDN 在线字体", flush=True)
        for p in (path + ".part",):
            if os.path.exists(p):
                os.unlink(p)
        return None

# 七套气质：靠「字族 + 字重 + 字距」区分，颜色主题与字体方案正交。
# 带 font_css 的方案会用 webfont 顶替标题/正文，fallback 仍是本地宋体/黑体，断网也不会糊。
TYPEFACES = {
    # 古典文气：宋体标题 + 宋体正文，字距略开。历史、人文、旧事
    "classic": dict(
        title=SERIF_STACK, body=SERIF_STACK, label=SANS_STACK,
        title_weight=600, title_spacing="2px", body_spacing="0.8px",
        label_spacing="8px", kicker_spacing="6px",
    ),
    # 资讯现代：黑体标题压阵 + 宋体正文好读。知识科普、考古、人物
    "modern": dict(
        title=SANS_STACK, body=SERIF_STACK, label=SANS_STACK,
        title_weight=600, title_spacing="0.5px", body_spacing="0.5px",
        label_spacing="7px", kicker_spacing="5px",
    ),
    # 柔和文艺：细宋体标题 + 黑体正文，靠细字重与宽字距出气韵。生活、情感、随笔
    # 不用 Yuanti/圆体：简体汉字覆盖不全，容易整行 fallback 成混排
    "soft": dict(
        title=SERIF_STACK, body=SANS_STACK, label=SANS_STACK,
        title_weight=300, title_spacing="4px", body_spacing="1.2px",
        label_spacing="10px", kicker_spacing="8px",
    ),
    # 古风衬线：站酷小薇做标题，横细竖粗带古意，正文仍宋体保证可读。文化、古建、器物
    "gufeng": dict(
        title="'ZCOOL XiaoWei'," + SERIF_STACK, body=SERIF_STACK, label=SANS_STACK,
        title_weight=400, title_spacing="3px", body_spacing="0.9px",
        label_spacing="9px", kicker_spacing="7px",
        font_css=CSS_XIAOWEI, local_font="ZCOOLXiaoWei-Regular.ttf",
    ),
    # 老标签体：站酷庆科黄油体，粗圆黑、笔画厚实，像文物标签/旧海报标题。清单、器物、知识点
    "qingke": dict(
        title="'ZCOOL QingKe HuangYou'," + SANS_STACK, body=SERIF_STACK, label=SANS_STACK,
        title_weight=400, title_spacing="1px", body_spacing="0.8px",
        label_spacing="8px", kicker_spacing="6px",
        font_css=CSS_QINGKE, local_font="ZCOOLQingKeHuangYou-Regular.ttf",
    ),
    # 毛笔题签：马善政行楷做标题，像手写题字。只适合短标题（≤10 字），长句会糊
    "brush": dict(
        title="'Ma Shan Zheng'," + SERIF_STACK, body=SERIF_STACK, label=SANS_STACK,
        title_weight=400, title_spacing="2px", body_spacing="0.9px",
        label_spacing="9px", kicker_spacing="7px",
        font_css=CSS_BRUSH, local_font="MaShanZheng-Regular.ttf",
    ),
    # 杂志编辑：中文用细体思源宋（300），西文数字用 Playfair 粗衬线，靠粗细反差出编辑感。
    # 反面教训：中文若也用 600，和 classic 的宋体 600 几乎看不出差别。
    "mags": dict(
        title="'Playfair Display','Noto Serif SC'," + SERIF_STACK,
        body="'Noto Serif SC'," + SERIF_STACK, label=SANS_STACK,
        title_weight=300, title_spacing="1px", body_spacing="0.8px",
        label_spacing="8px", kicker_spacing="6px",
        font_css=CSS_MAGS,
    ),
    # 档案考据：思源宋 700 的重衬线标题 + 等宽页码，像一份档案卷宗封面。考据、数据、年代考
    "dossier": dict(
        title="'Noto Serif SC'," + SERIF_STACK,
        body="'Noto Serif SC'," + SERIF_STACK, label=SANS_STACK,
        title_weight=700, title_spacing="0px", body_spacing="0.6px",
        label_spacing="6px", kicker_spacing="5px",
        mono="'IBM Plex Mono'," + MONO_STACK,
        font_css=CSS_DOSSIER,
    ),
}

# 颜色主题默认搭配的字体方案（可用 --typeface 覆盖）
THEME_TYPEFACE = {"ink": "gufeng", "gold": "gufeng"}

THEMES = {
    "ink": dict(
        bg1="#F9F4EA", bg2="#F1E8D7", fg="#1C1A17", sub="#57503F",
        accent="#A63A31", line="#D3C5AC", muted="#8C8069",
        seal_fg="#FBF6EC", seal_bg="#A63A31", pic_line="#D8CBB2",
    ),
    "gold": dict(
        bg1="#1B1613", bg2="#110D0B", fg="#EDE1C6", sub="#A2947A",
        accent="#C04434", line="#3A2F25", muted="#8A7C63",
        seal_fg="#F3EADA", seal_bg="#B03A2E", pic_line="#3A2F25",
    ),
}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def fit(lines, cap, avail=860, ratio=0.97):
    n = max((len(l) for l in lines), default=1)
    return min(cap, int(avail / max(n, 1) * ratio))


def data_uri(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
    if not os.path.exists(path):
        sys.exit(f"[ERROR] cards.json 引用的图片不存在：{path}\n"
                 f"        检查 image 路径是否相对 cards.json 所在目录")
    try:
        with open(path, "rb") as f:
            return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()
    except OSError as e:
        sys.exit(f"[ERROR] 读不到卡片图片：{path}\n        {e}")


def build_html(page, idx, total, meta, theme, base_dir, typeface=None):
    t = THEMES[theme]
    tf = TYPEFACES[typeface or THEME_TYPEFACE.get(theme, "classic")]
    is_cover = idx == 1
    title = page.get("title", [])
    note = page.get("note", [])
    kicker = page.get("kicker", "")
    # 有性格字体走 @import（必须在 style 最前），无 webfont 的方案留空。
    # 若该方案的中文字体已缓存到本地，就直接内嵌 @font-face 指本机文件，不再依赖网络。
    font_import = ""
    local = tf.get("local_font")
    local_path = os.path.join(FONT_DIR, local) if local else ""
    if local_path and os.path.exists(local_path):
        fam, weight, _ = FONT_SOURCES[local]
        font_import = (
            f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};"
            f"src:url('file://{local_path}') format('truetype');font-display:block;}}\n"
        )
    elif tf.get("font_css"):
        font_import = f'@import url("{tf["font_css"]}");\n'
    foot_font = tf.get("mono") or tf["label"]

    image = page.get("image", "")
    pic_h = page.get("pic_h", 640 if image else 0)
    if image and not os.path.isabs(image):
        image = os.path.join(base_dir, image)

    t_fs = fit(title, cap=96 if pic_h == 0 else 74)
    n_fs = fit(note, cap=34 if pic_h == 0 else 31)

    title_html = "".join(f'<div class="tl" style="font-size:{t_fs}px">{l}</div>' for l in title)
    note_html = "".join(f'<div class="nl" style="font-size:{n_fs}px">{l}</div>' for l in note)
    kicker_html = f'<div class="kicker">{kicker}</div>' if kicker else ""

    pic_html = ""
    if pic_h:
        pic_html = f'<div class="pic" style="height:{pic_h}px"><img src="{data_uri(image)}" alt=""></div>'

    pad = "62px 92px 54px" if pic_h else "104px 100px 84px"
    rule_m = "32px 0 30px" if pic_h else "42px 0 44px"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{font_import}*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{-webkit-font-smoothing:antialiased}}
.card{{position:relative;width:{W}px;height:{H}px;display:flex;flex-direction:column;overflow:hidden;
  background:linear-gradient(155deg,{t['bg1']} 0%,{t['bg2']} 100%);font-family:{tf['body']};color:{t['fg']}}}
.pic{{width:{W}px;flex:none;border-bottom:1px solid {t['pic_line']};overflow:hidden}}
.pic img{{width:100%;height:100%;object-fit:cover;display:block}}
.body{{flex:1;display:flex;flex-direction:column;padding:{pad};min-height:0}}
.head{{display:flex;align-items:flex-start;justify-content:space-between;flex:none}}
.tag{{font-family:{tf['label']};font-size:23px;letter-spacing:{tf['label_spacing']};color:{t['muted']};padding-top:10px}}
.seal{{width:64px;height:64px;background:{t['seal_bg']};color:{t['seal_fg']};flex:none;
  font-family:{tf['title']};font-weight:600;
  display:flex;align-items:center;justify-content:center;font-size:35px;line-height:1}}
.mid{{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0}}
.kicker{{font-family:{tf['label']};font-size:24px;letter-spacing:{tf['kicker_spacing']};color:{t['accent']};margin-bottom:26px}}
.tl{{font-family:{tf['title']};line-height:1.40;letter-spacing:{tf['title_spacing']};font-weight:{tf['title_weight']}}}
.rule{{width:88px;height:2px;background:{t['accent']};margin:{rule_m}}}
.nl{{font-family:{tf['body']};line-height:1.85;color:{t['sub']};letter-spacing:{tf['body_spacing']}}}
.foot{{display:flex;justify-content:space-between;align-items:center;flex:none;
  border-top:1px solid {t['line']};padding-top:20px;margin-top:22px;
  font-family:{foot_font};font-size:21px;letter-spacing:2px;color:{t['muted']};
  font-variant-numeric:tabular-nums}}
</style></head><body><div class="card">
  {pic_html}
  <div class="body">
    <div class="head"><div class="tag">{meta.get('tag','')}</div><div class="seal">{meta.get('seal','夜')}</div></div>
    <div class="mid">{kicker_html}{title_html}<div class="rule"></div>{note_html}</div>
    <div class="foot"><div>No.{idx:02d} / {total:02d}</div><div>{meta.get('account','')}</div></div>
  </div>
</div></body></html>"""


def render(html, out_path):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(html)
    tmp.close()
    chrome = next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None)
    if not chrome:
        sys.exit("[ERROR] 未找到 Chrome")
    # 不加 --user-data-dir / --disk-cache-dir：两者都实测会让连续渲染卡死
    # （前者抢 profile 单例锁、后者让 headless 不出图）。webfont 每页重下也就 1-2 秒。
    try:
        r = subprocess.run([
            chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--virtual-time-budget=9000",
            "--allow-file-access-from-files",
            f"--window-size={W},{H}", "--screenshot=" + os.path.abspath(out_path),
            "file://" + tmp.name,
        ], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            sys.exit(f"[ERROR] 渲染失败: {r.stderr}")
    except subprocess.TimeoutExpired:
        sys.exit(f"[ERROR] 渲染超时（120s）：{out_path}\n"
                 f"        多为 webfont CDN 卡住或 Chrome 实例残留，重试一次或改用 --typeface classic")
    finally:
        os.unlink(tmp.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("content")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--theme", default="ink", choices=list(THEMES))
    ap.add_argument("--typeface", default=None, choices=list(TYPEFACES),
                    help="字体方案：classic 宋体文气 / modern 黑体标题 / soft 柔和文艺 / "
                         "gufeng 古风衬线 / qingke 粗圆标签 / brush 毛笔题签 / "
                         "mags 杂志编辑 / dossier 档案考据")
    ap.add_argument("--only", type=int, default=0, help="只渲染第 N 页（调试用）")
    args = ap.parse_args()

    try:
        with open(args.content, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"[ERROR] 找不到 cards.json：{args.content}")
    except json.JSONDecodeError as e:
        sys.exit(f"[ERROR] cards.json 不是合法 JSON：{args.content}\n        {e}")
    if not data.get("pages"):
        sys.exit("[ERROR] cards.json 里 pages 为空，至少要有一页")

    pages = data["pages"]
    meta = {k: data.get(k, "") for k in ("account", "tag", "seal")}
    # 字体方案优先级：命令行 --typeface > cards.json 顶层 typeface > 主题默认
    typeface = args.typeface or data.get("typeface") or None
    # 该方案若用本地缓存字体，渲染前先确保字体到位（只首次下载，失败自动回落 CDN）
    tf_sel = TYPEFACES[typeface or THEME_TYPEFACE.get(args.theme, "classic")]
    if tf_sel.get("local_font"):
        ensure_local_font(tf_sel["local_font"])
    base_dir = os.path.dirname(os.path.abspath(args.content))
    os.makedirs(args.outdir, exist_ok=True)

    for i, page in enumerate(pages, 1):
        if args.only and i != args.only:
            continue
        out = os.path.join(args.outdir, f"{i:02d}.png")
        render(build_html(page, i, len(pages), meta, args.theme, base_dir, typeface), out)
        print(f"输出: {out}  [{typeface or THEME_TYPEFACE.get(args.theme, 'classic')}]", flush=True)


if __name__ == "__main__":
    main()
