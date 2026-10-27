#!/usr/bin/env python3
"""依赖自检：部署到新机器时先跑这个，缺什么一次看清

用法: python3 scripts/doctor.py
退出码 0 = 必需依赖齐全；1 = 有必需项缺失
"""
import os
import platform
import shutil
import subprocess
import sys

OK = "\033[32m✅\033[0m"
NO = "\033[31m❌\033[0m"
WARN = "\033[33m⚠️ \033[0m"

problems = []
warnings = []
system = platform.system()


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        return None


def check_python():
    v = sys.version_info
    vs = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 8):
        print(f"{OK} Python {vs}")
    else:
        print(f"{NO} Python {vs}（需要 ≥ 3.8）")
        problems.append("Python 版本过低：升级到 3.8+（推荐 3.10+）")


def check_pillow():
    try:
        import PIL
        print(f"{OK} Pillow {PIL.__version__}")
        return True
    except ImportError:
        pass
    # 自动切换的那个环境是否存在
    alt = os.path.expanduser("~/.workbuddy/binaries/python/envs/pillow/bin/python")
    if os.path.exists(alt):
        r = run([alt, "-c", "import PIL;print(PIL.__version__)"])
        if r and r.returncode == 0:
            print(f"{OK} Pillow {r.stdout.strip()}（在 {alt}）")
            return True
    print(f"{NO} Pillow 未安装（裁掉公众号水印需要它）")
    problems.append(
        "安装 Pillow：\n"
        "    pip3 install Pillow\n"
        "    # 或用 WorkBuddy 自带环境（很多机器已有）：\n"
        "    ~/.workbuddy/binaries/python/envs/pillow/bin/python -c 'import PIL;print(PIL.__version__)'"
    )
    return False


def check_chrome():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    found = [p for p in candidates if os.path.exists(p)]
    if not found:
        for name in ("google-chrome", "chromium", "chrome"):
            p = shutil.which(name)
            if p:
                found.append(p)
                break
    if found:
        r = run([found[0], "--version"])
        ver = (r.stdout or "").strip() if r else ""
        print(f"{OK} Chrome {ver}  ({found[0]})")
    else:
        print(f"{NO} 未找到 Chrome / Chromium（渲染卡片 PNG 需要）")
        problems.append(
            "安装 Chrome：\n"
            "    macOS: https://www.google.com/chrome/  或  brew install --cask google-chrome\n"
            "    Ubuntu/Debian: sudo apt install chromium-browser\n"
            "    Windows: https://www.google.com/chrome/"
        )


def check_ego():
    exe = shutil.which("ego-browser") or os.path.expanduser("~/.local/bin/ego-browser")
    if not os.path.exists(exe) and not shutil.which("ego-browser"):
        print(f"{NO} 未找到 ego-browser（抓公众号、发小红书都靠它）")
        problems.append(
            "安装 ego-browser（ego-lite）：\n"
            "    sh ~/.workbuddy/skills/ego-browser/scripts/install.sh\n"
            "    # 装完确认：ego-browser --version\n"
            "    # 然后手动在 ego-lite 浏览器里登录 mp.weixin.qq.com 和 creator.xiaohongshu.com"
        )
        return
    r = run(["ego-browser", "--version"])
    out = ((r.stdout or "") + (r.stderr or "")).strip() if r else ""
    first = out.splitlines()[0] if out else ""
    print(f"{OK} ego-browser {first}")
    if "ego-lite" not in out.lower() and "chromium" not in out.lower():
        print(f"{WARN} ego-browser 能跑，但 ego-lite 运行时可能没启动")


def check_xhs_skill():
    p = os.path.expanduser("~/.workbuddy/skills/xhs-image-note-release/scripts/publish_note.sh")
    if os.path.exists(p):
        print(f"{OK} xhs-image-note-release（发布底座）")
    else:
        print(f"{NO} 缺少 xhs-image-note-release skill（真正执行发布动作的底座）")
        problems.append(
            "安装 xhs-image-note-release：\n"
            "    从 https://github.com/Songhonglei/better-office-work 获取，\n"
            "    或直接在 WorkBuddy 里说「安装 xhs-image-note-release skill」"
        )


