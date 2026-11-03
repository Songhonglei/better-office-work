#!/usr/bin/env bash
# 视频多平台发布 —— 入口层
#
# 只负责：参数校验、平台编排、日志、退出码汇总。
# 浏览器操作全在 *.mjs 里，便于单独 node --check 和排障。
#
# 用法:
#   PLATFORMS=douyin,channels \
#   VIDEO=/abs/path/video.mp4 \
#   TITLE="四十岁以后，我不再跑那么快了" \
#   DESC='正文…' \
#   TOPICS="人生感悟,人到中年" \
#   MODE=stage \
#     bash release.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PLATFORMS="${PLATFORMS:-douyin,channels}"
VIDEO="${VIDEO:-}"
TITLE="${TITLE:-}"
DESC="${DESC:-}"
TOPICS="${TOPICS:-}"
COVER="${COVER:-}"
MODE="${MODE:-stage}"
KEEP_ON_FAIL="${KEEP_ON_FAIL:-1}"
# 复用上次失败留下的现场（页面已填好）：SPACE_ID=65 这样传。
# 不传就按名字新建；若同名空间还在且归属用户，脚本会报 E_SPACE_OWNED 并给出两条出路。
SPACE_ID="${SPACE_ID:-}"

LOG="/tmp/video-release-$(date +%Y%m%d-%H%M%S)-$$.log"
exec > >(tee -a "$LOG") 2>&1

usage_fail() {
  echo ""
  echo "=== FAILED ==="
  echo "platform : -"
  echo "step     : validate-params"
  echo "code     : $1"
  echo "exit     : 10"
  echo "message  : $2"
  echo "what_now :"
  shift 2
  local i=1
  for s in "$@"; do echo "  $i. $s"; i=$((i + 1)); done
  echo "=== END FAILED ==="
  echo ""
  echo "日志: $LOG"
  exit 10
}

[ -n "$VIDEO" ] || usage_fail "E_PARAM_VIDEO" "缺少 VIDEO" \
  "VIDEO 必须是绝对路径的 mp4" \
  "例: VIDEO=/Users/you/out/video.mp4 bash release.sh"

[ -f "$VIDEO" ] || usage_fail "E_VIDEO_NOT_FOUND" "视频文件不存在: $VIDEO" \
  "检查路径拼写" "先确认文件确实生成过"

case "$VIDEO" in
  *.mp4|*.MP4|*.mov|*.MOV|*.m4v) ;;
  *) usage_fail "E_VIDEO_FORMAT" "视频格式不支持: $VIDEO" \
       "两平台都建议 mp4（H.264）" "用 ffmpeg 转一次: ffmpeg -i in.mov -c:v libx264 -c:a aac out.mp4" ;;
esac

[ -n "$TITLE" ] || usage_fail "E_PARAM_TITLE" "缺少 TITLE" \
  "视频号短标题最多 16 字，抖音标题最多 30 字" \
  "脚本会按平台自动截断并提示"

case "$MODE" in
  stage|draft|publish) ;;
  *) usage_fail "E_PARAM_MODE" "MODE 只能是 stage / draft / publish，当前: $MODE" \
       "stage=填好不提交（推荐先跑这个）" \
       "draft=存草稿（抖音不支持，会退化为 stage）" \
       "publish=直接发布" ;;
esac

IFS=',' read -r -a PLATFORM_ARRAY <<< "$PLATFORMS"
[ "${#PLATFORM_ARRAY[@]}" -gt 0 ] || usage_fail "E_PARAM_PLATFORMS" "PLATFORMS 为空" \
  "可选: douyin, channels"

for p in "${PLATFORM_ARRAY[@]}"; do
  case "$p" in
    douyin|channels|xhs) ;;
    *) usage_fail "E_UNKNOWN_PLATFORM" "未知平台: $p" "可选: douyin / channels / xhs" ;;
  esac
done

# 封面只在部分平台生效，传了不支持的会明确告知，避免以为设置成功
if [ -n "$COVER" ]; then
  [ -f "$COVER" ] || usage_fail "E_COVER_NOT_FOUND" "封面图不存在: $COVER" \
    "COVER 是可选参数，不传就用平台默认首帧" \
    "只有小红书会用它，视频号和抖音的封面在各自后台设"
fi

