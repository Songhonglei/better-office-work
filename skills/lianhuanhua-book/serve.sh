#!/usr/bin/env bash
# 本地预览：./serve.sh [端口]，默认 8788
# 用 pipeline/serve.py 起服务：响应带 Cache-Control: no-cache，
# 改完图或样式刷新即见，不会卡在旧缓存上。
set -e
cd "$(dirname "$0")"
PORT="${1:-8788}"
if [ ! -f site/index.html ]; then
  echo "站点尚未构建，先跑：python3 pipeline/build_site.py"
  exit 1
fi
exec python3 pipeline/serve.py "$PORT"
