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
#
# 新增可选项:
#   MAX_VIDEO_MB=40     视频超过该体积自动转码 final_web.mp4 再发（0 = 关闭）
#   RESUME=1            复用已填好的编辑页现场，跳过 reload 与重复上传
#   TOPICS / HOT_TOPICS 留空时取数据目录 config.json 的默认值

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PLATFORMS="${PLATFORMS:-douyin,channels}"
VIDEO="${VIDEO:-}"
TITLE="${TITLE:-}"
DESC="${DESC:-}"
TOPICS="${TOPICS:-}"
COVER="${COVER:-}"
COVER_HORIZONTAL="${COVER_HORIZONTAL:-}"
# 封面（可选）：
#   COVER —— 竖版(3:4)封面图路径，三个平台通用（抖音为尽力而为，失败只告警）
#   COVER_HORIZONTAL —— 横版(16:9)封面；留空时若 assets/card_01_h.png 存在则自动用作横屏封面
#     （该文件由 gen_cards.py --cover-h 生成，不是 --ratio horizontal）
# 热点话题（可选）：
#   HOT_TOPICS=auto —— 拉抖音热榜按 DESC 相关度自动挑（最多 HOT_TOPICS_MAX 个，默认 2）
#   HOT_TOPICS="词1,词2" —— 手动指定热点话题；留空则不关联热点
HOT_TOPICS="${HOT_TOPICS:-}"
HOT_TOPICS_MAX="${HOT_TOPICS_MAX:-2}"
MODE="${MODE:-stage}"
KEEP_ON_FAIL="${KEEP_ON_FAIL:-1}"
# 复用上次失败留下的现场（页面已填好）：SPACE_ID=65 这样传。
# 不传就按名字新建；若同名空间还在且归属用户，脚本会报 E_SPACE_OWNED 并给出两条出路。
SPACE_ID="${SPACE_ID:-}"
# RESUME=1：复用已填好的编辑页现场，跳过 Page.reload 与重复上传（抖音登录态撑不过刷新）
RESUME="${RESUME:-0}"

# publish 模式不允许复用旧任务空间：三个平台脚本发布成功后都不释放空间，
# 拿旧 space 重跑会重新上传 + 提交，造成同一条内容双发。
if [ "$MODE" = "publish" ] && [ -n "$SPACE_ID" ]; then
  echo "  ⚠ publish 模式忽略 SPACE_ID（复用旧现场有重复发布风险），改用新任务空间"
  SPACE_ID=""
fi

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

# 封面三平台通用；抖音是「尽力而为」，失败只告警不阻断（douyin.mjs setDouyinCover）
if [ -n "$COVER" ]; then
  [ -f "$COVER" ] || usage_fail "E_COVER_NOT_FOUND" "封面图不存在: $COVER" \
    "COVER 是可选参数，不传就用平台默认首帧（首帧通常就是 card_01）" \
    "小红书/视频号/抖音都会尝试设置；抖音失败只告警"

# ── 运行时默认配置（数据目录，升级 skill 不会清掉） ──────────────
CONFIG="${WB_SKILLS_DATA:-$HOME/space/skills-data}/video-multi-release/config.json"
read_cfg() {
  # 解析失败不能静默：原来 2>/dev/null + set -e 会让脚本无诊断地停在这一行。
  python3 -c "import json,sys,os; p=sys.argv[1]; k=sys.argv[2]; d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {}; v=d.get(k); print(v if isinstance(v,str) else (','.join(v) if isinstance(v,list) else ''))" "$CONFIG" "$1" || {
    echo "  ⚠ config.json 解析失败，已忽略默认值（$CONFIG）" >&2
    printf ''
  }
}
[ -n "$TOPICS" ] || TOPICS="$(read_cfg topics)"
[ -n "$HOT_TOPICS" ] || HOT_TOPICS="$(read_cfg hot_topics)"