def check_fonts():
    """中文字体：缺了会渲染成方框，但不阻断流程"""
    if system == "Darwin":
        probe = [
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        hit = [p for p in probe if os.path.exists(p)]
        if hit:
            print(f"{OK} 中文字体（{len(hit)} 个候选命中），宋体/黑体可用")
        else:
            print(f"{WARN} 没探测到常见中文字体，卡片可能出方框")
            warnings.append("中文字体：macOS 一般在系统自带，若卡片是方框请检查字体册")
    elif system == "Linux":
        r = run(["fc-list", ":lang=zh"])
        if r and r.returncode == 0 and r.stdout.strip():
            n = len(r.stdout.strip().splitlines())
            print(f"{OK} 中文字体 {n} 个（fontconfig 可查）")
        else:
            print(f"{WARN} 未探测到中文字体，卡片会出方框")
            warnings.append(
                "安装中文字体（Linux 必做）：\n"
                "    sudo apt install fonts-noto-cjk fonts-wqy-zenhei"
            )
    else:
        print(f"{WARN} {system}：请确认系统已安装中文宋体/黑体，否则卡片出方框")
        warnings.append("Windows 一般自带微软雅黑/宋体，若出方框请检查字体设置")


def check_webfont():
    """gufeng/brush/mags/dossier 四套字体要拉 webfont；不通只是回退到系统字体"""
    url = "https://fonts.font.im/css2?family=ZCOOL+XiaoWei&display=swap"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310
            ok = r.status == 200
    except Exception:  # noqa: BLE001
        ok = False
    if ok:
        print(f"{OK} 字体 CDN（fonts.font.im）可达，gufeng/brush/mags/dossier 可用")
    else:
        print(f"{WARN} 字体 CDN 不可达：四套 webfont 方案会回落到系统宋体/黑体")
        warnings.append(
            "字体 CDN：gufeng/brush/mags/dossier 走 fonts.font.im，"
            "网络不通时自动回落系统字体，仅气质差异消失，不影响出图"
        )


def check_font_cache():
    """特色字体缓存目录（gufeng/qingke/brush 用），不可写只影响出图速度与离线"""
    d = os.path.join(os.path.expanduser("~"), ".cache", "mp2xhs", "fonts")
    if os.path.isdir(d):
        n = len([f for f in os.listdir(d) if f.endswith((".ttf", ".otf", ".woff2"))])
        if n:
            print(f"{OK} 特色字体缓存 {n} 个（{d}）")
            return
    try:
        os.makedirs(d, exist_ok=True)
        print(f"{OK} 字体缓存目录可写（尚空，首次渲染会自动下载）")
    except OSError as e:
        print(f"{WARN} 字体缓存目录不可写：{e}")
        warnings.append(
            "字体缓存：gufeng/qingke/brush 首次渲染要下载字体到 ~/.cache/mp2xhs/fonts，"
            "目录不可写时会回落到 CDN 在线字体（仍能出图，只是慢且依赖网络）"
        )


def check_login_hint():
    print(f"{WARN} 登录态无法自动检测，请确认在 ego-lite 里已登录：")
    print("      · mp.weixin.qq.com（公众号后台，抓文章用）")
    print("      · creator.xiaohongshu.com（小红书创作平台，发布用）")


def main():
    print("=" * 52)
    print(f" mp-article-to-xhs 依赖自检  ({system})")
    print("=" * 52)
    check_python()
    check_pillow()
    check_chrome()
    check_ego()
    check_xhs_skill()
    check_fonts()
    check_webfont()
    check_font_cache()
    print("-" * 52)
    check_login_hint()

    print("-" * 52)
    if problems:
        print(f"{NO} 有 {len(problems)} 项必需依赖未满足：\n")
        for i, p in enumerate(problems, 1):
            print(f"{i}. {p}\n")
    if warnings:
        print(f"{WARN} 提醒 {len(warnings)} 项：")
        for w in warnings:
            print(f"   · {w}")
        print()
    if not problems:
        print(f"{OK} 必需依赖齐全，可以直接用。")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
