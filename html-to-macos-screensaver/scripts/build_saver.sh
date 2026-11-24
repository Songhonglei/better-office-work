#!/bin/bash
set -euo pipefail

HTML="${1:?用法: build_saver.sh HTML 英文名 [显示名] [--build-only|--no-open]}"
NAME="${2:?请提供屏保英文名}"
shift 2
DISPLAY="$NAME"
if [[ $# -gt 0 && "$1" != --* ]]; then
  DISPLAY="$1"
  shift
fi
INSTALL=1
OPEN_SETTINGS=1
for option in "$@"; do
  case "$option" in
    --build-only) INSTALL=0 ;;
    --no-open) OPEN_SETTINGS=0 ;;
    *) echo "未知选项 $option" >&2; exit 2 ;;
  esac
done

[[ "$NAME" =~ ^[A-Za-z][A-Za-z0-9]*$ ]] || { echo '英文名须以字母开头，只含字母数字' >&2; exit 2; }
[[ -f "$HTML" ]] || { echo 'HTML 文件不存在' >&2; exit 2; }
HTML="$(cd "$(dirname "$HTML")" && pwd)/$(basename "$HTML")"
SRC_DIR="$(dirname "$HTML")"
ENTRY="$(basename "$HTML")"
case "$ENTRY" in
  *.[hH][tT][mM]|*.[hH][tT][mM][lL]) ;;
  *) echo '请选择 .html 或 .htm 文件' >&2; exit 2 ;;
esac
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
SAVER="$SRC_DIR/$NAME.saver"
INSTALL_PATH="$HOME/Library/Screen Savers/$NAME.saver"
[[ ! -e "$SAVER" && ! -L "$SAVER" ]] || { echo "输出已存在，请更换名称或移走原文件：$SAVER" >&2; exit 1; }
if [[ "$INSTALL" == 1 && ( -e "$INSTALL_PATH" || -L "$INSTALL_PATH" ) ]]; then
  echo "同名屏保已安装：$INSTALL_PATH" >&2
  exit 1
fi
WORK="$(mktemp -d "$SRC_DIR/.html-saver.XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT
BUNDLE="$WORK/$NAME.saver"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

find "$SRC_DIR" -maxdepth 1 -type f ! -name ".*" \
  \( -iname "*.html" -o -iname "*.htm" -o -iname "*.css" -o -iname "*.js" -o -iname "*.mjs" \
     -o -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.gif" -o -iname "*.svg" \
     -o -iname "*.webp" -o -iname "*.ico" -o -iname "*.json" -o -iname "*.woff" -o -iname "*.woff2" \
     -o -iname "*.ttf" -o -iname "*.otf" -o -iname "*.mp4" -o -iname "*.webm" -o -iname "*.mp3" -o -iname "*.wav" \) \
  -exec cp {} "$BUNDLE/Contents/Resources/" \;
[[ -f "$BUNDLE/Contents/Resources/$ENTRY" ]] || { echo '入口页面未复制，请检查文件类型和名称' >&2; exit 1; }

python3 - "$PROJECT/assets/Info.plist.tpl" "$BUNDLE/Contents/Info.plist" "$NAME" "$DISPLAY" "$ENTRY" <<'PY2'
import plistlib
import sys

template, output, module, display, entry = sys.argv[1:]
with open(template, 'rb') as source:
    info = plistlib.load(source)
info = {key: value.replace('__MODULE__', module).replace('__DISPLAY__', display)
        if isinstance(value, str) else value for key, value in info.items()}
info['EntryFile'] = entry
with open(output, 'wb') as target:
    plistlib.dump(info, target)
PY2
cp "$PROJECT/assets/main.swift.tpl" "$WORK/main.swift"
cp "$PROJECT/assets/loadtest.swift.tpl" "$WORK/loadtest.swift"
swiftc -emit-library -module-name "$NAME" -o "$BUNDLE/Contents/MacOS/$NAME" "$WORK/main.swift" \
  -framework ScreenSaver -framework WebKit
swiftc -o "$WORK/loadtest" "$WORK/loadtest.swift" -framework ScreenSaver
"$WORK/loadtest" "$BUNDLE"
mv "$BUNDLE" "$SAVER"
echo "已生成：$SAVER"
if [[ "$INSTALL" == 1 ]]; then
  mkdir -p "$(dirname "$INSTALL_PATH")"
  cp -R "$SAVER" "$INSTALL_PATH"
  echo "已安装：$INSTALL_PATH"
  if [[ "$OPEN_SETTINGS" == 1 ]]; then
    open "x-apple.systempreferences:com.apple.ScreenSaver-Settings.extension" || true
  fi
fi