# 字数前置校验：能在启动浏览器之前发现的问题，不要留到浏览器里
TITLE_LEN=$(python3 -c "import sys; print(len(sys.argv[1]))" "$TITLE")
DESC_LEN=$(python3 -c "import sys; print(len(sys.argv[1]))" "$DESC")
echo "=========================================="
echo "  视频多平台发布"
echo "  平台: ${PLATFORMS}"
echo "  视频: $(basename "$VIDEO")  $(du -h "$VIDEO" | cut -f1)"
echo "  标题: ${TITLE}（${TITLE_LEN} 字）"
echo "  描述: ${DESC_LEN} 字"
echo "  话题: ${TOPICS:-（无）}"
echo "  模式: ${MODE}"
if [ -n "$SPACE_ID" ]; then echo "  空间: ${SPACE_ID}（复用现场）"; fi
echo "  日志: ${LOG}"
echo "=========================================="

echo "$DESC" | python3 -c "import sys; d=sys.stdin.read().rstrip('\n'); exit(0 if len(d)<=1000 else 1)" \
  || usage_fail "E_DESC_TOO_LONG" "描述超过 1000 字（当前 ${DESC_LEN}）" \
       "两个平台的描述上限都是 1000 字" \
       "精简后再跑"

# 话题转 JSON 数组
TOPICS_JSON=$(python3 -c "
import sys, json
raw = sys.argv[1] if len(sys.argv) > 1 else ''
items = [t.strip().lstrip('#') for t in raw.split(',') if t.strip()]
print(json.dumps(items, ensure_ascii=False))
" "$TOPICS")

EXIT_CODE=0
SUMMARY=""

for platform in "${PLATFORM_ARRAY[@]}"; do
  EXIT_CODE=0
  echo ""
  echo "────────────  ${platform}  ────────────"

  PARAMS_JSON=$(python3 -c "
import json, sys
print(json.dumps({
    'platform': sys.argv[1],
    'video': sys.argv[2],
    'title': sys.argv[3],
    'desc': sys.argv[4],
    'topics': json.loads(sys.argv[5]),
    'mode': sys.argv[6],
    'keepOnFail': sys.argv[7] == '1',
    'coverVertical': sys.argv[8],
    'spaceId': sys.argv[9] or None,
}, ensure_ascii=False))
" "$platform" "$VIDEO" "$TITLE" "$DESC" "$TOPICS_JSON" "$MODE" "$KEEP_ON_FAIL" "$COVER" "$SPACE_ID")

  MJS="$SCRIPTS_DIR/${platform}.mjs"
  [ -f "$MJS" ] || { echo "缺少脚本: $MJS"; EXIT_CODE=11; SUMMARY="$SUMMARY\n  $platform  失败(11) 缺脚本"; continue; }

  # 把参数作为常量前置拼进去：ego-browser nodejs 不继承 shell 环境变量
  EGO_OUT="$(mktemp)"
  set +e
  {
    printf 'const PARAMS = %s;\n' "$PARAMS_JSON"
    cat "$MJS"
  } | ego-browser nodejs 2>&1 | tee "$EGO_OUT"
  RC_PIPE=("${PIPESTATUS[@]}")
  set -e

  # ego-browser 会把 node 的退出码统一改写成自己进程的 1，真实码只打了行日志：
  #   ego's nodejs process exited with code 11.
  # 所以 $? 不可信。优先取 FAILED 块里脚本自己声明的 exit，其次取那行日志，最后才退回管道码。
  RC_BLOCK=$(grep -oE '^exit     : [0-9]+' "$EGO_OUT" | tail -1 | grep -oE '[0-9]+$' || true)
  RC_MSG=$(grep -oE 'exited with code [0-9]+' "$EGO_OUT" | tail -1 | grep -oE '[0-9]+$' || true)
  rm -f "$EGO_OUT"

  if [ -n "$RC_BLOCK" ]; then
    EXIT_CODE=$RC_BLOCK
  elif [ -n "$RC_MSG" ]; then
    EXIT_CODE=$RC_MSG
  else
    EXIT_CODE=${RC_PIPE[1]:-0}
  fi

  if [ "$EXIT_CODE" -eq 0 ]; then
    SUMMARY="$SUMMARY\n  $platform  ✅ 成功"
  else
    SUMMARY="$SUMMARY\n  $platform  ❌ 失败(退出码 $EXIT_CODE)"
    # 默认第一个平台失败就停，避免带着问题继续发下一个。
    # 想「能发的先发」就设 CONTINUE_ON_FAIL=1。
    if [ "${CONTINUE_ON_FAIL:-0}" != "1" ]; then
      SUMMARY="$SUMMARY\n  （已停止，后续平台未执行；要跳过失败继续发，设 CONTINUE_ON_FAIL=1）"
      break
    fi
  fi
done

echo ""
echo "=========================================="
echo -e "  结果${SUMMARY}"
echo "  日志: $LOG"
echo "=========================================="
exit "$EXIT_CODE"
