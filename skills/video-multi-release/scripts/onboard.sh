#!/usr/bin/env bash
# 首次配置 —— 写入 API Key 到 skill 根目录的 .env
#
# 密钥不写进任何脚本或文档正文，只落在 .env 里（默认被 .gitignore 忽略）。
# 重跑可覆盖。加 --verify 会调一次 TTS 接口验证 key 是否可用。

set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$SKILL_ROOT/.env"
TTS="$SKILL_ROOT/scripts/tts.py"

VERIFY=0
KEY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --verify) VERIFY=1; shift ;;
    --key) KEY="${2:-}"; shift 2 ;;
    -h|--help)
      echo "用法: bash scripts/onboard.sh [--key sk-xxxx] [--verify]"
      echo "  不带 --key 时交互输入（不回显）"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 10 ;;
  esac
done

echo "=========================================="
echo "  video-multi-release 首次配置"
echo "=========================================="
echo "配置目标: $ENV_FILE"
echo ""

if [ -f "$ENV_FILE" ]; then
  echo "已存在 .env，继续会覆盖。"
  if grep -qE '^DASHSCOPE_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
    echo "当前已配置 DASHSCOPE_API_KEY（值不显示）"
  fi
  echo ""
fi

if [ -z "$KEY" ]; then
  printf '请粘贴 DASHSCOPE_API_KEY（输入不回显）: '
  read -rs KEY || true
  echo ""
fi

if [ -z "$KEY" ]; then
  echo "错误: key 为空"
  exit 10
fi

case "$KEY" in
  sk-*) ;;
  *) echo "警告: key 通常以 sk- 开头，当前是 '${KEY:0:4}…'，已按原样写入" ;;
esac

umask 077
printf 'DASHSCOPE_API_KEY=%s\n' "$KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

if [ ! -s "$ENV_FILE" ]; then
  echo "错误: 写入失败"
  exit 11
fi
echo "✅ 已写入 ${ENV_FILE}（权限 600）"

# .gitignore 兜底：确保这个文件不会被同步出去
GI="$SKILL_ROOT/.gitignore"
if [ ! -f "$GI" ] || ! grep -qxF '.env' "$GI" 2>/dev/null; then
  printf '.env\n__pycache__/\n*.pyc\n' >> "$GI"
  echo "✅ 已把 .env 加入 .gitignore"
fi

if [ "$VERIFY" -eq 1 ]; then
  echo ""
  echo "验证 key…"
  TMP_JSON=$(mktemp /tmp/onboard-tts-XXXXXX.json)
  cat > "$TMP_JSON" <<'JSON'
{"segments":[{"id":"seg01","text":"验证语音合成是否可用。"}]}
JSON
  TMP_OUT=$(mktemp -d /tmp/onboard-audio-XXXXXX)
  if python3 "$TTS" --script "$TMP_JSON" --preset female --out-dir "$TMP_OUT" >/tmp/onboard-verify.log 2>&1; then
    echo "✅ key 可用，已成功合成一段测试音频"
  else
    echo "❌ 验证失败，输出如下："
    tail -15 /tmp/onboard-verify.log
    rm -f "$TMP_JSON"; rm -rf "$TMP_OUT"
    exit 20
  fi
  rm -f "$TMP_JSON"; rm -rf "$TMP_OUT"
fi

echo ""
echo "下一步："
echo "  1. 确认 ego-browser 已装、目标平台已登录"
echo "  2. 跑一次 stage 模式:"
echo "     PLATFORMS=channels VIDEO=/abs/v.mp4 TITLE=\"标题\" DESC='正文' MODE=stage \\"
echo "       bash $SKILL_ROOT/scripts/release.sh"
