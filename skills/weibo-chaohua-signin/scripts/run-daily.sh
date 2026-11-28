#!/bin/bash
# 微博超话签到 - launchd 包装器
# 作用：调用 skill 脚本，并把结果弹到桌面通知
set -euo pipefail

SKILL_DIR="$HOME/.workbuddy/skills/weibo-chaohua-signin"
CODE=0
OUT="$("$SKILL_DIR/scripts/checkin.sh" 2>&1)" || CODE=$?
TS="$(date '+%H:%M')"
# 去掉 STATUS=xxx 前缀，通知只留可读文本（含连续签到天数）
TXT="$(printf '%s' "$OUT" | sed 's/^STATUS=[a-z]*  *//')"

case "$CODE" in
0)
  # 成功 / 已签到 —— 只有签到成功时才打扰，已签到静默
  case "$OUT" in
  *"签到成功"*)
    osascript -e "display notification \"${TXT//\"/}\" with title \"微博超话签到 · $TS\"" >/dev/null 2>&1
    ;;
  *)
    # 今天已签到，不通知
    ;;
  esac
  ;;
2)
  osascript -e "display notification \"登录态失效，请打开微博扫码重新登录\" with title \"微博超话签到 · $TS\"" >/dev/null 2>&1
  ;;
*)
  osascript -e "display notification \"${TXT//\"/}\" with title \"微博超话签到失败 · $TS\"" >/dev/null 2>&1
  ;;
esac

exit $CODE