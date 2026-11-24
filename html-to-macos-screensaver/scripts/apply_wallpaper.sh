#!/bin/bash
# apply_wallpaper.sh — 把 HTML 渲染成壁纸 PNG 并设为 macOS 桌面壁纸
# 用法: apply_wallpaper.sh <html文件> [输出名] [--no-apply]
set -euo pipefail

HTML="${1:?缺少 HTML 文件路径}"
NAME="${2:-}"
APPLY=1
[ "${2:-}" = "--no-apply" ] && { APPLY=0; NAME=""; }
[ "${3:-}" = "--no-apply" ] && APPLY=0

[ -f "$HTML" ] || { echo "✗ 找不到 HTML: $HTML"; exit 1; }
command -v swiftc >/dev/null || { echo "✗ 需要 Xcode Command Line Tools: xcode-select --install"; exit 1; }

HTML="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"
DIR="$(dirname "$HTML")"
NAME="${NAME:-$(basename "$HTML" .html)}"
[[ "$NAME" != */* ]] || { echo '壁纸名不能带目录' >&2; exit 2; }
OUT="$DIR/$NAME-wallpaper.png"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 屏幕逻辑分辨率 ×2（Retina）；Finder 授权被拒时退回安全默认值
SIZE="$(swift -e 'import AppKit; if let s = NSScreen.main { print(Int(s.frame.width * s.backingScaleFactor), Int(s.frame.height * s.backingScaleFactor)) }' 2>/dev/null || true)"
read -r W H <<< "${SIZE:-2560 1440}"
W="${WALLPAPER_WIDTH:-$W}"
H="${WALLPAPER_HEIGHT:-$H}"
[[ "$W" =~ ^[1-9][0-9]*$ && "$H" =~ ^[1-9][0-9]*$ ]] || { echo '无效的壁纸尺寸' >&2; exit 2; }

echo "· 编译截图工具"
swiftc -O -o "$WORK/snapshot" "$SKILL_DIR/assets/snapshot.swift" -framework Cocoa -framework WebKit

echo "· 渲染 ${W}x${H} 壁纸（等待页面动画稳定 3s）"
if ! "$WORK/snapshot" "$HTML" "$WORK/wallpaper.png" "$W" "$H" 3; then
  echo "✗ 截图失败（页面可能崩溃或超时）"; exit 1
fi
[ -s "$WORK/wallpaper.png" ] || { echo "截图失败" >&2; exit 1; }
mv -f "$WORK/wallpaper.png" "$OUT"

if [ "$APPLY" = 1 ]; then
  echo "· 设为桌面壁纸"
  # 首次执行会弹出"允许控制 System Events"的授权框，需要用户点允许
  osascript - "$OUT" <<'APPLESCRIPT'
on run argv
  tell application "System Events" to set picture of every desktop to (POSIX file (item 1 of argv))
end run
APPLESCRIPT
  echo "✓ 壁纸已应用"
else
  echo "✓ 壁纸已生成（未应用）"
fi
echo "  文件: $OUT"