# 曲库全部是 CC-BY 4.0（assets/music/README.md），对外发布必须在简介里署名。
# 这里只提醒、不改用户的 DESC —— 擅自追加文案属于意外副作用。
CFG_BGM="$(read_cfg bgm)"
MUSIC_DIR="${WB_SKILLS_DATA:-$HOME/space/skills-data}/video-multi-release/music"
if [ -n "$CFG_BGM" ]; then
  case "$CFG_BGM" in
    "$MUSIC_DIR"/*)
      case "$DESC" in
        *"Kevin MacLeod"*) ;;
        *) echo "  ⚠ BGM 来自 CC-BY 曲库（$(basename "$CFG_BGM")），对外发布需在简介末尾署名："
           echo "      音乐: <曲名> - Kevin MacLeod (incompetech.com) / CC BY 4.0" ;;
      esac
      ;;
  esac
fi

# ── 视频体积前置检查 ────────────────────────────────────────────
# 实测视频号上传 78MB 在 160 秒超时，压到 25MB 后 18 秒完成。
# 超阈值就自动转一份 final_web.mp4 并用它发，避免每次靠人记得压缩。
MAX_VIDEO_MB="${MAX_VIDEO_MB:-40}"
VIDEO_MB=$(du -m "$VIDEO" | cut -f1 | tr -d ' ')
if [ "${MAX_VIDEO_MB:-40}" != "0" ] && [ "$VIDEO_MB" -gt "$MAX_VIDEO_MB" ] 2>/dev/null; then
  WEB_VIDEO="$(dirname "$VIDEO")/final_web.mp4"
  # 缓存只在同一源视频下有效。源比压缩版新（换了片 / 重新渲染）就必须重转，
  # 否则「存在即复用」会把上一次的压缩版当成这次的内容发出去（实测可复现）。
  if [ ! -f "$WEB_VIDEO" ] || [ "$VIDEO" -nt "$WEB_VIDEO" ]; then
    echo "  视频 ${VIDEO_MB}MB 超过 ${MAX_VIDEO_MB}MB，正在转码压缩版…"
    ffmpeg -y -hide_banner -loglevel error -i "$VIDEO" \
      -c:v libx264 -preset medium -crf 24 -maxrate 2600k -bufsize 5200k \
      -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart "$WEB_VIDEO"
  else
    echo "  视频 ${VIDEO_MB}MB 超过 ${MAX_VIDEO_MB}MB，复用同源码的压缩版"
  fi
  VIDEO="$WEB_VIDEO"
  echo "  实际发布文件: $(basename "$VIDEO")  $(du -h "$VIDEO" | cut -f1)"
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
# ── 热点话题解析（在循环外做一次，结果全平台共用）──
HOT_JSON="[]"
if [ -n "$HOT_TOPICS" ] && [ -n "$DESC" ]; then
  if [ "$HOT_TOPICS" = "auto" ]; then
    HOT_PICKED=$(python3 "$SCRIPTS_DIR/hot_topics.py" --desc "$DESC" --pick "$HOT_TOPICS_MAX" --json 2>/dev/null || echo "[]")
  else
    HOT_PICKED=$(python3 -c "
import json, sys
print(json.dumps([{'word': w.strip(), 'hot': 0, 'score': 0} for w in sys.argv[1].split(',') if w.strip()], ensure_ascii=False))
" "$HOT_TOPICS")
  fi
  HOT_JSON="$HOT_PICKED"
  HOT_COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$HOT_JSON")
  echo "  热点话题: $HOT_JSON"
fi

# ── 横屏封面自动探测：video 同目录的 card_01_h.png（gen_cards.py --ratio horizontal 产物）──
COVER_H="$COVER_HORIZONTAL"
if [ -z "$COVER_H" ] && [ -n "$VIDEO" ]; then
  CAND="$(dirname "$VIDEO")/../assets/card_01_h.png"
  [ -f "$CAND" ] && COVER_H="$CAND"
fi

SUMMARY=""
FIRST_FAIL_RC=0        # CONTINUE_ON_FAIL=1 时保留第一个失败码，别被最后一个平台覆盖

for platform in "${PLATFORM_ARRAY[@]}"; do
  EXIT_CODE=0
  echo ""
  echo "────────────  ${platform}  ────────────"

  PARAMS_JSON=$(python3 -c "
import json, sys
# 话题合并：用户话题在前，热点话题在后，去重
topics = json.loads(sys.argv[5])
hot = json.loads(sys.argv[10])
have = set(topics)
for h in hot:
    w = h['word'].strip().lstrip('#')
    if w and w not in have:
        topics.append(w)
        have.add(w)
print(json.dumps({
    'platform': sys.argv[1],
    'video': sys.argv[2],
    'title': sys.argv[3],
    'desc': sys.argv[4],
    'topics': topics,
    'hotTopics': [h['word'] for h in hot],
    'mode': sys.argv[6],
    'keepOnFail': sys.argv[7] == '1',
    'coverVertical': sys.argv[8],
    'coverHorizontal': sys.argv[9] or None,
    'spaceId': sys.argv[11] or None,
    'resume': sys.argv[12] == '1',
}, ensure_ascii=False))
" "$platform" "$VIDEO" "$TITLE" "$DESC" "$TOPICS_JSON" "$MODE" "$KEEP_ON_FAIL" "$COVER" "$COVER_H" "$HOT_JSON" "$SPACE_ID" "$RESUME")

  MJS="$SCRIPTS_DIR/${platform}.mjs"
  if [ ! -f "$MJS" ]; then
    echo "缺少脚本: $MJS"
    # 不能直接 continue：那会跳过失败累计，结尾 exit "$FIRST_FAIL_RC" 变成 0，
    # 汇总里写着「失败(11)」而进程返回成功（实测可复现）。
    if [ "$FIRST_FAIL_RC" -eq 0 ]; then FIRST_FAIL_RC=11; fi
    SUMMARY="$SUMMARY\n  $platform  ❌ 失败(11) 缺脚本"
    if [ "${CONTINUE_ON_FAIL:-0}" != "1" ]; then break; fi
    continue
  fi

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
  # 汇总用的平台结果字段（必须在删临时文件之前取出）
  OK_BLOCK=$(grep -oE '=== OK \([^)]*\) ===' "$EGO_OUT" | tail -1 || true)
  P_STATE=$(printf '%s' "$OK_BLOCK" | sed -n 's/.*(\(.*\)).*/\1/p')
  P_URL=$(grep -E '^url      : ' "$EGO_OUT" | tail -1 | sed 's/^url      : //' || true)
  P_VF=$(grep -E '^verified : ' "$EGO_OUT" | tail -1 | sed 's/^verified : //' || true)
  P_MISS=$(grep -E '^topics_missing: ' "$EGO_OUT" | tail -1 | sed 's/^topics_missing: //' || true)
  rm -f "$EGO_OUT"

  if [ -n "$RC_BLOCK" ]; then
    EXIT_CODE=$RC_BLOCK
  elif [ -n "$RC_MSG" ]; then
    EXIT_CODE=$RC_MSG
  else
    EXIT_CODE=${RC_PIPE[1]:-0}
  fi

  # ego-browser 异常时可能返回 0 但脚本根本没跑完。没有 OK 块一律不算成功，
  # 否则 stage / draft / 卡死都会被汇总成「✅ 成功」。
  if [ "$EXIT_CODE" -eq 0 ] && [ -z "$OK_BLOCK" ]; then
    echo "  ⚠ 未见 === OK (...) === 块，判定为未确认（退出码 90）"
    EXIT_CODE=90
  fi

  if [ "$EXIT_CODE" -eq 0 ]; then
    SUMMARY="$SUMMARY\n  $platform  ✅ ${P_STATE:-已确认}"
    [ -n "$P_URL" ] && SUMMARY="$SUMMARY  ${P_URL}"
    [ -n "$P_VF" ] && SUMMARY="$SUMMARY  核验=${P_VF}"
    [ -n "$P_MISS" ] && SUMMARY="$SUMMARY  未挂话题=${P_MISS}"
  else
    if [ "$FIRST_FAIL_RC" -eq 0 ]; then FIRST_FAIL_RC=$EXIT_CODE; fi
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
exit "$FIRST_FAIL_RC"
