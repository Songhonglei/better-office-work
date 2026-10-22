#!/usr/bin/env bash
# 构建「番茄钟」独立产物：
#   1. dist/index.html — 注入 standalone 补丁（全出血渲染，消除圆角毛边，适配深/浅主题）
#   2. 番茄钟.app      — 原生 macOS 应用（WKWebView 壳 + 自绘图标）
# 用法: ./build.sh   （需要 macOS + Xcode Command Line Tools）
set -euo pipefail

cd "$(dirname "$0")"
SRC="index.html"
DIST_DIR="dist"
APP="$DIST_DIR/番茄钟.app"
BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT

# ---------- 1. standalone HTML ----------
# 补丁说明：
#  - viewport-fit=cover        页面延伸到窗口标题栏下方（WKWebView safe-area 默认会把页面压到标题栏下，造成卡片圆角与窗口圆角错位形成毛边）
#  - .card border-radius:0     窗口自身负责圆角，不再双重圆角
#  - header 顶部加 22px        为红绿灯按钮留出悬浮空间（深色/浅色主题下都清晰可见）
#  - body 底色                 兜底任何未绘制像素
mkdir -p "$DIST_DIR"
python3 - "$SRC" "$DIST_DIR/index.html" <<'PY'
import sys, re

src, dst = sys.argv[1], sys.argv[2]
html = open(src, encoding="utf-8").read()

html = html.replace(
    '<meta name="viewport" content="width=device-width, initial-scale=1" />',
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />',
    1,
)

patch = """<style id="standalone-fix">
  html,body{background:#05070F;}
  .card{border-radius:0 !important;}
  .card::after{border-radius:0;}
  header{padding-top:22px;}
</style>
</head>"""
html = html.replace("</head>", patch, 1)

open(dst, "w", encoding="utf-8").write(html)
print("patched ->", dst)
PY

# ---------- 2. 图标 ----------
python3 - icon.png <<'PY'
from PIL import Image, ImageDraw, ImageFilter
import math, random

S = 512
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
bd = ImageDraw.Draw(bg)
bd.rounded_rectangle([8, 8, S-8, S-8], radius=110, fill=(13, 18, 48, 255))
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([S*0.18, S*0.10, S*0.82, S*0.58], fill=(48, 58, 130, 90))
glow = glow.filter(ImageFilter.GaussianBlur(60))
bg = Image.alpha_composite(bg, glow)
draw = ImageDraw.Draw(bg)

cx, cy = S/2, S*0.46
rx, ry = S*0.30, S*0.185
c1, c2, c3 = (0x8F,0xD8,0xFF), (0xEA,0xF6,0xFF), (0xA7,0x8B,0xFA)
def lerp(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))
N = 120
for i in range(N):
    t = i / (N-1)
    col = lerp(c1, c2, t/0.5) if t < 0.5 else lerp(c2, c3, (t-0.5)/0.5)
    pts = []
    for k in range(9):
        a2 = math.pi*2*((i + k/8) / N)
        pts.append((cx + rx*math.cos(a2), cy + ry*math.sin(a2)))
    for w, alpha in ((16, 60), (9, 130), (4, 255)):
        overlay = Image.new("RGBA", (S, S), (0,0,0,0))
        od = ImageDraw.Draw(overlay)
        od.line(pts, fill=col+(alpha,), width=w, joint="curve")
        bg = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(bg)

draw.ellipse([cx-26, cy-26, cx+26, cy+26], outline=(234, 246, 255, 255), width=6)
a = math.radians(-30)
ox, oy = cx + rx*math.cos(a), cy + ry*math.sin(a)
draw.ellipse([ox-9, oy-9, ox+9, oy+9], fill=(143, 216, 255, 255))
random.seed(7)
for _ in range(40):
    x, y = random.uniform(30, S-30), random.uniform(30, S-30)
    r = random.uniform(1.2, 3.2)
    draw.ellipse([x-r, y-r, x+r, y+r], fill=(220, 234, 255, random.randint(60, 160)))

bg.save("icon.png")
icset = "AppIcon.iconset"
import os
os.makedirs(icset, exist_ok=True)
for px, name in [(1024,"icon_512x512@2x.png"),(512,"icon_512x512.png"),(512,"icon_256x256@2x.png"),
                 (256,"icon_256x256.png"),(256,"icon_128x128@2x.png"),(128,"icon_128x128.png"),
                 (64,"icon_64x64.png"),(64,"icon_32x32@2x.png"),(32,"icon_32x32.png"),(16,"icon_16x16.png")]:
    bg.resize((px, px), Image.LANCZOS).save(f"{icset}/{name}")
print("icon ready")
PY
iconutil -c icns AppIcon.iconset -o "$BUILD_TMP/AppIcon.icns"
rm -rf AppIcon.iconset

# ---------- 3. 编译 App ----------
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$DIST_DIR/index.html" "$APP/Contents/Resources/index.html"
cp Info.plist "$APP/Contents/Info.plist"
cp "$BUILD_TMP/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
swiftc -O main.swift -o "$APP/Contents/MacOS/tomato" -framework Cocoa -framework WebKit

echo "✅ build complete: $APP"
