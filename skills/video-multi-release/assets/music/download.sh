#!/usr/bin/env bash
# 一键重建 BGM 曲库（~87MB，10 首 mp3 不入 git，由本脚本负责下载）
# 来源: incompetech (Kevin MacLeod)，CC-BY 4.0，署名模板见同目录 README.md
# 用法: bash assets/music/download.sh   （在 skill 根目录或任意位置执行均可）

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="https://incompetech.com/music/royalty-free/mp3-royaltyfree"

TRACKS=(
  "Sovereign"
  "Crossing the Divide"
  "Impact Lento"
  "Frost Waltz"
  "Ossuary 1 - A Beginning"
  "Floating Cities"
  "Heartbreaking"
  "Meditation Impromptu 02"
  "Reawakening"
  "Long Note Two"
)

echo "==> 下载 ${#TRACKS[@]} 首到 $DIR"
FAIL=0
for t in "${TRACKS[@]}"; do
  OUT="$DIR/$t.mp3"
  if [ -s "$OUT" ] && ffprobe -v error "$OUT" >/dev/null 2>&1; then
    echo "  = 已存在，跳过: $t"
    continue
  fi
  ENC=$(printf '%s' "$t" | sed 's/ /%20/g')
  if curl -sf --max-time 180 -o "$OUT" "$BASE/$ENC.mp3" \
     && ffprobe -v error "$OUT" >/dev/null 2>&1; then
    SZ=$(( $(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT") / 1024 / 1024 ))
    echo "  + 已下载: $t (${SZ}MB)"
  else
    echo "  x 失败: $t" >&2
    FAIL=$((FAIL + 1))
  fi
done

if [ "$FAIL" -ne 0 ]; then
  echo "==> $FAIL 首下载失败，重跑本脚本可续传" >&2
  exit 1
fi
echo "==> 曲库就绪。注意：发布视频需在简介附署名（见 README.md）"
