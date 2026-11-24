#!/bin/bash
# build_dynamic_wallpaper.sh — 把 HTML 渲染成多时段画面，打包成 macOS 动态壁纸(.heic)并应用
# 页面可用 window.__FORCE_HOUR__ 读取被钉住的小时数（0-23）来切换配色/场景。
# 用法: build_dynamic_wallpaper.sh <html文件> [壁纸名] [--no-apply]
set -euo pipefail

HTML="${1:?缺少 HTML 文件路径}"
WPNAME="${2:-dynamic}"
APPLY=1
[ "${3:-}" = "--no-apply" ] && APPLY=0

[ -f "$HTML" ] || { echo "✗ 找不到 HTML: $HTML"; exit 1; }
command -v swiftc >/dev/null || { echo "✗ 需要 Xcode Command Line Tools"; exit 1; }

HTML="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"
DIR="$(dirname "$HTML")"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WALLPAPPER="${WALLPAPPER:-$(command -v wallpapper || true)}"
[ -x "$WALLPAPPER" ] || { echo "请安装 wallpapper 或指定 WALLPAPPER" >&2; exit 1; }

WORK="$(mktemp -d "$DIR/.wallpaper-build.XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# 屏幕逻辑分辨率 ×2（Retina）；Finder 授权被拒时退回安全默认值
SIZE="$(swift -e 'import AppKit; if let s = NSScreen.main { print(Int(s.frame.width * s.backingScaleFactor), Int(s.frame.height * s.backingScaleFactor)) }' 2>/dev/null || true)"
read -r W H <<< "${SIZE:-2560 1440}"
W="${WALLPAPER_WIDTH:-$W}"
H="${WALLPAPER_HEIGHT:-$H}"
[[ "$W" =~ ^[1-9][0-9]*$ && "$H" =~ ^[1-9][0-9]*$ ]] || { echo '无效的壁纸尺寸' >&2; exit 2; }

echo "· 编译截图工具"
swiftc -O -o "$WORK/snapshot" "$SKILL_DIR/assets/snapshot.swift" -framework Cocoa -framework WebKit

CUR_H=$(date +%-H)
for label in night dawn day dusk; do
  case "$label" in
    night)  renderH=2 ;;
    dawn)   renderH=7 ;;
    day)    renderH=12 ;;
    dusk)   renderH=19 ;;
  esac
  echo "· 渲染 ${label}（钉住 ${renderH} 时）"
  "$WORK/snapshot" "$HTML" "$WORK/$label.png" "$W" "$H" 3 "window.__FORCE_HOUR__=$renderH;"
  [ -s "$WORK/$label.png" ] || { echo "✗ $label 渲染失败"; exit 1; }
done

# primary = 当前小时落入的时段；night 图复用于 0 点与 21 点两个切换节点
python3 - "$WORK" "$WPNAME" "$CUR_H" <<'PY'
import json, sys, os
work, name, curh = sys.argv[1], sys.argv[2], int(sys.argv[3])
slots = [("night.png",0),("dawn.png",5),("day.png",8),("dusk.png",17),("night.png",21)]
entries = []
primary_idx = 0
for i,(f,t) in enumerate(slots):
    e = {"fileName": f, "time": f"{t:02d}:00:00"}
    if f == "day.png":   e["isForLight"] = True
    if f == "night.png" and i == 0: e["isForDark"] = True
    if t <= curh: primary_idx = i
    entries.append(e)
entries[primary_idx]["isPrimary"] = True
with open(os.path.join(work, "wallpaper.json"), "w") as fp:
    json.dump(entries, fp, indent=2)
print("primary:", entries[primary_idx]["fileName"], entries[primary_idx]["time"])
PY

echo "· 打包动态壁纸"
[[ "$WPNAME" != */* ]] || { echo '壁纸名不能带目录' >&2; exit 2; }
OUT="$DIR/$WPNAME.heic"
"$WALLPAPPER" -i "$WORK/wallpaper.json" -o "$WORK/wallpaper.heic"
[ -s "$WORK/wallpaper.heic" ] || { echo "打包失败" >&2; exit 1; }
mv -f "$WORK/wallpaper.heic" "$OUT"

if [ "$APPLY" = 1 ]; then
  echo "· 设为桌面壁纸（系统会自动识别为动态壁纸）"
  osascript - "$OUT" <<'APPLESCRIPT'
on run argv
  tell application "System Events" to set picture of every desktop to (POSIX file (item 1 of argv))
end run
APPLESCRIPT
  echo "✓ 动态壁纸已应用"
else
  echo "✓ 动态壁纸已生成（未应用）"
fi
echo "  文件: $OUT"
