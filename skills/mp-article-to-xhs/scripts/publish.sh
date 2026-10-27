#!/bin/bash
# 发布包装：默认【草稿箱】，只有显式 --publish 才直接发布
#
# 用法：
#   bash publish.sh --dir ./cards --title "标题" --body-file body.txt \
#        --topics "历史冷知识,三星堆" [--images 01.png,02.png] [--publish] [--dry-run]
#
# 不带 --publish 一律走 draft（推草稿箱），由用户自己去点发布。
set -euo pipefail

DIR=""
TITLE=""
BODY_FILE=""
TOPICS=""
IMAGES=""
MODE="draft"
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)        DIR="$2"; shift 2 ;;
    --title)      TITLE="$2"; shift 2 ;;
    --body-file)  BODY_FILE="$2"; shift 2 ;;
    --topics)     TOPICS="$2"; shift 2 ;;
    --images)     IMAGES="$2"; shift 2 ;;
    --dry-run)    DRY_RUN="1"; shift ;;
    --publish)    MODE="publish"; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ -z "$DIR" ] || [ -z "$TITLE" ] || [ -z "$BODY_FILE" ]; then
  echo "ERROR: --dir / --title / --body-file 必填"; exit 1
fi

# 预检：publish_note.sh 会把标题塞进 JS 单引号、正文塞进模板字符串，
# 这两类字符会让它在传完图之后才失败，白等两分钟，所以提前拦
if printf '%s' "$TITLE" | grep -q "'"; then
  echo "ERROR: 标题不能包含英文单引号 '（会中断发布脚本），换成「」或直接删掉"; exit 1
fi
if grep -q '`' "$BODY_FILE" 2>/dev/null || grep -qF '${' "$BODY_FILE" 2>/dev/null; then
  echo "ERROR: 正文不能包含反引号或 \${（会中断发布脚本），已拦下"; exit 1
fi

IMAGE_DIR="$(cd "$DIR" && pwd)"

# 未指定图片则自动收集目录下全部 png 并按文件名排序
if [ -z "$IMAGES" ]; then
  IMAGES=$(cd "$IMAGE_DIR" && ls *.png 2>/dev/null | sort | paste -sd, -)
fi
IMG_COUNT=$(echo "$IMAGES" | tr ',' '\n' | wc -l | tr -d ' ')
if [ "$IMG_COUNT" -gt 18 ]; then
  echo "ERROR: 小红书图文最多 18 张，当前 $IMG_COUNT 张，请精简卡片"; exit 1
fi

# 正文换行转义成字面 \n（publish_note.sh 内部会还原）
BODY=$(python3 - "$BODY_FILE" <<'PY'
import re, sys
s = open(sys.argv[1], encoding='utf-8').read().strip()
s = re.sub(r'\n{3,}', '\n\n', s)
sys.stdout.write(s.replace('\n', '\\n'))
PY
)

echo "=========================================="
echo " 模式: $MODE$([ "$MODE" = "draft" ] && echo ' (推草稿箱，不对外发布)')"
echo " 图片: $IMG_COUNT 张  $IMAGE_DIR"
echo " 标题: $TITLE ($(python3 -c "print(len('''$TITLE'''))") 字)"
echo " 正文: $(wc -m < "$BODY_FILE" | tr -d ' ') 字"
echo "=========================================="

if [ "$MODE" = "publish" ]; then
  echo "⚠️  直接发布模式：内容会立刻对外可见"
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "（dry-run：只核对参数，不执行发布）"
  exit 0
fi

export IMAGE_DIR IMAGES TITLE BODY TOPICS MODE
bash "$HOME/.workbuddy/skills/xhs-image-note-release/scripts/publish_note.sh"
