#!/bin/bash
# 微博超话签到 - 默认张韶涵超话
# 依赖: ego-browser(ego-lite) 中已存在的微博登录态
set -euo pipefail

PAGE_ID="${WEIBO_PAGE_ID:-1008083da293788e69d1df81b6832c26b94d34}"
TOPIC_NAME="${WEIBO_TOPIC_NAME:-张韶涵}"
SPACE="${WEIBO_EGO_SPACE:-weibo daily signin}"

# 日志放 skill 目录外，skill 覆盖安装/更新时不丢历史签到记录
LOG_DIR="${WEIBO_LOG_DIR:-$HOME/.skill-data/weibo-chaohua-signin/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%F).log"

# 前一日日期，兼容 macOS(date -j -v) 与 GNU(date -d)
if date -j -v-1d -f "%Y-%m-%d" "2026-01-02" +%F >/dev/null 2>&1; then
  prev_day() { date -j -v-1d -f "%Y-%m-%d" "$1" +%F; }
else
  prev_day() { date -d "$1 -1 day" +%F; }
fi

# 连续签到天数：从指定日期往过去逐日回溯，日志中有成功记录(100000/382004)即计一天
# 结果写入 STREAK；STREAK_OPEN=1 表示回溯到日志覆盖的第一天仍连续，真实天数只会更多
STREAK=0
STREAK_OPEN=0
calc_streak() {
  local today="$1" today_ok="$2" d="" n=0 earliest=""
  STREAK=0
  STREAK_OPEN=0
  earliest=$(ls "$LOG_DIR"/[0-9]*.log 2>/dev/null | head -1) || true
  earliest=$(basename "$earliest" .log 2>/dev/null) || true
  # 本次调用成功即视今天已签到，无需等日志落盘
  if [ "$today_ok" = "1" ]; then
    n=1
    d=$(prev_day "$today") || d=""
  fi
  if [ -n "$d" ]; then
    while [ "$n" -lt 3650 ]; do
      if [ -f "$LOG_DIR/$d.log" ] && grep -qE 'code=(100000|382004)' "$LOG_DIR/$d.log"; then
        n=$((n + 1))
        d=$(prev_day "$d") || break
      else
        break
      fi
    done
  fi
  STREAK=$n
  # 只有回溯越过日志最早一天（或从无历史日志），才说明真实连续天数更长
  if [ "$n" -gt 0 ]; then
    if [ -z "$earliest" ] || [[ "$d" < "$earliest" ]]; then
      STREAK_OPEN=1
    fi
  fi
}

RAW=$(ego-browser nodejs <<JSEOF 2>&1
const space = "${SPACE}";
const pid = "${PAGE_ID}";
await useOrCreateTaskSpace(space);
await openOrReuseTab('https://weibo.com/page/' + pid, { wait: true, timeout: 30 });
await wait(8);
const r = await js(
  '(async () => {' +
  '  const body = new URLSearchParams({' +
  '    scene_id: "pc_checkin",' +
  '    page_id: "' + pid + '",' +
  '    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,' +
  '    lang: navigator.language || "zh-cn",' +
  '    plat: navigator.platform,' +
  '    ua: navigator.userAgent' +
  '  });' +
  '  try {' +
  '    const res = await fetch("/ajax_proxy/chaohua/page/checkin", {' +
  '      method: "POST",' +
  '      credentials: "include",' +
  '      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest" },' +
  '      body: body.toString()' +
  '    });' +
  '    const t = await res.text();' +
  '    let j = {};' +
  '    try { j = JSON.parse(t); } catch (e) { j = { raw: t.slice(0, 200) }; }' +
  '    return JSON.stringify({ http: res.status, code: j.code, msg: j.msg || j.raw || "", title: j.title || "", sub_title: j.sub_title || "" });' +
  '  } catch (e) {' +
  '    return JSON.stringify({ http: 0, code: -1, msg: String(e) });' +
  '  }' +
  '})()'
);
cliLog('RESULT: ' + r);
// 页面若展示「连续签到 N 天」则以页面为准，否则由本地日志回溯
const pageDays = await js(
  '(function () {' +
  '  var t = document.documentElement.textContent || "";' +
  '  var m = t.match(/连续签到[\\s]*([0-9]+)[\\s]*天/);' +
  '  return m ? m[1] : "";' +
  '})()'
);
cliLog('PAGEDAYS: ' + pageDays);
JSEOF
) || true

LINE=$(printf '%s\n' "$RAW" | grep -o 'RESULT: .*' | tail -1) || true

if [ -z "$LINE" ]; then
  printf '[%s] FAIL ego-browser 无结果输出\n' "$(date '+%F %T')" >> "$LOG_FILE"
  printf '%s\n' "$RAW" | tail -20 >> "$LOG_FILE"
  echo "STATUS=fail REASON=ego-browser 无输出（浏览器不可用或脚本报错）"
  exit 3
fi

CODE=$(printf '%s' "$LINE" | grep -o '"code":[0-9-]*' | head -1 | cut -d: -f2) || true
MSG=$(printf '%s' "$LINE" | grep -o '"msg":"[^"]*"' | head -1 | cut -d: -f2- | tr -d '"') || true
PAGE_DAYS=$(printf '%s\n' "$RAW" | grep -o 'PAGEDAYS: [0-9]*' | tail -1 | grep -o '[0-9]*') || true

case "$CODE" in
  100000|382004) TODAY_OK=1 ;;
  *) TODAY_OK=0 ;;
esac
calc_streak "$(date +%F)" "$TODAY_OK"
if [ -n "${PAGE_DAYS:-}" ]; then
  DAYS="$PAGE_DAYS"
  DAYS_SRC="page"
elif [ "$STREAK" -gt 0 ]; then
  DAYS="$STREAK"
  DAYS_SRC="log"
else
  DAYS=""
  DAYS_SRC="none"
fi

if [ -n "$DAYS" ]; then
  if [ "$DAYS_SRC" = "log" ] && [ "$STREAK_OPEN" = "1" ]; then
    DAYS_TXT="连续签到 ${DAYS} 天+"
  else
    DAYS_TXT="连续签到 ${DAYS} 天"
  fi
else
  DAYS_TXT="连续签到天数未知"
fi

printf '[%s] %s code=%s msg=%s streak=%s src=%s\n' "$(date '+%F %T')" "$TOPIC_NAME" "$CODE" "$MSG" "${DAYS:-0}" "$DAYS_SRC" >> "$LOG_FILE"

case "$CODE" in
  100000)
    echo "STATUS=ok  ${TOPIC_NAME}超话 签到成功 ${DAYS_TXT}"
    exit 0
    ;;
  382004)
    echo "STATUS=ok  ${TOPIC_NAME}超话 今天已签到 ${DAYS_TXT}"
    exit 0
    ;;
  100003)
    echo "STATUS=expired  ${TOPIC_NAME}超话 登录态失效，需要重新扫码登录"
    exit 2
    ;;
  *)
    echo "STATUS=fail  ${TOPIC_NAME}超话 签到失败 code=${CODE} msg=${MSG}"
    exit 1
    ;;
esac
